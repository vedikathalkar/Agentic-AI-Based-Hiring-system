from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..agents.skill_agent import score_skills
from ..database import get_db
from ..scoring_service import assessment_state
from ..security import Principal, candidate_row_filter, require_candidate, require_hr
from ..services import credits_service, interview_service, pipeline_service, profile_service
from .candidates import _to_application_out

router = APIRouter(tags=["dashboard"])

HR_DECIDED = ("shortlisted", "scheduled", "interviewed", "selected", "offered", "hired", "offer_declined", "rejected")


def my_applications(db: Session, user: Principal) -> list[models.Application]:
    return (db.query(models.Application).join(models.Candidate).filter(candidate_row_filter(user))
            .order_by(models.Application.applied_at.desc().nullslast(), models.Application.application_id.desc()).all())


@router.get("/me/applications")
def candidate_applications(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return [_to_application_out(a, db, user) for a in my_applications(db, user)]


def _stage(app: models.Application) -> str:
    s = app.status or "submitted"
    if s == "hired":
        return "hired"
    if s in ("offered", "offer_declined"):
        return "offer"
    if s in ("scheduled", "interviewed", "selected"):
        return "interview"
    if s == "shortlisted":
        return "shortlisted"
    if s == "rejected":
        return "rejected"
    if assessment_state(app.assessment) != "not_started" or s == "assessed":
        return "assessment"
    return "screening" if s in ("parsed", "in_review") else "applied"


@router.get("/dashboard/candidate")
def candidate_dashboard(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    apps = my_applications(db, user)
    profile = profile_service.get_candidate_profile(db, user.id)
    completion = profile_service.candidate_completion(user.account, profile)
    app_ids = [a.application_id for a in apps]
    interviews = []
    if app_ids:
        rows = (db.query(models.InterviewSchedule)
                .filter(models.InterviewSchedule.application_id.in_(app_ids),
                        models.InterviewSchedule.status.in_(interview_service.ACTIVE),
                        models.InterviewSchedule.scheduled_at_utc >= datetime.utcnow())
                .order_by(models.InterviewSchedule.scheduled_at_utc).all())
        interviews = [interview_service.interview_dict(db, iv, "candidate") for iv in rows]
    offers = (db.query(models.OfferLetter).filter(models.OfferLetter.application_id.in_(app_ids),
                                                  models.OfferLetter.status != "draft").all()) if app_ids else []
    pending = [a for a in apps if assessment_state(a.assessment) != "completed" and a.status not in ("rejected", "hired")]

    # Recommended: open jobs not yet applied to, ranked with the same skill matcher used for screening.
    skills = []
    from ..services.settings_service import get_settings
    allow_matching = get_settings(db, "candidate", user.id).allow_data_for_matching is not False
    for key in (("technical_skills", "tools", "frameworks", "languages") if allow_matching else ()):
        skills += profile_service._loads(getattr(profile, key))
    if not skills and allow_matching:
        latest = next((a.candidate.resume for a in apps if a.candidate and a.candidate.resume), None)
        skills = [s.strip() for s in (latest.skills or "").split(",")] if latest else []
    applied_jobs = {a.job_id for a in apps}
    recs = []
    for job in db.query(models.JobRole).filter((models.JobRole.status.is_(None)) | (models.JobRole.status == "open")).all():
        if job.job_id in applied_jobs:
            continue
        match = score_skills(skills, job.requirements or "") if skills else {"score": None, "matched": []}
        recs.append({"job_id": job.job_id, "title": job.title, "location": job.location, "team": job.team,
                     "match": match["score"], "matched": match["matched"][:5], "created_at": job.created_at})
    recs.sort(key=lambda r: (r["match"] is None, -(r["match"] or 0), -(r["created_at"].timestamp() if r["created_at"] else 0)))

    # Where each application is right now, in the candidate-facing pipeline (services/pipeline_service.py).
    stages = list(pipeline_service.KEYS) + ["hired"]
    counts = {s: 0 for s in stages + ["stopped"]}
    for a in apps:
        out = pipeline_service.pipeline_for_application(db, a)["outcome"]
        if out["state"] == "stopped":
            counts["stopped"] += 1
        elif out["state"] == "completed":
            counts["hired"] += 1
        else:
            counts[out["current"] or "applied"] += 1
    return {
        "name": user.name,
        "profile_completion": completion,
        "resume": {"uploaded": bool(profile.resume_path), "file_name": profile.resume_file_name,
                   "uploaded_at": profile.resume_uploaded_at},
        "stats": {
            "applications": len(apps),
            "assessments_pending": len(pending),
            "assessments_completed": sum(1 for a in apps if assessment_state(a.assessment) == "completed"),
            "upcoming_interviews": len(interviews),
            "shortlisted": sum(1 for a in apps if a.status in ("shortlisted", "scheduled", "interviewed", "selected")),
            "rejected": sum(1 for a in apps if a.status == "rejected"),
            "offers": sum(1 for o in offers if o.status in ("sent", "viewed", "accepted")),
            "credits": credits_service.balance(db, "candidate", user.id),
        },
        "pipeline": [{"stage": s, "count": counts[s], "label": pipeline_service.LABEL.get(s, "Hired")} for s in stages],
        "stopped_count": counts["stopped"],
        "applications": [{**_to_application_out(a, db, user), "stage": _stage(a)} for a in apps[:8]],
        "pending_assessments": [{"application_id": a.application_id, "job_title": a.job.title if a.job else None,
                                 "assessment_status": assessment_state(a.assessment)} for a in pending[:5]],
        "interviews": interviews[:5],
        "offers": [{"offer_id": o.offer_id, "status": o.status, "sent_at": o.sent_at, "expires_at": o.expires_at,
                    "job_title": (o.application.job.title if o.application and o.application.job else None)} for o in offers],
        "recommended_jobs": recs[:6],
    }


@router.get("/dashboard/hr")
def hr_dashboard(user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    jobs = (db.query(models.JobRole)
            .filter((models.JobRole.hr_account_id == user.id) | (models.JobRole.hr_account_id.is_(None))).all())
    job_ids = [j.job_id for j in jobs]
    apps = db.query(models.Application).filter(models.Application.job_id.in_(job_ids)).all() if job_ids else []
    app_ids = [a.application_id for a in apps]
    upcoming = []
    if app_ids:
        rows = (db.query(models.InterviewSchedule)
                .filter(models.InterviewSchedule.application_id.in_(app_ids),
                        models.InterviewSchedule.status.in_(interview_service.ACTIVE),
                        models.InterviewSchedule.scheduled_at_utc >= datetime.utcnow())
                .order_by(models.InterviewSchedule.scheduled_at_utc).all())
        upcoming = [interview_service.interview_dict(db, iv, "hr") for iv in rows]
    offers = db.query(models.OfferLetter).filter(models.OfferLetter.application_id.in_(app_ids)).all() if app_ids else []
    account, hp, company = user.account, profile_service.get_hr_profile(db, user.id), profile_service.get_company(db, user.account)
    assessed = [a for a in apps if a.status == "assessed" or (a.final_score and a.final_score.test_score is not None)
                or assessment_state(a.assessment) == "completed"]
    return {
        "stats": {
            "total_jobs": len(jobs), "open_jobs": sum(1 for j in jobs if (j.status or "open") == "open"),
            "total_applications": len(apps),
            "awaiting_review": sum(1 for a in apps if a.status not in HR_DECIDED),
            "assessed": len(assessed),
            "shortlisted": sum(1 for a in apps if a.status in ("shortlisted", "scheduled", "interviewed", "selected", "offered", "hired")),
            "scheduled_interviews": len(upcoming),
            "offers_sent": sum(1 for o in offers if o.status in ("sent", "viewed", "accepted", "rejected", "expired")),
            "hired": sum(1 for a in apps if a.status == "hired"),
        },
        "credits": credits_service.balance(db, "hr", user.id),
        "verification_state": profile_service.verification_state(account, hp, company),
        "profile_completion": profile_service.hr_completion(account, hp, company),
        "upcoming_interviews": upcoming[:6],
    }
