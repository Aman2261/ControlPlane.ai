# ControlPlane.ai

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32-FF4B4B?logo=streamlit&logoColor=white)
![scikit--learn](https://img.shields.io/badge/scikit--learn-1.4-F7931E?logo=scikitlearn&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Task](https://img.shields.io/badge/Task-Responsible%20AI%20Governance-9C27B0)

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
- **Semantic cache + complexity router** — repeat/near-duplicate prompts
  are served at zero cost, and each prompt is priced by complexity tier
- **Policy-driven decision engine** — the same finding can be handled
  differently depending on the use case's configured risk tolerance
- **Immutable, versioned audit log** — every decision records which
  policy version was active at the time, plus cost, cache, and latency
  data for that request
- **Feedback loop** — reviewer overrides on escalated items adjust
  detector thresholds and republish a new policy version, rather than
  silently drifting
- **Two dashboards** — a single-page live view (`dashboard/index.html`)
  and a full tabbed Streamlit app (`dashboard/dashboard.py`) with audit
  log, reviewer queue, and cost/calibration metrics
- **REST API** exposing the same pipeline for integration into other
  services

## Quick start

```bash
pip install -r requirements.txt

# Option A — CLI walkthrough (no server needed)
python3 run_demo.py

# Option B — live single-page dashboard (recommended for demos)
uvicorn app.main:app --reload --port 8000        # terminal 1
python3 -m http.server 8080 --directory dashboard # terminal 2
# open http://localhost:8080/index.html

# Option C — full Streamlit dashboard (more detail, tab-based)
uvicorn app.main:app --reload --port 8000    # terminal 1
streamlit run dashboard/dashboard.py          # terminal 2
```

`dashboard/index.html` is a single-page live view — every request flows
through streaming inspection, detector findings, the risk matrix, the
self-healing log, and the reviewer queue on one screen, so the whole
pipeline is visible without switching tabs. It's a static file that talks
to the FastAPI backend over `fetch()`, so it needs to be served (not
opened directly as a `file://` URL) for the API calls to work — the
`python3 -m http.server` command above is the simplest way to do that.
If your backend runs somewhere other than `localhost:8000`, update the
`API_BASE` constant near the top of `dashboard/index.html`'s `<script>`.

`dashboard/dashboard.py` (Streamlit) covers the same functionality across
separate tabs, plus a metrics/calibration view better suited to reviewing
aggregate traffic after the fact rather than a single live walkthrough.

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

## Cost control

A fourth mechanism runs alongside the three detectors, implementing the
"Intelligent Cost Control" pillar: a **semantic cache** and a
**complexity router**.

- Every prompt is classified as `simple` or `complex` (based on length
  and a few reasoning-signal keywords) and priced accordingly.
- Before detection runs, the prompt is checked against a per-use-case
  cache of prior prompts using Jaccard similarity over tokenized text.
  A close-enough match (similarity ≥ 0.55) replays the cached decision
  instantly at zero cost and skips detection entirely — a real cache
  hit against real request text, not a hard-coded lookup.
- Detection latency is measured with a real wall-clock timer around the
  detector stage, not simulated.

Run any scenario twice in a row and the second run will register as a
cache hit — the dashboard's cost panel and the Metrics tab's cumulative
spend/savings chart both reflect it immediately.

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
  cost_control.py        # semantic cache + complexity-based cost estimation
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
dashboard/
  index.html                    # single-page live dashboard (static, calls the API)
  dashboard.py                    # Streamlit dashboard (tabbed, more detail)
run_demo.py                        # CLI walkthrough of all demo scenarios
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
- The semantic cache is in-memory and resets when the process restarts;
  a production version would back it with a persistent vector store.
  Cost figures use simulated per-token rates, not real API pricing.

## License

MIT
