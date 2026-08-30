"""
Feedback Loop
==============
Closes the loop the brief asks for: "how flagged or overridden cases
feed back to improve detection quality over time."

When a reviewer resolves an ESCALATED item, they tell us one of three
things:
  - "agree"          the flag was correct, no change needed
  - "false_positive"  the detector over-flagged -> loosen that detector
                        slightly for this use case
  - "false_negative"  something worse was missed -> tighten that
                        detector slightly for this use case

Adjustments are small, capped, and applied via the policy engine, which
republishes a new policy_version rather than silently mutating behavior —
every subsequent audit log entry will show exactly which version (and
therefore which accumulated feedback) produced a given decision.

We deliberately do NOT auto-tune on every single override — a single
noisy data point shouldn't swing a production policy. Adjustments are
small (+/-3 per event, capped at +/-25 total) so it takes a consistent
pattern of overrides to meaningfully shift behavior, which is the
honest, defensible version of "the system learns."
"""
from typing import Dict, Any, List
from collections import defaultdict

from app import audit_log, policy as policy_engine
from app.decision_engine import RISK_TYPE_TO_WEIGHT_KEY

ADJUSTMENT_STEP = 3.0


def _dominant_weight_key(findings_json: str) -> str:
    import json
    findings = json.loads(findings_json)
    if not findings:
        return "hallucination"
    top = max(findings, key=lambda f: f.get("risk_score", f.get("confidence", 0)))
    return RISK_TYPE_TO_WEIGHT_KEY.get(top["risk_type"], top["risk_type"])


def submit_override(audit_log_id: int, reviewer: str, override_decision: str, note: str = "") -> Dict[str, Any]:
    entry = audit_log.get_entry(audit_log_id)
    if entry is None:
        raise ValueError(f"No audit log entry with id {audit_log_id}")

    audit_log.record_override(audit_log_id, reviewer, override_decision, note)

    weight_key = _dominant_weight_key(entry["findings_json"])
    use_case = entry["use_case"]

    delta = 0.0
    if override_decision == "false_positive":
        delta = -ADJUSTMENT_STEP
    elif override_decision == "false_negative":
        delta = +ADJUSTMENT_STEP

    new_adjustment = None
    if delta != 0.0:
        new_adjustment = policy_engine.apply_adjustment(use_case, weight_key, delta)

    return {
        "use_case": use_case,
        "detector_weight_key": weight_key,
        "override_decision": override_decision,
        "adjustment_delta": delta,
        "new_adjustment_total": new_adjustment,
        "new_policy_version": policy_engine.load_policy(use_case)["policy_version"],
    }


def calibration_stats(use_case: str) -> List[Dict[str, Any]]:
    """Rolling precision estimate per detector for a use case, computed
    directly from logged overrides — no hidden state, fully re-derivable
    from the audit trail at any time."""
    overrides = audit_log.overrides_for_use_case(use_case)
    tally = defaultdict(lambda: {"agree": 0, "false_positive": 0, "false_negative": 0})

    for o in overrides:
        weight_key = _dominant_weight_key(o["findings_json"])
        tally[weight_key][o["override_decision"]] += 1

    stats = []
    for weight_key, counts in tally.items():
        total = counts["agree"] + counts["false_positive"]
        precision = round(counts["agree"] / total, 2) if total else None
        stats.append({
            "detector": weight_key,
            "use_case": use_case,
            "agree": counts["agree"],
            "false_positive": counts["false_positive"],
            "false_negative": counts["false_negative"],
            "estimated_precision": precision,
            "current_adjustment": policy_engine.get_adjustment(use_case, weight_key),
        })
    return stats
