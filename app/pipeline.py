"""
Pipeline Orchestrator
======================
Wires the six stages together end-to-end:

  1. request + policy context   -> policy.load_policy()
  2. LLM generation + sidecar   -> llm_client.generate()
  3. detection layer (parallel) -> pii / grounding / bias detectors
  4. risk scoring                -> decision_engine.score_findings()
  5. decision engine              -> decision_engine.decide()
  6. audit log                     -> audit_log.write_entry()

Detectors run independently and their findings are merged before scoring,
so a single finding can legitimately carry information from more than one
detector's perspective (e.g. a hallucinated detail about a named person
is logged by both the grounding detector AND flagged for review as
privacy-adjacent) — matching the brief's point that these risks overlap
in practice rather than sorting cleanly into one bucket.
"""
from typing import Optional, Dict, Any

from app import policy as policy_engine
from app import llm_client, audit_log, decision_engine
from app.detectors import pii_detector, grounding_detector, bias_detector


def run_scenario(scenario_id: str, use_case: Optional[str] = None) -> Dict[str, Any]:
    scenario = llm_client.generate(scenario_id)
    use_case = use_case or scenario.use_case
    pol = policy_engine.load_policy(use_case)

    findings = []

    if "pii" in pol["detectors_enabled"]:
        findings += [f.to_dict() for f in pii_detector.detect(scenario.response)]

    if "grounding" in pol["detectors_enabled"]:
        findings += [f.to_dict() for f in grounding_detector.detect(
            scenario.response,
            source_documents=scenario.source_documents,
            consistency_sample=scenario.consistency_sample,
        )]

    if "bias" in pol["detectors_enabled"]:
        findings += [f.to_dict() for f in bias_detector.detect(
            scenario.response,
            counterfactual_variants=scenario.counterfactual_variants,
        )]

    current_rate = audit_log.escalation_rate_per_1000(use_case)
    decision = decision_engine.decide(
        scenario.response, findings, pol,
        current_escalation_rate_per_1000=current_rate,
    )

    audit_id = audit_log.write_entry(
        use_case=use_case,
        jurisdiction=pol["jurisdiction"],
        policy_version=pol["policy_version"],
        scenario_id=scenario_id,
        request_text=scenario.prompt,
        raw_response_text=scenario.response,
        decision=decision,
    )

    return {
        "audit_id": audit_id,
        "scenario": {
            "id": scenario.id,
            "title": scenario.title,
            "prompt": scenario.prompt,
        },
        "use_case": use_case,
        "jurisdiction": pol["jurisdiction"],
        "policy_version": pol["policy_version"],
        "raw_response": scenario.response,
        "decision": decision,
    }
