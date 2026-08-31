"""
Decision Engine
================
Turns a list of detector findings into one of four actions, using
thresholds pulled from the active policy — never hard-coded — so the
same finding can be handled differently in a customer chatbot than in a
regulated decision-support tool.

Risk scoring: each finding's risk = severity_weight[risk_type] * confidence,
where severity_weight comes from the policy (+ any live feedback-loop
adjustment). The overall risk for a response is the MAX across findings,
not an average — a single severe issue should not be diluted by several
minor ones ("worst-dimension-dominates").

Tiers:
  risk <= allow_max      -> ALLOW        (delivered as-is, logged silently)
  <= autofix_max          -> AUTO_FIX     (targeted fix applied, delivered)
  <= escalate_max          -> ESCALATE     (held for human review)
  above escalate_max        -> BLOCK        (replaced with safe fallback)
"""
import re
from dataclasses import dataclass
from typing import List, Dict, Any

from app import policy as policy_engine

RISK_TYPE_TO_WEIGHT_KEY = {
    "privacy": "pii",
    "hallucination": "hallucination",
    "fairness": "bias",
}


@dataclass
class ScoredFinding:
    finding: dict
    risk_score: float


def _effective_weight(policy: dict, weight_key: str) -> float:
    base = policy["severity_weights"].get(weight_key, 50)
    adjustment = policy.get("_calibration_adjustments", {}).get(weight_key, 0.0)
    return max(0.0, min(100.0, base + adjustment))


def score_findings(findings: List[dict], policy: dict) -> List[ScoredFinding]:
    scored = []
    for f in findings:
        weight_key = RISK_TYPE_TO_WEIGHT_KEY.get(f["risk_type"], f["risk_type"])
        weight = _effective_weight(policy, weight_key)
        risk = round(weight * f["confidence"], 2)
        scored.append(ScoredFinding(finding=f, risk_score=risk))
    return scored


def _tier_for_risk(risk: float, thresholds: dict) -> str:
    if risk <= thresholds["allow_max"]:
        return "ALLOW"
    if risk <= thresholds["autofix_max"]:
        return "AUTO_FIX"
    if risk <= thresholds["escalate_max"]:
        return "ESCALATE"
    return "BLOCK"


def _apply_autofix(response_text: str, scored: List[ScoredFinding]):
    """Targeted fixes rather than a full rewrite: redact PII spans, and
    append an evidence caveat for ungrounded/low-confidence claims.
    Returns (fixed_text, actions) where actions is a human-readable log
    of exactly what was changed and why — used to drive the self-healing
    log in the dashboard."""
    fixed = response_text
    caveats = []
    actions = []

    for sf in scored:
        f = sf.finding
        if f["detector"] == "pii":
            span = f["span"]
            if span and span in fixed:
                fixed = fixed.replace(span, f"[REDACTED:{f['subtype'].upper()}]")
                actions.append(f"Redacted {f['subtype']} — \"{span}\"")
        elif f["detector"] == "grounding":
            short_span = f['span'][:70] + ('...' if len(f['span']) > 70 else '')
            caveats.append(f"⚠ Unverified claim: \"{short_span}\"")
            actions.append(f"Added verification caveat — \"{short_span}\"")

    if caveats:
        fixed = fixed.strip() + "\n\n[ControlPlane note — please verify: " + " | ".join(caveats) + "]"

    return fixed, actions


def decide(response_text: str, findings: List[dict], policy: dict,
           current_escalation_rate_per_1000: float = 0.0) -> Dict[str, Any]:
    scored = score_findings(findings, policy)
    overall_risk = max([sf.risk_score for sf in scored], default=0.0)
    thresholds = policy["thresholds"]
    tier = _tier_for_risk(overall_risk, thresholds)

    # Queue-aware throttling: if this use case's review queue is already
    # over budget, don't silently drop the issue — but do document that
    # it was downgraded to auto-fix under load, so it stays visible in
    # the audit trail instead of just vanishing.
    throttled = False
    if tier == "ESCALATE" and current_escalation_rate_per_1000 >= policy["review_queue_budget_per_1000"]:
        tier = "AUTO_FIX"
        throttled = True

    delivered_text = response_text
    actions = []
    if tier == "AUTO_FIX":
        delivered_text, actions = _apply_autofix(response_text, scored)
        if throttled:
            actions.append("Escalation downgraded to auto-fix — review queue over budget")
    elif tier == "BLOCK":
        delivered_text = (
            "This response was withheld by ControlPlane because it exceeded "
            "the configured risk threshold for this use case. A safe "
            "fallback is shown here while the issue is reviewed."
        )
        actions.append("Blocked — risk exceeded the configured threshold for this use case")
    elif tier == "ESCALATE":
        actions.append("Held for human review — risk exceeds the auto-fix threshold")
    else:
        actions.append("Delivered as-is — risk within the allow threshold")

    return {
        "tier": tier,
        "overall_risk": overall_risk,
        "throttled_from_escalate": throttled,
        "findings": [
            {**sf.finding, "risk_score": sf.risk_score} for sf in scored
        ],
        "actions": actions,
        "delivered_text": delivered_text,
        "policy_version": policy["policy_version"],
        "thresholds_used": thresholds,
    }
