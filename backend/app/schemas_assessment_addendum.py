"""
Append these to your existing backend/schemas.py (they follow the same
style as your JobRole/Candidate/Application schemas).
"""

from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime


# ---- Assessment: generation ----

class MCQOptionOut(BaseModel):
    label: str
    text: str


class AssessmentQuestionOut(BaseModel):
    """A single question as shown to the candidate — no answer key included."""
    index: int
    type: str  # "mcq" | "short_answer" | "coding"
    skill: str
    difficulty: str
    question: str
    options: Optional[List[MCQOptionOut]] = None


class GenerateAssessmentResponse(BaseModel):
    assessment_id: int
    application_id: int
    skills_covered: List[str]
    questions: List[AssessmentQuestionOut]
    # Optional state fields (added; older clients can ignore them).
    status: Optional[str] = None  # not_started | in_progress | completed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    draft_answers: Optional[Dict[str, str]] = None


class AssessmentStatusOut(BaseModel):
    application_id: int
    candidate_id: Optional[int] = None
    status: str  # not_started | in_progress | completed
    assessment_id: Optional[int] = None
    num_questions: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    test_score: Optional[float] = None
    final_score: Optional[float] = None
    skill_score: Optional[float] = None
    experience_score: Optional[float] = None
    screening_status: Optional[str] = None
    job_title: Optional[str] = None
    expires_at: Optional[datetime] = None
    remaining_seconds: Optional[int] = None     # computed by the server
    time_limit_minutes: Optional[int] = None
    auto_submitted: bool = False
    coding_questions: int = 0
    # Proctoring (services/proctor_service.py)
    proctoring_enabled: bool = False
    proctored: bool = False
    integrity: Optional[str] = None      # clean | flagged | terminated
    strikes: int = 0
    max_strikes: int = 3


class ProctoringStart(BaseModel):
    """What the candidate agreed to and what the pre-exam check found."""
    consent: bool = False
    checks: Dict[str, bool] = {}          # camera, microphone, face, rules, fullscreen ...
    engine: Optional[str] = None          # which face detector the browser used
    user_agent: Optional[str] = None


class StartAssessmentRequest(BaseModel):
    proctoring: Optional[ProctoringStart] = None


class ProctorEventIn(BaseModel):
    kind: str
    meta: Optional[Dict[str, Any]] = None
    snapshot: Optional[str] = None        # tiny JPEG data URL, only used for strikes


class ProctorEventsRequest(BaseModel):
    events: List[ProctorEventIn] = []
    answers: Optional[Dict[str, str]] = None   # latest answers, saved before a strike can end the test


class SaveProgressRequest(BaseModel):
    answers: Dict[str, str]


# ---- Assessment: submission / grading ----

class AssessmentAnswerIn(BaseModel):
    index: int          # matches AssessmentQuestionOut.index
    user_answer: str


class SubmitAssessmentRequest(BaseModel):
    answers: List[AssessmentAnswerIn]


class GradedQuestionOut(BaseModel):
    index: int
    question: str
    type: str
    user_answer: str
    correct: bool
    score: float
    feedback: str


class FinalScoreOut(BaseModel):
    skill_score: Optional[float] = None
    experience_score: Optional[float] = None
    test_score: Optional[float] = None
    final_score: Optional[float] = None
    skill_matched: Optional[str] = None
    skill_missing: Optional[str] = None
    recommendation: Optional[str] = None
    explanation: Optional[str] = None
    screening_status: Optional[str] = None

    class Config:
        from_attributes = True


class SubmitAssessmentResponse(BaseModel):
    application_id: int
    test_score_percent: float
    results: List[GradedQuestionOut]
    final_score: Optional[FinalScoreOut]
    completed_at: Optional[datetime] = None
    auto_submitted: bool = False
    ranking_status: Optional[str] = None  # completed | failed
    ranking_error: Optional[str] = None
    screening_retry: Optional[Dict[str, Any]] = None


class AssessmentOut(BaseModel):
    """Generic read model for GET /assessments/{application_id}"""
    assessment_id: int
    application_id: int
    score: Optional[float] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
