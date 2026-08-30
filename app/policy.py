"""
Policy Engine
=============
Loads the per-use-case policy config that drives everything downstream:
which detectors run, how severe each risk type is considered, and where
the allow / auto-fix / escalate / block thresholds sit.

This is the mechanism that answers the Round 2 complexity: "different AI
use cases have very different risk tolerance and latency budgets — a
single, one-size-fits-all checking approach rarely works well everywhere."

Policies are versioned by hashing their contents, so every audit log entry
can record *exactly* which policy was active when a decision was made —
even after the policy has since been tuned by the feedback loop.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Dict

import yaml

POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"

# In-memory store of live threshold adjustments made by the feedback loop.
# Keyed by (use_case, detector_type) -> additive adjustment applied to the
# detector's effective confidence before scoring. Positive = stricter
# (harder to trigger), negative = looser (easier to trigger).
# Kept separate from the YAML files so the *base* policy authored by a
# human is never silently overwritten — the feedback loop only ever adds
# a visible, logged delta on top of it.
_CALIBRATION_ADJUSTMENTS: Dict[str, float] = {}


def _policy_hash(policy: dict, adjustments: dict) -> str:
    """Stable content hash used as the policy_version recorded in the audit log."""
    payload = json.dumps({"policy": policy, "adjustments": adjustments}, sort_keys=True)
    return "pv_" + hashlib.sha256(payload.encode()).hexdigest()[:10]


def list_use_cases():
    return sorted(p.stem for p in POLICY_DIR.glob("*.yaml"))


def load_policy(use_case: str) -> dict:
    path = POLICY_DIR / f"{use_case}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown use case '{use_case}'. Available: {list_use_cases()}")
    with open(path) as f:
        policy = yaml.safe_load(f)

    # Attach any live calibration adjustments for this use case.
    relevant_adjustments = {
        k.split("::")[1]: v
        for k, v in _CALIBRATION_ADJUSTMENTS.items()
        if k.startswith(f"{use_case}::")
    }
    policy["_calibration_adjustments"] = relevant_adjustments
    policy["policy_version"] = _policy_hash(
        {k: v for k, v in policy.items() if not k.startswith("_")},
        relevant_adjustments,
    )
    return policy


def get_adjustment(use_case: str, detector_type: str) -> float:
    return _CALIBRATION_ADJUSTMENTS.get(f"{use_case}::{detector_type}", 0.0)


def apply_adjustment(use_case: str, detector_type: str, delta: float, cap: float = 25.0):
    """
    Called by the feedback loop. Nudges a detector's effective severity
    weight for a specific use case up (stricter) or down (looser),
    clamped to +/- `cap` so a single noisy override can't swing behavior
    wildly. Every call republishes a new policy_version — thresholds
    never drift silently.
    """
    key = f"{use_case}::{detector_type}"
    current = _CALIBRATION_ADJUSTMENTS.get(key, 0.0)
    new_val = max(-cap, min(cap, current + delta))
    _CALIBRATION_ADJUSTMENTS[key] = new_val
    return new_val


def reset_adjustments():
    _CALIBRATION_ADJUSTMENTS.clear()
