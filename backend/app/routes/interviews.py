from typing import Optional
from zoneinfo import available_timezones

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, assert_hr_application_access, candidate_row_filter, candidate_owns, current_user, hr_can_access_job, require_hr_or_admin
from ..services import interview_service as svc
from ..services.email_service import dispatch_email

router = APIRouter(prefix="/interviews", tags=["interviews"])

COMMON_TIMEZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "Europe/Berlin",
                    "America/New_York", "America/Chicago", "America/Los_Angeles", "Australia/Sydney", "UTC"]


class InterviewCreate(BaseModel):
    application_id: int
    date: str
    time: str
    timezone: str = "Asia/Kolkata"
    duration_minutes: int = Field(45, ge=10, le=480)
    mode: str = "Google Meet"
    meeting_link: Optional[str] = None
    location: Optional[str] = None
    interviewer: Optional[str] = None
    notes: Optional[str] = None


class InterviewUpdate(BaseModel):
    date: Optional[str] = None
    time: Optional[str] = None
    timezone: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=10, le=480)
    mode: Optional[str] = None
    meeting_link: Optional[str] = None
    location: Optional[str] = None
    interviewer: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


def _dispatch(background: BackgroundTasks, ids: list[int]) -> None:
    for eid in ids:
        background.add_task(dispatch_email, eid)


def _interview_for(db: Session, schedule_id: int, user: Principal) -> models.InterviewSchedule:
    iv = db.get(models.InterviewSchedule, schedule_id)
    app = db.get(models.Application, iv.application_id) if iv else None
    if iv is None or app is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    if user.role == "candidate":
        if not candidate_owns(user, app.candidate):
            raise HTTPException(status_code=404, detail="Interview not found")
    elif not hr_can_access_job(user, app.job):
        raise HTTPException(status_code=404, detail="Interview not found")
    return iv


@router.get("/options")
def options(user: Principal = Depends(current_user)):
    return {"modes": list(svc.MODES), "statuses": list(svc.STATUSES), "timezones": COMMON_TIMEZONES,
            "all_timezones_count": len(available_timezones())}


@router.get("")
def list_interviews(scope: str = "all", user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """HR: interviews for their jobs. Candidate: their own interviews. scope=upcoming filters to active future ones."""
    from datetime import datetime
    q = db.query(models.InterviewSchedule).join(models.Application, models.Application.application_id ==
                                                models.InterviewSchedule.application_id)
    if user.role == "candidate":
        q = q.join(models.Candidate).filter(candidate_row_filter(user))
    elif user.role == "hr":
        q = q.join(models.JobRole).filter((models.JobRole.hr_account_id == user.id) | (models.JobRole.hr_account_id.is_(None)))
    if scope == "upcoming":
        q = q.filter(models.InterviewSchedule.status.in_(svc.ACTIVE),
                     models.InterviewSchedule.scheduled_at_utc >= datetime.utcnow())
    rows = q.order_by(models.InterviewSchedule.scheduled_at_utc.is_(None), models.InterviewSchedule.scheduled_at_utc).all()
    return [svc.interview_dict(db, iv, user.role) for iv in rows]


@router.post("")
def create_interview(payload: InterviewCreate, background: BackgroundTasks, user: Principal = Depends(require_hr_or_admin),
                     db: Session = Depends(get_db)):
    app = assert_hr_application_access(user, db.get(models.Application, payload.application_id))
    iv, email_ids = svc.schedule(db, user.id if user.role == "hr" else None, app, payload.model_dump())
    _dispatch(background, email_ids)   # emails go out only after the schedule was committed
    return svc.interview_dict(db, iv, user.role)


@router.get("/{schedule_id}")
def get_interview(schedule_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    return svc.interview_dict(db, _interview_for(db, schedule_id, user), user.role)


@router.put("/{schedule_id}")
def update_interview(schedule_id: int, payload: InterviewUpdate, background: BackgroundTasks,
                     user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    iv = _interview_for(db, schedule_id, user)
    iv, email_ids = svc.update(db, iv, payload.model_dump(exclude_unset=True))
    _dispatch(background, email_ids)
    return svc.interview_dict(db, iv, user.role)


@router.delete("/{schedule_id}")
def cancel_interview(schedule_id: int, background: BackgroundTasks, reason: Optional[str] = None,
                     user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    """Cancels (the row is kept for history)."""
    iv = _interview_for(db, schedule_id, user)
    _dispatch(background, svc.cancel(db, iv, reason))
    return svc.interview_dict(db, iv, user.role)


@router.post("/{schedule_id}/resend")
def resend_confirmation(schedule_id: int, background: BackgroundTasks, user: Principal = Depends(require_hr_or_admin),
                        db: Session = Depends(get_db)):
    iv = _interview_for(db, schedule_id, user)
    if iv.status not in svc.ACTIVE:
        raise HTTPException(status_code=409, detail="Only upcoming interviews can be re-sent")
    ids = svc.send_interview_confirmation(db, iv, updated=iv.status == "rescheduled")
    _dispatch(background, ids)
    return {"queued": len(ids)}
