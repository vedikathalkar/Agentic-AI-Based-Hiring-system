import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, assert_candidate_application, current_user, require_candidate, require_hr_or_admin
from ..services import assessment_service, code_runner

router = APIRouter(prefix="/coding", tags=["coding"])


class CodeIn(BaseModel):
    application_id: int
    question_index: int
    language: str
    source: str = Field(max_length=100_000)


@router.get("/languages")
def languages(user: Principal = Depends(current_user)):
    return {"languages": code_runner.available_languages(), "sandbox": code_runner.sandbox_info()}


def _run(payload: CodeIn, kind: str, user: Principal, db: Session) -> dict:
    app = assert_candidate_application(user, db.get(models.Application, payload.application_id))
    return assessment_service.run_code(db, app, payload.question_index, payload.language, payload.source, kind)


@router.post("/run")
def run_code(payload: CodeIn, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    """Run against the visible sample tests only."""
    return _run(payload, "run", user, db)


@router.post("/submit")
def submit_code(payload: CodeIn, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    """Run against visible + hidden tests; the latest submission is what gets graded."""
    return _run(payload, "submit", user, db)


# ---- Problem bank (HR/admin) --------------------------------------------------

class TestCase(BaseModel):
    input: str = ""
    output: str


class Example(BaseModel):
    input: str = ""
    output: str
    explanation: Optional[str] = None


class ProblemIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    difficulty: str = "medium"
    tags: str = ""
    statement: str = Field(min_length=10)
    input_format: str = ""
    output_format: str = ""
    constraints: str = ""
    examples: List[Example] = []
    visible_tests: List[TestCase] = Field(min_length=1)
    hidden_tests: List[TestCase] = Field(min_length=1)
    time_limit_ms: int = Field(2000, ge=200, le=10000)
    memory_limit_mb: int = Field(256, ge=32, le=1024)
    active: bool = True


def _can_edit(user: Principal, p: models.CodingProblem) -> bool:
    return user.role == "admin" or (p.hr_account_id is not None and p.hr_account_id == user.id)


def _problem_dict(p: models.CodingProblem, user: Principal) -> dict:
    editable = _can_edit(user, p)
    hidden = json.loads(p.hidden_tests or "[]")
    return {
        "problem_id": p.problem_id, "title": p.title, "difficulty": p.difficulty, "tags": p.tags,
        "statement": p.statement, "input_format": p.input_format, "output_format": p.output_format,
        "constraints": p.constraints, "examples": json.loads(p.examples or "[]"),
        "visible_tests": json.loads(p.visible_tests or "[]"),
        "hidden_tests": hidden if editable else None, "hidden_test_count": len(hidden),
        "time_limit_ms": p.time_limit_ms, "memory_limit_mb": p.memory_limit_mb, "active": p.active,
        "library": p.hr_account_id is None, "editable": editable, "created_at": p.created_at,
    }


@router.get("/problems")
def list_problems(user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    q = db.query(models.CodingProblem)
    if user.role == "hr":
        q = q.filter((models.CodingProblem.hr_account_id.is_(None)) | (models.CodingProblem.hr_account_id == user.id))
    return [_problem_dict(p, user) for p in q.order_by(models.CodingProblem.problem_id).all()]


def _apply(p: models.CodingProblem, data: ProblemIn) -> None:
    p.title, p.difficulty, p.tags = data.title.strip(), data.difficulty, data.tags
    p.statement, p.input_format, p.output_format, p.constraints = (data.statement, data.input_format,
                                                                   data.output_format, data.constraints)
    p.examples = json.dumps([e.model_dump() for e in data.examples])
    p.visible_tests = json.dumps([t.model_dump() for t in data.visible_tests])
    p.hidden_tests = json.dumps([t.model_dump() for t in data.hidden_tests])
    p.time_limit_ms, p.memory_limit_mb, p.active = data.time_limit_ms, data.memory_limit_mb, data.active


@router.post("/problems")
def create_problem(data: ProblemIn, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    p = models.CodingProblem(hr_account_id=user.id if user.role == "hr" else None)
    _apply(p, data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _problem_dict(p, user)


@router.put("/problems/{problem_id}")
def update_problem(problem_id: int, data: ProblemIn, user: Principal = Depends(require_hr_or_admin),
                   db: Session = Depends(get_db)):
    p = db.get(models.CodingProblem, problem_id)
    if p is None or not _can_edit(user, p):
        raise HTTPException(status_code=404, detail="Problem not found")
    _apply(p, data)
    db.commit()
    return _problem_dict(p, user)


class VerifyIn(BaseModel):
    language: str
    source: str


@router.post("/problems/{problem_id}/verify")
def verify_problem(problem_id: int, payload: VerifyIn, user: Principal = Depends(require_hr_or_admin),
                   db: Session = Depends(get_db)):
    """Run a reference solution against all tests so authors can validate their cases."""
    p = db.get(models.CodingProblem, problem_id)
    if p is None or not (_can_edit(user, p) or p.hr_account_id is None):
        raise HTTPException(status_code=404, detail="Problem not found")
    tests = json.loads(p.visible_tests or "[]") + (json.loads(p.hidden_tests or "[]") if _can_edit(user, p) else [])
    r = code_runner.execute(payload.language, payload.source, tests, p.time_limit_ms, p.memory_limit_mb)
    return {"status": r.status, "passed": r.passed, "total": r.total, "error": r.error,
            "time_ms": r.time_ms, "memory_kb": r.memory_kb}
