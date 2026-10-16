"""Practice zone (candidates only): AI mock interviews and mock assessments."""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, require_candidate
from ..services import practice_service as svc

router = APIRouter(prefix="/practice", tags=["practice"])


class RoleIn(BaseModel):
    job_id: Optional[int] = None
    role_title: Optional[str] = Field(None, max_length=200)
    skills: List[str] = Field(default_factory=list, max_length=12)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class InterviewIn(RoleIn):
    interview_type: Literal["technical", "behavioural", "mixed"] = "mixed"
    num_questions: int = Field(5, ge=3, le=8)
    mode: Literal["practice", "interview"] = "interview"
    total_limit_minutes: Optional[int] = Field(None, ge=5, le=90)
    include_coding: bool = True


class AnswerIn(BaseModel):
    answer: str = Field("", max_length=20000)
    answer_mode: Literal["voice", "text", "code"] = "text"
    language: Optional[str] = None
    speaking_seconds: Optional[float] = Field(None, ge=0, le=3600)
    skipped: bool = False
    auto_submitted: bool = False


class CodeIn(BaseModel):
    language: str
    source: str = Field("", max_length=50000)
    question_index: Optional[int] = None


class AssessmentIn(RoleIn):
    num_mcq: int = Field(10, ge=3, le=25)
    num_coding: int = Field(1, ge=0, le=2)
    time_limit_minutes: Optional[int] = Field(None, ge=5, le=120)


class ProgressIn(BaseModel):
    answers: dict = Field(default_factory=dict)
    code: dict = Field(default_factory=dict)


@router.get("/roles")
def roles(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return svc.roles(db, user.id)


# ---- mock interviews -------------------------------------------------------------

@router.get("/interviews")
def list_interviews(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    rows = (db.query(models.MockInterview).filter(models.MockInterview.account_id == user.id)
            .order_by(models.MockInterview.interview_id.desc()).limit(30).all())
    return [svc.interview_dict(db, r, full=False) for r in rows]


@router.post("/interviews")
def create_interview(data: InterviewIn, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    # Plain def: the LLM call runs in a worker thread, not on the event loop.
    iv = svc.create_interview(db, user.id, data.model_dump())
    return svc.interview_dict(db, iv)


@router.get("/interviews/{interview_id}")
def get_interview(interview_id: int, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return svc.interview_dict(db, svc.own_interview(db, user.id, interview_id))


@router.post("/interviews/{interview_id}/begin")
def begin(interview_id: int, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    iv = svc.own_interview(db, user.id, interview_id)
    svc.begin_question(db, iv)
    return svc.interview_dict(db, iv)


@router.post("/interviews/{interview_id}/answer")
def answer(interview_id: int, data: AnswerIn, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    iv = svc.own_interview(db, user.id, interview_id)
    svc.answer_question(db, iv, data.model_dump())
    return svc.interview_dict(db, iv)


@router.post("/interviews/{interview_id}/run-code")
def run_interview_code(interview_id: int, data: CodeIn, user: Principal = Depends(require_candidate),
                       db: Session = Depends(get_db)):
    iv = svc.own_interview(db, user.id, interview_id)
    return svc.run_interview_code(db, iv, data.language, data.source)


@router.post("/interviews/{interview_id}/finish")
def finish(interview_id: int, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    iv = svc.own_interview(db, user.id, interview_id)
    svc.finish_interview(db, iv)
    return svc.interview_dict(db, iv)


# ---- mock assessments ------------------------------------------------------------

@router.get("/assessments")
def list_assessments(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    rows = (db.query(models.MockAssessment).filter(models.MockAssessment.account_id == user.id)
            .order_by(models.MockAssessment.mock_id.desc()).limit(30).all())
    return [svc.assessment_dict(db, r, full=False) for r in rows]


@router.post("/assessments")
def create_assessment(data: AssessmentIn, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return svc.assessment_dict(db, svc.create_assessment(db, user.id, data.model_dump()))


@router.get("/assessments/{mock_id}")
def get_assessment(mock_id: int, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return svc.assessment_dict(db, svc.own_assessment(db, user.id, mock_id))


@router.put("/assessments/{mock_id}/progress")
def save_progress(mock_id: int, data: ProgressIn, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    m = svc.own_assessment(db, user.id, mock_id)
    svc.save_progress(db, m, data.answers, data.code)
    return {"saved": True}


@router.post("/assessments/{mock_id}/run-code")
def run_assessment_code(mock_id: int, data: CodeIn, user: Principal = Depends(require_candidate),
                        db: Session = Depends(get_db)):
    m = svc.own_assessment(db, user.id, mock_id)
    return svc.run_assessment_code(db, m, data.question_index or 0, data.language, data.source)


@router.post("/assessments/{mock_id}/submit")
def submit_assessment(mock_id: int, data: ProgressIn, user: Principal = Depends(require_candidate),
                      db: Session = Depends(get_db)):
    m = svc.own_assessment(db, user.id, mock_id)
    svc.submit_assessment(db, m, data.answers, data.code)
    return svc.assessment_dict(db, m)

