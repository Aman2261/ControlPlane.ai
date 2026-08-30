# ControlPlane.ai

A real-time AI governance layer that sits between an application and any
LLM, scoring every response across **privacy (PII)**, **hallucination /
grounding**, and **bias / fairness**, then routing it through a four-tier
decision engine — **allow / auto-fix / escalate / block** — whose
thresholds are configurable per use case. Every decision is written to an
immutable audit log, and human reviewer overrides feed a calibration loop
that adjusts detector strictness over time.

This repository is a working prototype: the detectors, decision engine,
audit log, and feedback loop all run real logic against real input text,
not a mockup.

## Features

- **Three independent detectors** running in parallel on plain
  request/response text — no access to model internals required
- **Policy-driven decision engine** — the same finding can be handled
  differently depending on the use case's configured risk tolerance
- **Immutable, versioned audit log** — every decision records which
  policy version was active at the time
- **Feedback loop** — reviewer overrides on escalated items adjust
  detector thresholds and republish a new policy version, rather than
  silently drifting
- **Interactive dashboard** to run scenarios, review escalations, and
  inspect metrics live
- **REST API** exposing the same pipeline for integration into other
  services

## Quick start

```bash
pip install -r requirements.txt

# Option A — CLI walkthrough (no server needed)
python3 run_demo.py

# Option B — full interactive dashboard
uvicorn app.main:app --reload --port 8000   # in one terminal
streamlit run dashboard/dashboard.py         # in another terminal
```

The dashboard talks directly to the pipeline in-process, so
`streamlit run dashboard/dashboard.py` alone is enough to see it work.
The FastAPI server exposes the same pipeline as a REST API for
integration into other services.

## Architecture

```
Request + policy context  →  LLM generation + sidecar tap  →  Detection layer
        (per use case)             (swappable model)         (3 parallel detectors)
                                                                       ↓
Audit log + feedback loop  ←   Decision engine (4-tier)   ←   Risk scoring
  (immutable, versioned)      (thresholds from policy)      (severity × confidence)
```

ControlPlane operates entirely at the **input/output text layer** — it
never requires access to model weights, logits, or internals, so it works
with any model consumed via API.

## Detectors

| Detector | File | Mechanism |
|---|---|---|
| **PII / Privacy** | `app/detectors/pii_detector.py` | Regex for structured PII (email, phone, SSN, credit card, DOB) plus a name-in-context heuristic |
| **Grounding / Hallucination** | `app/detectors/grounding_detector.py` | TF-IDF retrieval verification against source documents when available, with explicit numeric-fact contradiction checking; falls back to self-consistency comparison when no source is available |
| **Bias / Fairness** | `app/detectors/bias_detector.py` | Counterfactual outcome comparison (same request, one demographic-correlated attribute swapped) plus a lexicon-based stereotyping-language scan |

A single response can trigger findings from more than one detector — see
the `overlap_hallucination_privacy` scenario, where a fabricated clinical
detail about a named patient is flagged as both a hallucination and a
privacy risk.

## Use cases

Three example policies ship with the prototype, each with a different
risk posture:

| Use case | Policy file | Risk posture |
|---|---|---|
| Customer chatbot | `policies/customer_chatbot.yaml` | Real-time, high volume, lower individual stakes — tolerates more auto-fixing before escalating |
| Internal copilot | `policies/internal_copilot.yaml` | Employees act on the answers, but external liability is lower |
| Decision-support tool | `policies/decision_support.yaml` | Regulated workflow, outputs directly affect real people — lowest risk tolerance of the three |

Running the same finding through different policies produces different
decision tiers, since thresholds are defined per use case rather than
globally.

## Feedback loop

1. An escalated item is reviewed by a human and marked `agree`,
   `false_positive`, or `false_negative`.
2. The override is written to the audit trail and used to nudge that
   detector's effective severity weight for that use case (small, capped
   adjustments — a single override doesn't swing behavior).
3. A new policy version is published immediately; nothing drifts
   silently, and every audit log entry records exactly which policy
   version produced it.

Try it: run the `pii_leak` scenario on `customer_chatbot` (it escalates),
mark it `false_positive` a few times in the Reviewer queue tab, then
re-run the same scenario — the decision tier changes and a new policy
version is recorded.

## Project structure

```
app/
  policy.py            # loads and versions per-use-case policy config
  llm_client.py         # LLM client + demo scenario library
  detectors/
    pii_detector.py
    grounding_detector.py
    bias_detector.py
  decision_engine.py     # risk scoring + four-tier decision logic
  audit_log.py            # append-only SQLite audit trail
  feedback.py               # reviewer overrides -> calibration -> policy updates
  pipeline.py                # orchestrates the full pipeline
  main.py                      # FastAPI app
policies/                       # one YAML config per use case
dashboard/dashboard.py           # Streamlit demo UI
run_demo.py                       # CLI walkthrough of all demo scenarios
```

## Notes on prototype scope

- **LLM responses are pre-written demo scenarios** (`app/llm_client.py`)
  rather than live model calls, so the demo is deterministic and needs no
  API key. Swapping in a real model only requires changing `generate()`,
  since the rest of the pipeline only ever reads plain request/response
  text.
- **Grounding/hallucination detection uses TF-IDF similarity and numeric
  contradiction checking** rather than a trained embedding/NLI model — a
  lightweight but functional approximation of the same mechanism.
- Detectors are intentionally lightweight, rule-based approximations of
  production-grade equivalents (a trained fairness classifier, a
  dedicated PII model, an embedding-based NLI grounding check) —
  sufficient to demonstrate the mechanism, not tuned for production
  accuracy.
- Multi-turn/agentic compounding risk is not modeled — each request is
  scored independently.
- Queue-aware throttling in the decision engine is a simple rate check,
  not a full prioritization algorithm.

## License

MIT
