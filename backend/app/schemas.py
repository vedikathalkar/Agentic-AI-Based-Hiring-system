import re
from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator

# Weights must be real, non-null integers >= 0 (no floats, no strings, no null).
StrictWeight = Annotated[StrictInt, Field(ge=0)]


# ---- Job Role ----
_REQ_SPLIT = re.compile(r"[,;\n]")


class JobRoleBase(BaseModel):
    title: str
    team: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    preferred_skills: Optional[str] = None
    education_requirement: Optional[str] = None
    min_experience: Optional[float] = 0
    open_positions: Optional[int] = 1
    weight_skill: Optional[int] = 40
    weight_experience: Optional[int] = 20
    weight_test: Optional[int] = 40
    coding_questions: Optional[int] = 0
    assessment_minutes: Optional[int] = 30


class JobRoleCreate(JobRoleBase):
    """Validated input for POST /jobs. Invalid payloads return 422."""
    requirements: str
    min_experience: float = 0
    weight_skill: StrictWeight = 40
    weight_experience: StrictWeight = 20
    weight_test: StrictWeight = 40
    coding_questions: Annotated[int, Field(ge=0, le=3)] = 0
    assessment_minutes: Annotated[int, Field(ge=5, le=180)] = 30

    @field_validator("title")
    @classmethod
    def validate_title(cls, value):
        if not value or not value.strip():
            raise ValueError("title is required")
        return value.strip()

    @field_validator("min_experience")
    @classmethod
    def validate_min_experience(cls, value):
        if value is None or value < 0:
            raise ValueError("min_experience must be >= 0")
        return value

    @field_validator("requirements")
    @classmethod
    def validate_requirements(cls, value):
        parts = [p.strip() for p in _REQ_SPLIT.split(value or "") if p.strip()]
        if not parts:
            raise ValueError("requirements must contain at least one skill (separate skills with commas, semicolons or new lines)")
        return value.strip()

    @model_validator(mode="after")
    def validate_weight_total(self):
        total = self.weight_skill + self.weight_experience + self.weight_test
        if total != 100:
            raise ValueError(f"weights must sum to exactly 100 (skill + experience + assessment = {total})")
        return self


class JobRoleOut(JobRoleBase):
    """Read model. Deliberately does not inherit the create validators so
    legacy rows (e.g. missing requirements) can still be listed."""
    job_id: int
    created_at: Optional[datetime] = None
    status: Optional[str] = "open"
    hr_account_id: Optional[int] = None
    company_name: Optional[str] = None

    class Config:
        from_attributes = True


# ---- Candidate ----
class CandidateCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    job_id: int  # which job they're applying for


class CandidateOut(BaseModel):
    candidate_id: int
    name: str
    email: str
    phone: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Application (candidate x job, with scores/status) ----
class ApplicationOut(BaseModel):
    application_id: int
    candidate_id: int
    job_id: int
    status: str
    applied_at: datetime
    candidate_name: Optional[str] = None
    job_title: Optional[str] = None
    skill_score: Optional[float] = None
    experience_score: Optional[float] = None
    test_score: Optional[float] = None
    final_score: Optional[float] = None
    skill_matched: Optional[str] = None
    skill_missing: Optional[str] = None
    recommendation: Optional[str] = None
    ranking_explanation: Optional[str] = None
    screening_status: Optional[str] = None
    assessment_status: Optional[str] = None  # not_started | in_progress | completed
    assessment_completed_at: Optional[datetime] = None
    candidate_email: Optional[str] = None
    experience_years: Optional[float] = None
    has_resume: Optional[bool] = None

    class Config:
        from_attributes = True


# Existing application status vocabulary (see models.Application).
APPLICATION_STATUSES = (
    "submitted", "parsed", "in_review", "assessed",
    "shortlisted", "scheduled", "interviewed", "selected",
    "offered", "hired", "offer_declined", "rejected",
)
HR_SETTABLE_STATUSES = ("in_review", "shortlisted", "interviewed", "selected", "rejected")


class StatusUpdate(BaseModel):
    status: str
    note: Optional[str] = None      # optional message from HR, shown to the candidate with the explanation

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        value = (value or "").strip().lower()
        if value not in APPLICATION_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(APPLICATION_STATUSES)}")
        return value


# ---- Authentication ----
class CandidateSignup(BaseModel):
    name: str
    email: str
    password: str


class HRSignup(BaseModel):
    name: str
    company: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str
