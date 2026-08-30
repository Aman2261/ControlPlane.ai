#!/usr/bin/env python3
"""
Runs every demo scenario through the full ControlPlane pipeline and prints
a readable summary — useful for a quick sanity check or a terminal-based
walkthrough without needing to stand up the API + dashboard.

Usage:
    python3 run_demo.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import audit_log, llm_client, pipeline

TIER_COLOR = {
    "ALLOW": "\033[92m",       # green
    "AUTO_FIX": "\033[94m",    # blue
    "ESCALATE": "\033[93m",    # yellow
    "BLOCK": "\033[91m",       # red
}
RESET = "\033[0m"


def main():
    audit_log.init_db()

    print("=" * 78)
    print("ControlPlane.ai — Prototype Pipeline Demo")
    print("=" * 78)

    for scenario_id in llm_client.SCENARIOS:
        result = pipeline.run_scenario(scenario_id)
        d = result["decision"]
        color = TIER_COLOR.get(d["tier"], "")

        print(f"\n--- Scenario: {result['scenario']['title']} "
              f"({result['use_case']}) ---")
        print(f"Prompt:   {result['scenario']['prompt']}")
        print(f"Response: {result['raw_response'][:120]}"
              f"{'...' if len(result['raw_response']) > 120 else ''}")
        print(f"Policy version: {result['policy_version']} "
              f"| Jurisdiction: {result['jurisdiction']}")

        if d["findings"]:
            print("Findings:")
            for f in d["findings"]:
                print(f"   - [{f['detector']:9s}] {f['subtype']:26s} "
                      f"confidence={f['confidence']:.2f}  risk={f['risk_score']:.1f}")
        else:
            print("Findings: none")

        print(f"Decision: {color}{d['tier']}{RESET}  "
              f"(overall_risk={d['overall_risk']:.1f}, "
              f"thresholds={d['thresholds_used']})")

        if d["tier"] in ("AUTO_FIX", "BLOCK"):
            print(f"Delivered text: {d['delivered_text'][:160]}"
                  f"{'...' if len(d['delivered_text']) > 160 else ''}")

    print("\n" + "=" * 78)
    print("Summary across all use cases:")
    metrics = audit_log.metrics_summary()
    print(json.dumps(metrics, indent=2))
    print("=" * 78)


if __name__ == "__main__":
    main()
