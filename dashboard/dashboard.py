"""
ControlPlane.ai — Prototype Dashboard
========================================
Run with:
    streamlit run dashboard/dashboard.py

Talks directly to the pipeline (no separate API server needed for the
dashboard itself) so it's a single command to get a live demo running.
The FastAPI app in app/main.py exposes the same functionality over HTTP
for anyone who wants to integrate ControlPlane as a real middleware layer.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from app import audit_log, llm_client, pipeline, feedback, policy as policy_engine

st.set_page_config(page_title="ControlPlane.ai", layout="wide", page_icon="🛡️")
audit_log.init_db()

TIER_STYLE = {
    "ALLOW": ("#1a7f37", "#e6f4ea"),
    "AUTO_FIX": ("#0969da", "#ddf1ff"),
    "ESCALATE": ("#9a6700", "#fff8c5"),
    "BLOCK": ("#cf222e", "#ffebe9"),
}


def tier_badge(tier: str):
    fg, bg = TIER_STYLE.get(tier, ("#333", "#eee"))
    st.markdown(
        f"<span style='background:{bg};color:{fg};padding:4px 12px;"
        f"border-radius:14px;font-weight:700;font-size:14px'>{tier}</span>",
        unsafe_allow_html=True,
    )


st.title("🛡️ ControlPlane.ai — Prototype")
st.caption("Real-time AI governance layer — run a scenario through the pipeline, "
           "watch the detectors fire, and see the policy-driven decision.")

# ---- top-level stat bar ------------------------------------------------
_m = audit_log.metrics_summary()
s1, s2, s3, s4 = st.columns(4)
s1.metric("Requests processed", _m["total_requests"])
s2.metric("Cache hit rate", f"{_m['cache_hit_rate']*100:.0f}%")
s3.metric("Cost saved (cache)", f"${_m['total_cost_saved']:.4f}")
s4.metric("Avg. detection latency", f"{_m['avg_detection_latency_ms']:.1f} ms")

use_cases = policy_engine.list_use_cases()
tab_run, tab_audit, tab_review, tab_metrics = st.tabs(
    ["▶ Run a request", "📜 Audit log", "🧑‍⚖️ Reviewer queue", "📊 Metrics & calibration"]
)

# ----------------------------------------------------------------------
with tab_run:
    col_a, col_b = st.columns([1, 2])

    with col_a:
        use_case = st.selectbox(
            "Use case", use_cases,
            format_func=lambda uc: policy_engine.load_policy(uc)["display_name"],
        )
        pol = policy_engine.load_policy(use_case)
        st.caption(f"Jurisdiction: **{pol['jurisdiction']}**")
        st.caption(f"Latency budget: **{pol['latency_budget_ms']} ms**")
        with st.expander("Active thresholds for this use case"):
            st.json(pol["thresholds"])
            st.json(pol["severity_weights"])
            if pol["_calibration_adjustments"]:
                st.write("Live feedback-loop adjustments:")
                st.json(pol["_calibration_adjustments"])

        scenarios = llm_client.list_scenarios(use_case)
        if not scenarios:
            st.warning("No demo scenarios tagged for this use case.")
        else:
            scenario_id = st.selectbox(
                "Demo scenario", [s["id"] for s in scenarios],
                format_func=lambda sid: next(s["title"] for s in scenarios if s["id"] == sid),
            )
            st.caption("💡 Run the same scenario twice in a row to see the semantic "
                       "cache hit — the second run costs $0 and skips detection entirely.")
            run = st.button("▶ Run through ControlPlane", type="primary", use_container_width=True)

    with col_b:
        if 'scenarios' in dir() and scenarios and run:
            result = pipeline.run_scenario(scenario_id, use_case)
            d = result["decision"]
            c = result["cost"]

            st.subheader(result["scenario"]["title"])
            st.markdown(f"**Prompt:** {result['scenario']['prompt']}")

            st.markdown("**Raw model response:**")
            st.info(result["raw_response"])

            # ---- cost of THIS response — prominent, per-request, not aggregate ----
            st.markdown("---")
            if c["cache_hit"]:
                cost_col, saved_col = st.columns(2)
                cost_col.metric("💵 Cost of this response", "$0.00000", delta="cache hit — no generation cost")
                saved_col.metric("💰 Saved vs. a fresh call", f"${c['cost_saved']:.5f}",
                                  delta=f"similarity {c['cache_similarity']:.2f}")
                st.caption("Served from the semantic cache — detection was skipped entirely for this request.")
            else:
                st.metric("💵 Cost of this response", f"${c['estimated_cost']:.5f}",
                           delta=f"{c['complexity']} query", delta_color="off")

            cc1, cc2 = st.columns(2)
            cc1.metric("Detection latency", f"{c['detection_latency_ms']:.2f} ms")
            cc2.metric("Cache size (this use case)", c["cache_size"])
            st.markdown("---")

            st.markdown("**Findings:**")
            if d["findings"]:
                df = pd.DataFrame(d["findings"])[
                    ["detector", "risk_type", "subtype", "confidence", "risk_score", "detail"]
                ]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.success("No findings — clean response.")

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Overall risk score", f"{d['overall_risk']:.1f}")
            with c2:
                tier_badge(d["tier"])
            with c3:
                st.caption(f"Policy version: `{d['policy_version']}`")

            if d["throttled_from_escalate"]:
                st.warning("⚠ This item would normally have been ESCALATED, but the "
                           "review queue budget for this use case was exceeded — "
                           "downgraded to AUTO_FIX and logged as such.")

            if d["tier"] in ("AUTO_FIX", "BLOCK"):
                st.markdown("**Delivered to user:**")
                st.warning(d["delivered_text"])

            st.caption(f"Logged as audit entry #{result['audit_id']}")

# ----------------------------------------------------------------------
with tab_audit:
    st.subheader("Audit log")
    filter_uc = st.selectbox("Filter by use case", ["(all)"] + use_cases, key="audit_filter")
    entries = audit_log.recent_entries(None if filter_uc == "(all)" else filter_uc, limit=100)
    if entries:
        df = pd.DataFrame(entries)[
            ["id", "timestamp", "use_case", "decision_tier", "overall_risk",
             "complexity", "estimated_cost", "cache_hit", "cost_saved",
             "detection_latency_ms", "policy_version", "scenario_id",
             "throttled_from_escalate"]
        ]
        df["estimated_cost"] = df["estimated_cost"].apply(lambda v: f"${v:.5f}")
        df["cost_saved"] = df["cost_saved"].apply(lambda v: f"${v:.5f}")
        df = df.rename(columns={"estimated_cost": "cost ($)", "cost_saved": "saved ($)"})
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No requests logged yet — run a scenario in the first tab.")

# ----------------------------------------------------------------------
with tab_review:
    st.subheader("Reviewer queue — items awaiting human review")
    review_uc = st.selectbox("Use case", use_cases, key="review_uc")
    entries = [e for e in audit_log.recent_entries(review_uc, 100) if e["decision_tier"] == "ESCALATE"]

    if not entries:
        st.info("No escalated items for this use case yet.")
    else:
        options = {f"#{e['id']} — {e['scenario_id']} (risk={e['overall_risk']:.1f})": e for e in entries}
        choice = st.selectbox("Escalated item", list(options.keys()))
        entry = options[choice]

        st.markdown(f"**Request:** {entry['request_text']}")
        st.markdown("**Response:**")
        st.warning(entry["raw_response_text"])
        import json as _json
        st.markdown("**Findings that triggered escalation:**")
        st.dataframe(pd.DataFrame(_json.loads(entry["findings_json"])), use_container_width=True, hide_index=True)

        st.markdown("---")
        reviewer = st.text_input("Reviewer name", value="reviewer_1")
        decision = st.radio(
            "Your assessment",
            ["agree", "false_positive", "false_negative"],
            format_func=lambda x: {
                "agree": "✅ Agree — the flag was correct",
                "false_positive": "⬇ False positive — this was fine, loosen this detector",
                "false_negative": "⬆ False negative — something worse was missed, tighten this detector",
            }[x],
        )
        note = st.text_area("Note (optional)")

        if st.button("Submit review", type="primary"):
            result = feedback.submit_override(entry["id"], reviewer, decision, note)
            st.success(
                f"Recorded. Detector `{result['detector_weight_key']}` adjustment for "
                f"`{result['use_case']}` is now **{result['new_adjustment_total']}** "
                f"(policy republished as `{result['new_policy_version']}`)."
            )
            st.rerun()

# ----------------------------------------------------------------------
with tab_metrics:
    st.subheader("Decision breakdown by use case")
    metrics = audit_log.metrics_summary()
    if metrics["by_use_case_tier"]:
        df = pd.DataFrame(metrics["by_use_case_tier"])
        pivot = df.pivot_table(index="use_case", columns="decision_tier", values="c", fill_value=0)
        st.bar_chart(pivot)
        st.caption(
            f"Total requests processed: {metrics['total_requests']} · "
            f"Total reviewer overrides: {metrics['total_overrides']}"
        )
    else:
        st.info("No traffic yet — run some scenarios in the first tab.")

    st.subheader("Cost & caching")
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Total cost spent", f"${metrics['total_cost']:.5f}")
    mc2.metric("Total cost saved by cache", f"${metrics['total_cost_saved']:.5f}")
    mc3.metric("Cache hit rate", f"{metrics['cache_hit_rate']*100:.0f}%")
    mc4.metric("Avg. detection latency", f"{metrics['avg_detection_latency_ms']:.1f} ms")

    all_entries = audit_log.recent_entries(None, limit=200)
    if all_entries:
        cost_df = pd.DataFrame(all_entries)[["id", "use_case", "complexity", "estimated_cost", "cache_hit", "cost_saved"]]
        cost_df = cost_df.sort_values("id")
        cost_df["cumulative_cost"] = cost_df["estimated_cost"].cumsum()
        cost_df["cumulative_saved"] = cost_df["cost_saved"].cumsum()
        st.caption("Cumulative spend vs. cumulative savings from the semantic cache, in request order:")
        st.line_chart(cost_df.set_index("id")[["cumulative_cost", "cumulative_saved"]])
    else:
        st.info("No cost data yet — run some scenarios, then run the same one again to trigger a cache hit.")

    st.subheader("Detector calibration (from reviewer feedback)")
    for uc in use_cases:
        stats = feedback.calibration_stats(uc)
        if stats:
            st.markdown(f"**{policy_engine.load_policy(uc)['display_name']}**")
            st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)
    if not any(feedback.calibration_stats(uc) for uc in use_cases):
        st.info("No reviewer overrides yet — submit one in the Reviewer queue tab "
                 "to see calibration stats appear here.")
