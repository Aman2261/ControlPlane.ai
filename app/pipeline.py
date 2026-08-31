"""
Pipeline Orchestrator
======================
Wires the stages together end-to-end:

  0. cost control            -> cost_control.check_cache() / classify_complexity()
  1. request + policy context -> policy.load_policy()
  2. LLM generation + sidecar -> llm_client.generate()
  3. detection layer (parallel) -> pii / grounding / bias detectors
  4. risk scoring                -> decision_engine.score_findings()
  5. decision engine              -> decision_engine.decide()
  6. audit log                     -> audit_log.write_entry()

A semantic-cache check runs first: if a similar-enough prompt has been
seen before for this use case, the prior decision is replayed at zero
cost and detection is skipped entirely, rather than re-running
generation and all three detectors from scratch. On a cache miss,
detection runs as normal and the real wall-clock time it took is
recorded — a genuine latency measurement, not a simulated one — and the
result is stored in the cache for future requests.

Detectors run independently and their findings are merged before scoring,
so a single finding can legitimately carry information from more than one
detector's perspective (e.g. a hallucinated detail about a named person
is logged by both the grounding detector AND flagged for review as
privacy-adjacent) — matching the brief's point that these risks overlap
in practice rather than sorting cleanly into one bucket.
"""
import time
from typing import Optional, Dict, Any

from app import policy as policy_engine
from app import llm_client, audit_log, decision_engine, cost_control
from app.detectors import pii_detector, grounding_detector, bias_detector


def run_scenario(scenario_id: str, use_case: Optional[str] = None) -> Dict[str, Any]:
    scenario = llm_client.generate(scenario_id)
    use_case = use_case or scenario.use_case
    pol = policy_engine.load_policy(use_case)

    cache_hit = cost_control.check_cache(use_case, scenario.prompt)

    if cache_hit:
        decision = cache_hit["cached_decision"]
        complexity = decision.get("_complexity", "simple")
        detection_latency_ms = 0.0
        cost = 0.0
        cost_saved = cache_hit["original_cost"]
    else:
        t0 = time.perf_counter()
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

        detection_latency_ms = round((time.perf_counter() - t0) * 1000, 2)

        current_rate = audit_log.escalation_rate_per_1000(use_case)
        decision = decision_engine.decide(
            scenario.response, findings, pol,
            current_escalation_rate_per_1000=current_rate,
        )

        complexity = cost_control.classify_complexity(scenario.prompt)
        cost = cost_control.estimate_cost(scenario.prompt, scenario.response, complexity)
        cost_saved = 0.0

        decision["_complexity"] = complexity
        cost_control.store_cache(use_case, scenario.prompt, decision, cost)

    audit_id = audit_log.write_entry(
        use_case=use_case,
        jurisdiction=pol["jurisdiction"],
        policy_version=decision["policy_version"],
        scenario_id=scenario_id,
        request_text=scenario.prompt,
        raw_response_text=scenario.response,
        decision=decision,
        cost_info={
            "complexity": complexity,
            "estimated_cost": cost,
            "cache_hit": bool(cache_hit),
            "cache_similarity": cache_hit["similarity"] if cache_hit else None,
            "cost_saved": cost_saved,
            "detection_latency_ms": detection_latency_ms,
        },
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
        "policy_version": decision["policy_version"],
        "raw_response": scenario.response,
        "decision": decision,
        "cost": {
            "complexity": complexity,
            "estimated_cost": cost,
            "cache_hit": bool(cache_hit),
            "cache_similarity": cache_hit["similarity"] if cache_hit else None,
            "cost_saved": cost_saved,
            "detection_latency_ms": detection_latency_ms,
            "cache_size": cost_control.cache_size(use_case),
        },
    }
