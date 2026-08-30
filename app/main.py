"""
ControlPlane.ai — Prototype API
=================================
Run with:
    uvicorn app.main:app --reload --port 8000

Then either hit the endpoints directly, or run the Streamlit dashboard
(dashboard/dashboard.py) which talks to this API.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import policy as policy_engine
from app import llm_client, audit_log, feedback, pipeline

app = FastAPI(title="ControlPlane.ai Prototype API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

audit_log.init_db()


@app.get("/policies")
def get_policies():
    return {uc: policy_engine.load_policy(uc) for uc in policy_engine.list_use_cases()}


@app.get("/scenarios")
def get_scenarios(use_case: str = None):
    return llm_client.list_scenarios(use_case)


class SimulateRequest(BaseModel):
    scenario_id: str
    use_case: str = None


@app.post("/simulate")
def simulate(req: SimulateRequest):
    try:
        return pipeline.run_scenario(req.scenario_id, req.use_case)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class OverrideRequest(BaseModel):
    audit_log_id: int
    reviewer: str
    override_decision: str  # 'agree' | 'false_positive' | 'false_negative'
    note: str = ""


@app.post("/override")
def override(req: OverrideRequest):
    try:
        return feedback.submit_override(
            req.audit_log_id, req.reviewer, req.override_decision, req.note
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/audit_log")
def get_audit_log(use_case: str = None, limit: int = 50):
    return audit_log.recent_entries(use_case, limit)


@app.get("/calibration")
def get_calibration(use_case: str):
    return feedback.calibration_stats(use_case)


@app.get("/metrics")
def get_metrics():
    return audit_log.metrics_summary()


@app.get("/health")
def health():
    return {"status": "ok"}
