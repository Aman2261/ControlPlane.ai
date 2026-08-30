# ControlPlane.ai — Round 2 Prototype

A working prototype of the real-time AI governance layer pitched in Round 1:
a policy-driven pipeline that scores every AI response across **privacy
(PII)**, **hallucination/grounding**, and **bias/fairness**, then routes it
through a four-tier decision engine (allow / auto-fix / escalate / block)
whose thresholds vary by use case — with a real audit trail and a real
feedback loop that recalibrates detector strictness from human overrides.

## Quick start

```bash
pip install -r requirements.txt

# Option A — CLI walkthrough (no server needed)
python3 run_demo.py

# Option B — full interactive dashboard
uvicorn app.main:app --reload --port 8000   # in one terminal
streamlit run dashboard/dashboard.py         # in another terminal
```

The dashboard talks directly to the pipeline in-process, so you technically
only need `streamlit run dashboard/dashboard.py` to see it work — the
FastAPI server is there to demonstrate ControlPlane as a real middleware
layer other services could call.

## What's real vs. simulated (read this before your pitch)

This is an honest prototype, not a mockup — the three detectors, the
policy-driven decision engine, the audit log, and the feedback loop all
run real logic against real input text, and the numbers you see change
based on what you feed them. Two things are intentionally simplified for
prototype scope, both flagged in-code:

- **LLM responses are pre-written scenarios**, not live model calls
  (`app/llm_client.py`). This makes the demo deterministic and reproducible
  without needing an API key. Swapping in a real model is a one-function
  change — `generate()` — because ControlPlane only ever reads plain
  request/response text, never model internals, by design (see
  "Architecture" below).
- **Grounding/hallucination detection uses TF-IDF similarity + numeric
  contradiction checking**, not a trained embedding/NLI model (which would
  need a model download this sandboxed environment can't reach). It's a
  genuine, working approximation of the same mechanism described in the
  Round 1 pitch, and the README/code comments say so explicitly rather
  than pretending otherwise.

## Architecture

```
Request + policy context  →  LLM generation + sidecar tap  →  Detection layer
        (per use case)          (simulated / swappable)      (3 parallel detectors)
                                                                       ↓
Audit log + feedback loop  ←   Decision engine (4-tier)   ←   Risk scoring
  (immutable, versioned)      (thresholds from policy)      (severity × confidence)
```

Everything operates at the **input/output text layer only** — no access to
model weights, logits, or internals — because the brief is explicit that
enterprises consume a foundation model via API rather than owning it.

## The three detectors

| Detector | File | Mechanism |
|---|---|---|
| **PII / Privacy** | `app/detectors/pii_detector.py` | Regex for structured PII (email, phone, SSN, credit card, DOB) + a name-in-context heuristic |
| **Grounding / Hallucination** | `app/detectors/grounding_detector.py` | TF-IDF retrieval verification against source docs when available, with explicit numeric-fact contradiction checking; falls back to self-consistency comparison when no source exists (the brief's "no reliable ground truth" case) |
| **Bias / Fairness** | `app/detectors/bias_detector.py` | Counterfactual outcome comparison (same request, one demographic-correlated attribute swapped — a real flip in recommendation is direct evidence of disparate treatment) + a lexicon-based stereotyping-language scan |

A single response can trigger findings from more than one detector — see
the `overlap_hallucination_privacy` scenario, where a fabricated clinical
detail about a named patient is flagged as **both** a hallucination and a
privacy risk, matching the brief's point that these risks overlap in
practice.

## The three use cases (and why they behave differently)

| Use case | Policy file | Risk posture |
|---|---|---|
| Customer chatbot | `policies/customer_chatbot.yaml` | Real-time, high volume, lower individual stakes — tolerates more auto-fixing before escalating |
| Internal copilot | `policies/internal_copilot.yaml` | Middle ground — employees act on answers, but external liability is lower |
| Decision-support tool | `policies/decision_support.yaml` | Regulated workflow, outputs directly affect real people — lowest risk tolerance of the three, even at the cost of more escalations |

Run the **same** `overlap_hallucination_privacy`-style finding through
`customer_chatbot` vs `decision_support` policies and you'll see different
tiers fire — that's the concrete proof that this isn't a one-size-fits-all
checker.

## The feedback loop, demonstrated

1. Run the `pii_leak` scenario (customer_chatbot) — it escalates.
2. In the dashboard's **Reviewer queue** tab, mark it `false_positive` three
   times.
3. Re-run the same scenario — watch it drop from ESCALATE to AUTO_FIX, and
   note the new `policy_version` in the response (thresholds never drift
   silently; every change republishes a versioned policy, visible in the
   audit log).

This is also scriptable — see the feedback-loop test block in the project
history, or just drive it through the dashboard live.

## Project structure

```
app/
  policy.py            # loads + versions per-use-case policy config
  llm_client.py         # simulated LLM + demo scenario library
  detectors/
    pii_detector.py
    grounding_detector.py
    bias_detector.py
  decision_engine.py     # risk scoring + 4-tier decision logic
  audit_log.py            # append-only SQLite audit trail
  feedback.py               # reviewer overrides -> calibration -> policy updates
  pipeline.py                # orchestrates all six stages
  main.py                      # FastAPI app
policies/                       # one YAML per use case
dashboard/dashboard.py           # Streamlit demo UI
run_demo.py                       # CLI walkthrough of all 6 scenarios
```

## Known limitations (be upfront about these in the pitch)

- Detectors are lightweight/rule-based approximations of the production
  pattern described in the proposal (embedding-based NLI, a trained
  fairness classifier, a dedicated PII model) — appropriate for
  demonstrating the *mechanism* at prototype scale, not production-grade
  accuracy.
- Multi-turn/agentic compounding risk (mentioned in the brief) is not
  modeled — each request is scored independently.
- The queue-aware throttling in the decision engine is a simple rate
  check, not a real prioritization algorithm.

These are exactly the kind of "reasonable assumptions" the brief invites —
state them clearly rather than let a judge find them unannounced.
