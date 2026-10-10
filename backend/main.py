from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.config import EVALUATION_DIR, OUTPUT_DIR
from backend.data_agent import RetailData
from backend.orchestrator import handle_issue, retail_data, retriever
from backend.safety_agent import inspect_and_mask

app = FastAPI(title="Punjab Sports Mart Retail Copilot", version="1.0")


class TriageRequest(BaseModel):
    issue: str = Field(min_length=3, max_length=4000)
    role: str = Field(default="Unknown", max_length=80)


class AnalyticsRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.get("/health")
def health():
    return {"status": "ok", "csv_tables_loaded": len(retail_data.tables), "retrieval_mode": retriever.retrieval_mode}


@app.post("/triage")
def triage(request: TriageRequest):
    try:
        if len(request.issue.strip()) < 3:
            raise HTTPException(status_code=400, detail="Describe the issue in at least three non-space characters.")
        return handle_issue(request.issue.strip(), request.role)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to process issue: {exc}")


@app.post("/analytics")
def analytics(request: AnalyticsRequest):
    if len(request.question.strip()) < 3:
        raise HTTPException(status_code=400, detail="Enter an analytics question with at least three non-space characters.")
    if inspect_and_mask(request.question)["restricted"]:
        return {"answer": "I cannot provide private customer, payment, credential, or contract data. This analytics endpoint only answers bounded questions over the supplied demo records.", "table": [], "data_used": [], "escalation": {"required": True, "team": "Security", "reason": "Restricted-data request."}}
    return retail_data.answer(request.question)


@app.get("/dashboard")
def dashboard():
    return retail_data.dashboard()


@app.post("/evaluate")
def evaluate():
    import pandas as pd
    from backend.config import EVALUATION_DIR, OUTPUT_DIR

    tests = pd.read_csv(EVALUATION_DIR / "public_test_cases.csv").fillna("")
    rows = []
    for test in tests.to_dict("records"):
        result = handle_issue(test["prompt"], test["persona"], use_llm=False)
        expected_sources = [s.strip() for s in test["expected_sources"].split(";") if s.strip()]
        rows.append({"test_id": test["test_id"], "category": result["category"], "priority": result["priority"], "confidence": result["confidence"], "answer": result["answer"], "citations": ";".join(result["citations"]), "data_used": ";".join(result["data_used"]), "escalated": "Yes" if result["escalation"]["required"] else "No", "escalation_team": result["escalation"]["team"], "pii_masked": "Yes" if result["pii_masked"] else "No", "safety_refusal": "Yes" if result["safety_refusal"] else "No", "notes": result["reasoning"], "expected_category": test["expected_category"], "expected_priority": test["expected_priority"], "category_correct": result["category"] == test["expected_category"], "priority_correct": result["priority"] == test["expected_priority"], "citation_present": bool(result["citations"]), "expected_source_hit": any(any(source.split("#")[0] in citation for citation in result["citations"]) for source in expected_sources), "safety_case": test["test_id"] in ["PUB-008", "PUB-009"], "data_case": test["test_id"] in ["PUB-003", "PUB-007", "PUB-010", "PUB-011"]})
    frame = pd.DataFrame(rows)
    public = frame[["test_id", "category", "priority", "confidence", "answer", "citations", "data_used", "escalated", "escalation_team", "pii_masked", "safety_refusal", "notes"]]
    public.to_csv(OUTPUT_DIR / "predictions.csv", index=False)
    safe_results = {row["test_id"]: row for row in rows}
    safety_passes = int(safe_results["PUB-008"]["safety_refusal"] == "Yes") + int(safe_results["PUB-009"]["pii_masked"] == "Yes" and safe_results["PUB-009"]["safety_refusal"] == "No")
    metrics = {"category_accuracy": float(frame.category_correct.mean()), "priority_accuracy": float(frame.priority_correct.mean()), "citation_presence": float(frame.citation_present.mean()), "expected_source_hit": float(frame.expected_source_hit.mean()), "safety_pass_rate": safety_passes / 2, "data_use_rate": float((frame[frame.data_case].data_used.str.len() > 0).mean())}
    return {"metrics": metrics, "cases": frame.drop(columns=["answer"]).to_dict("records"), "predictions_file": str(OUTPUT_DIR / "predictions.csv")}
