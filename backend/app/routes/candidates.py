import json
import logging
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..agents.skill_agent import parse_requirements
from ..database import get_db
from ..scoring_service import assessment_state, newest_application
from ..security import (Principal, candidate_owns, current_user, ensure_verified_hr, hr_can_access_job,
                        require_candidate, require_hr_or_admin)
from ..services import credits_service, feedback_service, files, hiring_context as ctx, pipeline_service
from ..services.email_service import EmailService, dispatch_email
from ..services.notification_service import notify

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/candidates", tags=["candidates"])

STATUS_LABELS = {"shortlisted": "Shortlisted", "rejected": "Not selected", "interviewed": "Interviewed",
                 "selected": "Selected", "in_review": "In review"}


def _split_csv(value: Optional[str]) -> list[str]:
    return [s.strip() for s in (value or "").split(",") if s.strip()]


def _is_unlocked(db: Session, user: Optional[Principal], app: models.Application) -> bool:
    if user is None:
        return False
    if user.role in ("admin", "candidate"):
        return True
    return db.query(models.CandidateUnlock).filter(models.CandidateUnlock.hr_account_id == user.id,
                                                   models.CandidateUnlock.application_id == app.application_id).first() is not None


def _mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    name, domain = email.split("@", 1)
    return f"{name[:1]}{'•' * max(3, len(name) - 1)}@{domain}"


def _to_application_out(app: models.Application, db: Optional[Session] = None, user: Optional[Principal] = None) -> dict:
    fs = app.final_score
    assessment = app.assessment
    resume = app.candidate.resume if app.candidate else None
    email = app.candidate.email if app.candidate else None
    if db is not None and user is not None and user.role == "hr" and not _is_unlocked(db, user, app):
        email = _mask_email(email)
    return {
        "application_id": app.application_id, "candidate_id": app.candidate_id, "job_id": app.job_id,
        "status": app.status, "applied_at": app.applied_at,
        "candidate_name": app.candidate.name if app.candidate else None, "candidate_email": email,
        "job_title": app.job.title if app.job else None,
        # Scores are passed through untouched: None = not calculated, 0 = real zero.
        "skill_score": fs.skill_score if fs else None,
        "experience_score": fs.experience_score if fs else None,
        "test_score": fs.test_score if fs else None,
        "final_score": fs.final_score if fs else None,
        "skill_matched": fs.skill_matched if fs else None,
        "skill_missing": fs.skill_missing if fs else None,
        "recommendation": fs.recommendation if fs else None,
        "ranking_explanation": (fs.explanation if fs else None) if (user is None or user.role != "candidate") else None,
        "screening_status": fs.screening_status if fs else None,
        "assessment_status": assessment_state(assessment),
        "assessment_completed_at": assessment.completed_at if assessment else None,
        "experience_years": resume.experience_years if resume else None,
        "has_resume": resume is not None,
        "pipeline": pipeline_service.pipeline_for_application(db, app),
        "decision_at": app.decision_at,
        "integrity": assessment.integrity if assessment is not None and assessment.proctored else None,
        "strikes": (assessment.strikes or 0) if assessment is not None else 0,
    }


def _candidate_or_404(candidate_id: int, db: Session) -> models.Candidate:
    candidate = db.query(models.Candidate).filter(models.Candidate.candidate_id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def _application_for(candidate_id: int, application_id: Optional[int], db: Session) -> models.Application:
    if application_id is not None:
        application = (db.query(models.Application)
                       .filter(models.Application.application_id == application_id,
                               models.Application.candidate_id == candidate_id).first())
    else:
        application = newest_application(db, candidate_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _authorized(user: Principal, candidate: models.Candidate, application: Optional[models.Application],
                allow_candidate: bool = True) -> None:
    if user.role == "admin":
        return
    if user.role == "candidate" and allow_candidate and candidate_owns(user, candidate):
        return
    if user.role == "hr" and application is not None and hr_can_access_job(user, application.job):
        return
    raise HTTPException(status_code=404, detail="Candidate not found")


@router.post("", response_model=schemas.ApplicationOut)
def create_candidate(payload: schemas.CandidateCreate, user: Principal = Depends(require_candidate),
                     db: Session = Depends(get_db)):
    """A logged-in candidate applies to a job (creates Candidate + Application)."""
    job = db.query(models.JobRole).filter(models.JobRole.job_id == payload.job_id).first()
    if not job or job.status == "closed":
        raise HTTPException(status_code=404, detail="Job not found or no longer accepting applications")
    duplicate = (db.query(models.Application).join(models.Candidate)
                 .filter(models.Application.job_id == job.job_id, models.Candidate.account_id == user.id).first())
    if duplicate:
        if duplicate.candidate is not None and duplicate.candidate.resume is None:
            # The earlier attempt stopped before a resume was attached: let the candidate finish it.
            return _to_application_out(duplicate)
        raise HTTPException(status_code=409, detail="You have already applied to this job")
    candidate = models.Candidate(name=(payload.name or user.name).strip(), email=(payload.email or user.email).strip(),
                                 phone=payload.phone, account_id=user.id)
    db.add(candidate)
    db.flush()
    application = models.Application(candidate_id=candidate.candidate_id, job_id=payload.job_id, status="submitted")
    db.add(application)
    db.commit()
    db.refresh(application)
    hr = ctx.hr_for_job(db, job)
    if hr:
        notify(db, "hr", hr.account_id, "application_received", "New application",
               f"{candidate.name} applied for {job.title}", f"/hr/candidate/{candidate.candidate_id}")
    return _to_application_out(application)


@router.get("", response_model=List[schemas.ApplicationOut])
def list_candidates(job_id: Optional[int] = Query(None), user: Principal = Depends(require_hr_or_admin),
                    db: Session = Depends(get_db)):
    """HR: applications for the jobs this account owns (plus legacy unowned jobs)."""
    query = db.query(models.Application).join(models.JobRole)
    if user.role == "hr":
        query = query.filter((models.JobRole.hr_account_id == user.id) | (models.JobRole.hr_account_id.is_(None)))
    if job_id is not None:
        query = query.filter(models.Application.job_id == job_id)
    applications = query.order_by(models.Application.applied_at.desc().nullslast(), models.Application.application_id.desc()).all()
    return [_to_application_out(a, db, user) for a in applications]


@router.get("/search")
def search_candidates(q: str = "", job_id: Optional[int] = Query(None), status: Optional[str] = None,
                      min_score: Optional[float] = None, min_experience: Optional[float] = None,
                      max_experience: Optional[float] = None, skills: Optional[str] = None,
                      user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    """HR: natural-language search over your applicants, e.g.
    "shortlisted python developers 3+ years score above 70"."""
    from ..services import search_service as search
    query = db.query(models.Application).join(models.JobRole)
    if user.role == "hr":
        query = query.filter((models.JobRole.hr_account_id == user.id) | (models.JobRole.hr_account_id.is_(None)))
    if job_id is not None:
        query = query.filter(models.Application.job_id == job_id)
    rows = []
    for a in query.order_by(models.Application.applied_at.desc().nullslast()).all():
        out = _to_application_out(a, db, user)
        resume = a.candidate.resume if a.candidate else None
        out["skills"] = (resume.skills if resume else "") or ""
        rows.append(out)
    vocab = {sk.strip() for r in rows for sk in r["skills"].split(",") if sk.strip()}
    parsed = search.parse_query(q[:300], extra_skills=vocab)
    f = search.merge_filters(parsed, skills=[x.strip() for x in (skills or "").split(",") if x.strip()], status=status,
                             min_score=min_score, min_experience=min_experience, max_experience=max_experience)
    ranked = search.rank_candidates(rows, f)
    return {"understood": search.describe(f), "corrections": parsed["corrections"], "total": len(ranked),
            "results": [{**r["row"], "relevance": r["score"], "matched_skills": r["matched_skills"], "reasons": r["reasons"]}
                        for r in ranked]}


@router.get("/{candidate_id}")
def get_candidate(candidate_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    candidate = _candidate_or_404(candidate_id, db)
    newest = newest_application(db, candidate_id)
    _authorized(user, candidate, newest)
    resume = candidate.resume
    unlocked = _is_unlocked(db, user, newest) if newest else user.role != "hr"
    applications = [_to_application_out(a, db, user) for a in sorted(
        candidate.applications, key=lambda a: (a.applied_at, a.application_id), reverse=True)]
    entries = []
    if resume and resume.experience_entries:
        try:
            entries = json.loads(resume.experience_entries)
        except (TypeError, ValueError):
            entries = []
    account = ctx.candidate_account_for(db, candidate)
    return {
        "candidate_id": candidate.candidate_id,
        "name": candidate.name,
        "email": candidate.email if unlocked else _mask_email(candidate.email),
        "phone": candidate.phone if unlocked else ("•••• ••••" if candidate.phone else None),
        "contact_unlocked": unlocked,
        "unlock_cost": credits_service.config.CREDIT_COSTS["candidate_unlock"],
        "has_account": account is not None,
        "created_at": candidate.created_at,
        "resume": {
            "file_name": resume.file_name,
            "uploaded_at": resume.uploaded_at,
            "file_available": bool(resume.file_path and os.path.isfile(resume.file_path)),
            "skills": resume.skills,
            "experience": resume.experience,
            "education": resume.education,  # informational only; not scored
            "experience_years": resume.experience_years,
            "experience_entries": entries,
        } if resume else None,
        "applications": applications,
    }


@router.post("/{candidate_id}/unlock")
def unlock_candidate(candidate_id: int, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    """Unlock contact details + original resume for this application (costs credits, once)."""
    candidate = _candidate_or_404(candidate_id, db)
    app = newest_application(db, candidate_id)
    _authorized(user, candidate, app, allow_candidate=False)
    if user.role == "admin" or _is_unlocked(db, user, app):
        return {"unlocked": True, "charged": 0, "balance": credits_service.balance(db, user.role, user.id)}
    ensure_verified_hr(db, user)
    tx = credits_service.spend(db, "hr", user.id, "candidate_unlock", f"Unlocked {candidate.name}",
                               reference=f"unlock:{app.application_id}", commit=False)
    db.add(models.CandidateUnlock(hr_account_id=user.id, application_id=app.application_id))
    db.commit()
    return {"unlocked": True, "charged": -(tx.amount) if tx else 0, "balance": credits_service.balance(db, "hr", user.id)}


@router.patch("/applications/{application_id}/status")
def update_status(application_id: int, payload: schemas.StatusUpdate, background: BackgroundTasks,
                  user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    app = db.query(models.Application).filter(models.Application.application_id == application_id).first()
    if not app or not hr_can_access_job(user, app.job):
        raise HTTPException(status_code=404, detail="Application not found")
    if payload.status not in schemas.HR_SETTABLE_STATUSES:
        raise HTTPException(status_code=422, detail=f"HR can set status to: {', '.join(schemas.HR_SETTABLE_STATUSES)}")
    if app.status == "hired":
        raise HTTPException(status_code=409, detail="The candidate has accepted an offer; status can't be changed")
    previous = app.status
    app.status = payload.status
    decided = payload.status in ("shortlisted", "rejected", "selected", "interviewed")
    if decided and previous != payload.status:
        # Record where the process stopped and snapshot the explanation the candidate will see.
        if payload.status == "rejected":
            app.decision_stage = pipeline_service.infer_stop_stage(pipeline_service.facts_for_application(db, app))
        else:
            app.decision_stage = None
        app.decision_note = (payload.note or "").strip()[:1000] or None
        app.decision_at = datetime.utcnow()
        db.flush()
        app.decision_feedback = json.dumps(feedback_service.build_feedback(feedback_service.facts_for_application(db, app)))
    db.commit()
    db.refresh(app)
    if previous != app.status and app.status in ("shortlisted", "rejected", "selected"):
        account = ctx.candidate_account_for(db, app.candidate)
        label = STATUS_LABELS.get(app.status, app.status)
        snap = json.loads(app.decision_feedback) if app.decision_feedback else {}
        if account:
            notify(db, "candidate", account.account_id, "application_status", f"Application {label.lower()}",
                   f"{app.job.title if app.job else 'Your application'}: {label}. {snap.get('headline', '')}".strip(), "/applications")
        hr = ctx.hr_for_job(db, app.job, user.id if user.role == "hr" else None)
        log = EmailService.queue(db, to=app.candidate.email, subject=f"Application update — {app.job.title if app.job else ''}",
                                 template="application_status",
                                 context={"candidate_name": app.candidate.name, "job_title": app.job.title if app.job else "",
                                          "company_name": ctx.company_name(db, hr), "status_label": label,
                                          "headline": snap.get("headline"), "summary": snap.get("summary"),
                                          "gaps": (snap.get("gaps") or [])[:4], "strengths": (snap.get("strengths") or [])[:3],
                                          "next_steps": (snap.get("next_steps") or [])[:3], "hr_note": snap.get("hr_note"),
                                          "link": ctx.link("/applications")},
                                 related_type="application", related_id=app.application_id,
                                 recipient_role="candidate", recipient_id=account.account_id if account else None,
                                 owner_role="hr", owner_id=hr.account_id if hr else None)
        if log:
            background.add_task(dispatch_email, log.email_id)
    return _to_application_out(app, db, user)


@router.get("/applications/{application_id}/feedback")
def application_feedback(application_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """The explained outcome for an application: where it stopped (or stands), what counted, what to do next.
    The candidate sees their own; HR sees the same text the candidate sees."""
    app = db.query(models.Application).filter(models.Application.application_id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if user.role == "candidate":
        if not candidate_owns(user, app.candidate):
            raise HTTPException(status_code=404, detail="Application not found")
    elif not (user.role == "admin" or (user.role == "hr" and hr_can_access_job(user, app.job))):
        raise HTTPException(status_code=404, detail="Application not found")
    return feedback_service.feedback_for_application(db, app)


@router.get("/{candidate_id}/scores")
def get_candidate_scores(candidate_id: int, application_id: Optional[int] = Query(None),
                         user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    """Main score source for the HR Candidate Detail page."""
    candidate = _candidate_or_404(candidate_id, db)
    application = _application_for(candidate_id, application_id, db)
    _authorized(user, candidate, application, allow_candidate=False)
    fs = application.final_score
    job = application.job
    return {
        "candidate_id": candidate_id, "application_id": application.application_id, "status": application.status,
        "skill_score": fs.skill_score if fs else None,
        "experience_score": fs.experience_score if fs else None,
        "test_score": fs.test_score if fs else None,
        "final_score": fs.final_score if fs else None,
        "recommendation": fs.recommendation if fs else None,
        "matched_skills": _split_csv(fs.skill_matched) if fs else [],
        "missing_skills": _split_csv(fs.skill_missing) if fs else [],
        "ranking_explanation": fs.explanation if fs else None,
        "screening_status": fs.screening_status if fs else None,
        "screening_error": fs.screening_error if fs else None,
        "assessment_status": assessment_state(application.assessment),
        "job": {
            "job_id": job.job_id, "title": job.title, "requirements": job.requirements or "",
            "requirements_list": parse_requirements(job.requirements or ""),
            "min_experience": job.min_experience,
            "weights": {"skill": job.weight_skill, "experience": job.weight_experience, "assessment": job.weight_test},
        } if job else None,
    }


@router.get("/{candidate_id}/resume")
def get_candidate_resume(candidate_id: int, download: bool = Query(False), user: Principal = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Serve the ORIGINAL uploaded resume. HR must have unlocked the candidate."""
    candidate = _candidate_or_404(candidate_id, db)
    app = newest_application(db, candidate_id)
    _authorized(user, candidate, app)
    if user.role == "hr" and not _is_unlocked(db, user, app):
        raise HTTPException(status_code=402, detail="Unlock this candidate to view their original resume")
    if user.role == "hr" and candidate.account_id:
        from ..services.settings_service import get_settings
        if get_settings(db, "candidate", candidate.account_id).resume_visibility == "private":
            raise HTTPException(status_code=403, detail="The candidate has chosen to keep their original resume private. "
                                                        "Screening scores and extracted skills are still shown.")
    resume = candidate.resume
    if not resume or not resume.file_path:
        raise HTTPException(status_code=404, detail="No resume uploaded for this candidate")
    if not os.path.isfile(resume.file_path):
        logger.warning("Resume file missing on disk for candidate %s: %s", candidate_id, resume.file_path)
        raise HTTPException(status_code=404, detail="Resume file is no longer available on the server")
    return files.file_response(resume.file_path, resume.file_name or os.path.basename(resume.file_path), download)


@router.get("/{candidate_id}/assessment")
def get_candidate_assessment(candidate_id: int, application_id: Optional[int] = Query(None),
                             user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Assessment the candidate actually took, with answer keys once completed.

    The candidate may read their own completed results; HR/admin may read it for
    jobs they can access. Hidden coding tests are never included.
    """
    candidate = _candidate_or_404(candidate_id, db)
    application = _application_for(candidate_id, application_id, db)
    _authorized(user, candidate, application)
    assessment = application.assessment
    state = assessment_state(assessment)
    fs = application.final_score
    base = {
        "candidate_id": candidate_id, "application_id": application.application_id, "status": state,
        "started_at": assessment.started_at if assessment else None,
        "completed_at": assessment.completed_at if assessment else None,
        "auto_submitted": bool(assessment.auto_submitted) if assessment else False,
        "time_limit_minutes": assessment.time_limit_minutes if assessment else None,
        "test_score": (fs.test_score if fs and fs.test_score is not None else
                       (assessment.score if assessment and state == "completed" else None)),
        "skills_covered": [], "questions": [],
    }
    if state == "not_started":
        return base
    try:
        stored = json.loads(assessment.questions)
    except (TypeError, ValueError):
        logger.exception("Invalid stored questions for application %s", application.application_id)
        stored = {}
    graded = {}
    if assessment.answers:
        try:
            graded = {g.get("index"): g for g in json.loads(assessment.answers) if isinstance(g, dict)}
        except (TypeError, ValueError):
            graded = {}
    done = state == "completed"
    questions = []
    for idx, q in enumerate(stored.get("questions", [])):
        g = graded.get(idx) or {}
        options = q.get("options") or None
        # Answer keys are only exposed once the assessment is completed.
        correct_label = q.get("correct_option_label") if done else None
        correct_text = None
        if options and correct_label:
            correct_text = next((o.get("text") for o in options if o.get("label") == correct_label), None)
        item = {
            "index": idx, "type": q.get("type"), "skill": q.get("skill"), "difficulty": q.get("difficulty"),
            "question": q.get("question"), "options": options, "correct_answer": correct_label,
            "correct_answer_text": correct_text,
            "reference_answer": q.get("reference_answer") if done else None,
            "candidate_answer": g.get("user_answer") if done else None,
            "correct": g.get("correct") if done else None,
            "score": g.get("score") if done else None,
            "feedback": g.get("feedback") if done else None,
        }
        if q.get("type") == "coding" and q.get("problem_id") and done:
            sub = (db.query(models.CodingSubmission)
                   .filter(models.CodingSubmission.assessment_id == assessment.assessment_id,
                           models.CodingSubmission.question_index == idx,
                           models.CodingSubmission.kind == "submit")
                   .order_by(models.CodingSubmission.submission_id.desc()).first())
            problem = db.get(models.CodingProblem, q["problem_id"])
            item["coding"] = {
                "problem_title": problem.title if problem else None,
                "statement": problem.statement if problem else None,
                "language": sub.language if sub else None, "source_code": sub.source_code if sub else None,
                "passed": sub.passed if sub else 0, "total": sub.total if sub else 0,
                "status": sub.status if sub else "not_submitted", "score": sub.score if sub else None,
                "exec_time_ms": sub.exec_time_ms if sub else None, "memory_kb": sub.memory_kb if sub else None,
                "error": sub.error if sub else None, "submitted_at": sub.submitted_at if sub else None,
            }
        questions.append(item)
    base["skills_covered"] = stored.get("skills_covered", [])
    base["questions"] = questions
    base["viewed_at"] = datetime.utcnow()
    return base
