"""Interview scheduling, confirmation emails and one-day-before reminders."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from . import config, hiring_context as ctx
from .email_service import EmailService, dispatch_email
from .notification_service import notify

logger = logging.getLogger(__name__)

ACTIVE = ("scheduled", "confirmed", "rescheduled")
STATUSES = ("scheduled", "confirmed", "completed", "cancelled", "rescheduled")
MODES = ("Google Meet", "Zoom", "Microsoft Teams", "Phone", "On-site")
REMINDER_WINDOW = timedelta(hours=24)


def to_utc(date: str, time: str, tz: str) -> datetime:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=422, detail=f"Unknown timezone: {tz}")
    try:
        local = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=zone)
    except ValueError:
        raise HTTPException(status_code=422, detail="Date must be YYYY-MM-DD and time HH:MM")
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def labels(iv: models.InterviewSchedule) -> dict:
    tz = iv.timezone or config.DEFAULT_TIMEZONE
    if iv.scheduled_at_utc:
        local = iv.scheduled_at_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz))
        return {"date_label": local.strftime("%A, %d %B %Y"), "time_label": local.strftime("%I:%M %p").lstrip("0"),
                "timezone": tz}
    return {"date_label": iv.date, "time_label": iv.time, "timezone": tz}


def _conflicts(db: Session, iv_id: Optional[int], start: datetime, minutes: int, hr_id: Optional[int],
               candidate_id: int, interviewer: Optional[str]) -> Optional[str]:
    end = start + timedelta(minutes=minutes)
    rows = (db.query(models.InterviewSchedule)
            .filter(models.InterviewSchedule.status.in_(ACTIVE),
                    models.InterviewSchedule.scheduled_at_utc.isnot(None),
                    models.InterviewSchedule.scheduled_at_utc < end,
                    models.InterviewSchedule.scheduled_at_utc > start - timedelta(hours=8)).all())
    for other in rows:
        if iv_id and other.schedule_id == iv_id:
            continue
        o_end = other.scheduled_at_utc + timedelta(minutes=other.duration_minutes or 45)
        if not (other.scheduled_at_utc < end and start < o_end):
            continue
        app = db.get(models.Application, other.application_id)
        if app and app.candidate_id == candidate_id:
            return "The candidate already has an interview at this time"
        if hr_id and other.hr_account_id == hr_id:
            return "You already have an interview scheduled at this time"
        if interviewer and other.interviewer and other.interviewer.strip().lower() == interviewer.strip().lower():
            return f"{interviewer} already has an interview at this time"
    return None


def _email_context(db: Session, iv: models.InterviewSchedule) -> dict:
    app = db.get(models.Application, iv.application_id)
    job = app.job if app else None
    hr = ctx.hr_for_job(db, job, iv.hr_account_id)
    cand = app.candidate if app else None
    return {
        "app": app, "job": job, "hr": hr, "candidate": cand,
        "vars": {
            "candidate_name": cand.name if cand else "Candidate", "candidate_email": cand.email if cand else None,
            "job_title": job.title if job else "the role", "company_name": ctx.company_name(db, hr),
            "hr_name": hr.name if hr else "there", "mode": iv.mode, "meeting_link": iv.meeting_link,
            "location": iv.location, "interviewer": iv.interviewer, "notes": iv.notes,
            "contact": ctx.company_contact(db, hr), **labels(iv),
        },
    }


def _queue_pair(db: Session, iv: models.InterviewSchedule, template: str, subject_cand: str, subject_hr: str,
                extra: dict | None = None) -> list[int]:
    c = _email_context(db, iv)
    ids = []
    cand_account = ctx.candidate_account_for(db, c["candidate"])
    if c["candidate"] and c["candidate"].email:
        log = EmailService.queue(db, to=c["candidate"].email, subject=subject_cand, template=template,
                                 context={**c["vars"], **(extra or {}), "audience": "candidate",
                                          "recipient_name": c["vars"]["candidate_name"], "link": ctx.link("/interviews")},
                                 related_type="interview", related_id=iv.schedule_id,
                                 recipient_role="candidate", recipient_id=cand_account.account_id if cand_account else None,
                                 owner_role="hr", owner_id=c["hr"].account_id if c["hr"] else None)
        if log:
            ids.append(log.email_id)
    if c["hr"]:
        log = EmailService.queue(db, to=c["hr"].email, subject=subject_hr, template=template,
                                 context={**c["vars"], **(extra or {}), "audience": "hr",
                                          "recipient_name": c["hr"].name, "link": ctx.link("/hr/interviews")},
                                 related_type="interview", related_id=iv.schedule_id,
                                 recipient_role="hr", recipient_id=c["hr"].account_id,
                                 owner_role="hr", owner_id=c["hr"].account_id)
        if log:
            ids.append(log.email_id)
    return ids


def _notify_pair(db: Session, iv: models.InterviewSchedule, type: str, title: str, message: str) -> None:
    c = _email_context(db, iv)
    cand_account = ctx.candidate_account_for(db, c["candidate"])
    if cand_account:
        notify(db, "candidate", cand_account.account_id, type, title, message, "/interviews", commit=False)
    if c["hr"]:
        notify(db, "hr", c["hr"].account_id, type, title, f"{c['vars']['candidate_name']}: {message}",
               f"/hr/candidate/{c['candidate'].candidate_id}" if c["candidate"] else "/hr/interviews", commit=False)
    db.commit()


def _reminder_state_for(start_utc: datetime) -> str:
    # If the interview is less than a day away the confirmation email already
    # serves as the reminder; don't send a second "tomorrow" email.
    return "pending" if start_utc - datetime.utcnow() > REMINDER_WINDOW else "skipped"


def send_interview_confirmation(db: Session, iv: models.InterviewSchedule, updated: bool = False) -> list[int]:
    c = _email_context(db, iv)["vars"]
    word = "updated" if updated else "scheduled"
    return _queue_pair(db, iv, "interview_scheduled",
                       f"Interview {word}: {c['job_title']} — {c['company_name']}",
                       f"Interview {word}: {c['candidate_name']} — {c['job_title']}", {"updated": updated})


def schedule(db: Session, hr_id: Optional[int], app: models.Application, data: dict) -> tuple[models.InterviewSchedule, list[int]]:
    if app.status == "rejected":
        raise HTTPException(status_code=409, detail="This application was rejected; it can't be scheduled")
    if app.status in ("offered", "hired", "offer_declined"):
        raise HTTPException(status_code=409, detail="An offer has already been made for this application; it can't be scheduled")
    existing = (db.query(models.InterviewSchedule)
                .filter(models.InterviewSchedule.application_id == app.application_id,
                        models.InterviewSchedule.status.in_(ACTIVE)).first())
    if existing:
        raise HTTPException(status_code=409, detail="This candidate already has an upcoming interview — reschedule it instead")
    tz = data.get("timezone") or config.DEFAULT_TIMEZONE
    start = to_utc(data["date"], data["time"], tz)
    if start <= datetime.utcnow():
        raise HTTPException(status_code=422, detail="Interview time must be in the future")
    minutes = int(data.get("duration_minutes") or 45)
    conflict = _conflicts(db, None, start, minutes, hr_id, app.candidate_id, data.get("interviewer"))
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)
    iv = models.InterviewSchedule(
        application_id=app.application_id, date=data["date"], time=data["time"], timezone=tz,
        scheduled_at_utc=start, duration_minutes=minutes, mode=data.get("mode") or "Google Meet",
        meeting_link=data.get("meeting_link"), location=data.get("location"), interviewer=data.get("interviewer"),
        notes=data.get("notes"), hr_account_id=hr_id, status="scheduled",
        reminder_status=_reminder_state_for(start), created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db.add(iv)
    app.status = "scheduled"
    db.commit()           # the schedule is durable before any email is attempted
    db.refresh(iv)
    _notify_pair(db, iv, "interview_scheduled", "Interview scheduled",
                 f"{labels(iv)['date_label']} at {labels(iv)['time_label']} ({iv.timezone})")
    return iv, send_interview_confirmation(db, iv)


def update(db: Session, iv: models.InterviewSchedule, data: dict) -> tuple[models.InterviewSchedule, list[int]]:
    if iv.status in ("cancelled", "completed"):
        raise HTTPException(status_code=409, detail=f"Interview is already {iv.status}")
    new_status = data.get("status")
    if new_status and new_status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(STATUSES)}")
    app = db.get(models.Application, iv.application_id)
    time_changed = any(data.get(k) and data.get(k) != getattr(iv, k) for k in ("date", "time", "timezone"))
    if time_changed:
        date, time, tz = data.get("date") or iv.date, data.get("time") or iv.time, data.get("timezone") or iv.timezone
        start = to_utc(date, time, tz)
        if start <= datetime.utcnow():
            raise HTTPException(status_code=422, detail="Interview time must be in the future")
        minutes = int(data.get("duration_minutes") or iv.duration_minutes or 45)
        conflict = _conflicts(db, iv.schedule_id, start, minutes, iv.hr_account_id, app.candidate_id,
                              data.get("interviewer") or iv.interviewer)
        if conflict:
            raise HTTPException(status_code=409, detail=conflict)
        iv.date, iv.time, iv.timezone, iv.scheduled_at_utc = date, time, tz, start
        iv.status = "rescheduled"
        # A new time needs a new reminder.
        iv.reminder_status, iv.reminder_sent_at = _reminder_state_for(start), None
    # Only real changes to how/where the interview happens notify the candidate.
    venue_changed = any(k in data and data[k] is not None and (data[k] or None) != (getattr(iv, k) or None)
                        for k in ("mode", "meeting_link", "location"))
    for key in ("mode", "meeting_link", "location", "interviewer", "notes", "duration_minutes"):
        if key in data and data[key] is not None:
            setattr(iv, key, data[key])
    if new_status and not time_changed:
        iv.status = new_status
        if new_status == "completed" and app and app.status in ("scheduled", "shortlisted"):
            app.status = "interviewed"
    iv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(iv)
    ids: list[int] = []
    if time_changed:
        _notify_pair(db, iv, "interview_rescheduled", "Interview rescheduled",
                     f"New time: {labels(iv)['date_label']} at {labels(iv)['time_label']} ({iv.timezone})")
        ids = send_interview_confirmation(db, iv, updated=True)
    elif venue_changed and iv.status in ACTIVE:
        _notify_pair(db, iv, "interview_updated", "Interview details updated", f"Mode: {iv.mode}")
        ids = send_interview_confirmation(db, iv, updated=True)
    elif new_status == "confirmed":
        _notify_pair(db, iv, "interview_confirmed", "Interview confirmed", labels(iv)["date_label"])
    return iv, ids


def cancel(db: Session, iv: models.InterviewSchedule, reason: Optional[str]) -> list[int]:
    if iv.status == "cancelled":
        return []
    iv.status, iv.cancelled_at, iv.updated_at = "cancelled", datetime.utcnow(), datetime.utcnow()
    iv.reminder_status = "skipped" if iv.reminder_status != "sent" else iv.reminder_status
    app = db.get(models.Application, iv.application_id)
    if app and app.status == "scheduled":
        app.status = "shortlisted"
    db.commit()
    _notify_pair(db, iv, "interview_cancelled", "Interview cancelled", reason or "The interview was cancelled")
    c = _email_context(db, iv)["vars"]
    return _queue_pair(db, iv, "interview_updated", f"Interview cancelled: {c['job_title']}",
                       f"Interview cancelled: {c['candidate_name']}", {"status_label": "cancelled", "reason": reason})


def send_interview_reminder(db: Session, iv: models.InterviewSchedule) -> list[int]:
    c = _email_context(db, iv)["vars"]
    _notify_pair(db, iv, "interview_reminder", "Interview tomorrow",
                 f"{c['job_title']} — {c['date_label']} at {c['time_label']} ({c['timezone']})")
    return _queue_pair(db, iv, "interview_reminder", f"Reminder: Interview Tomorrow — {c['job_title']}",
                       f"Reminder: Interview Tomorrow — {c['candidate_name']} ({c['job_title']})")


def process_due_reminders(db: Session, now: Optional[datetime] = None, dispatch: bool = True) -> int:
    """Send the one-day-before reminder for every interview entering its 24h window.

    Idempotent: each interview is claimed with an atomic UPDATE
    (reminder_status pending -> sending), so running this twice — or from two
    workers at once — can never send two reminders.
    """
    now = now or datetime.utcnow()
    due = (db.query(models.InterviewSchedule.schedule_id)
           .filter(models.InterviewSchedule.status.in_(ACTIVE),
                   models.InterviewSchedule.scheduled_at_utc.isnot(None),
                   models.InterviewSchedule.scheduled_at_utc > now,
                   models.InterviewSchedule.scheduled_at_utc <= now + REMINDER_WINDOW,
                   (models.InterviewSchedule.reminder_status.is_(None)) |
                   (models.InterviewSchedule.reminder_status == "pending")).all())
    sent = 0
    for (sid,) in due:
        claimed = (db.query(models.InterviewSchedule)
                   .filter(models.InterviewSchedule.schedule_id == sid,
                           (models.InterviewSchedule.reminder_status.is_(None)) |
                           (models.InterviewSchedule.reminder_status == "pending"))
                   .update({"reminder_status": "sending"}, synchronize_session=False))
        db.commit()
        if not claimed:
            continue
        iv = db.get(models.InterviewSchedule, sid)
        try:
            ids = send_interview_reminder(db, iv)
            iv.reminder_status, iv.reminder_sent_at = "sent", datetime.utcnow()
            db.commit()
            sent += 1
            if dispatch:
                for eid in ids:
                    dispatch_email(eid)
        except Exception:  # noqa: BLE001
            logger.exception("Reminder for interview %s failed", sid)
            db.rollback()
            iv = db.get(models.InterviewSchedule, sid)
            iv.reminder_status = "failed"
            db.commit()
    return sent


def interview_dict(db: Session, iv: models.InterviewSchedule, viewer_role: str) -> dict:
    app = db.get(models.Application, iv.application_id)
    out = {
        "schedule_id": iv.schedule_id, "application_id": iv.application_id, "date": iv.date, "time": iv.time,
        "timezone": iv.timezone or config.DEFAULT_TIMEZONE, "scheduled_at_utc": iv.scheduled_at_utc,
        "duration_minutes": iv.duration_minutes, "mode": iv.mode, "status": iv.status,
        "meeting_link": iv.meeting_link, "location": iv.location, "interviewer": iv.interviewer,
        "candidate_name": app.candidate.name if app and app.candidate else None,
        "candidate_id": app.candidate_id if app else None,
        "job_title": app.job.title if app and app.job else None,
        "company_name": ctx.company_name(db, ctx.hr_for_job(db, app.job if app else None, iv.hr_account_id)),
        **labels(iv),
    }
    if viewer_role in ("hr", "admin"):
        email = app.candidate.email if app and app.candidate else None
        if viewer_role == "hr" and app is not None and email:
            unlocked = db.query(models.CandidateUnlock).filter(models.CandidateUnlock.application_id == app.application_id,
                                                               models.CandidateUnlock.hr_account_id == iv.hr_account_id).first()
            if not unlocked:
                name, domain = email.split("@", 1) if "@" in email else (email, "")
                email = f"{name[:1]}{'•' * max(3, len(name) - 1)}@{domain}"
        out.update({"notes": iv.notes, "reminder_status": iv.reminder_status, "reminder_sent_at": iv.reminder_sent_at,
                    "candidate_email": email})
    return out
