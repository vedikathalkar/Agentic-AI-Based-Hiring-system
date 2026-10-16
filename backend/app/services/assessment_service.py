"""Assessment lifecycle: start (explicit), server-side timer, coding questions,
grading, submission (manual or automatic on expiry) and follow-up events.

The timer is authoritative on the server: ``expires_at = started_at + limit``.
The client only displays ``remaining_seconds`` returned by the API.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..agents import assessment_llm
from ..agents.assessment_llm import GeneratedQuestion, GeneratedQuestionSet, QuestionType
from ..agents.skill_agent import normalize_skill, parse_requirements
from ..scoring_service import (assessment_state, get_or_create_final_score, run_and_store_final_ranking,
                               run_and_store_screening)
from . import code_runner, config, credits_service, hiring_context as ctx, referral_service
from .email_service import EmailService
from .notification_service import notify

logger = logging.getLogger(__name__)

PRE_ASSESSMENT_STATUSES = (None, "submitted", "parsed", "in_review")
DEFAULT_MINUTES = 30


# ---- helpers -------------------------------------------------------------------

def question_set(assessment: models.Assessment) -> GeneratedQuestionSet:
    return GeneratedQuestionSet.model_validate_json(assessment.questions)


def qtype(q: GeneratedQuestion) -> str:
    return q.type.value if isinstance(q.type, QuestionType) else str(q.type)


def remaining_seconds(assessment: Optional[models.Assessment], now: Optional[datetime] = None) -> Optional[int]:
    if assessment is None or assessment.expires_at is None or assessment.completed_at is not None:
        return None
    now = now or datetime.utcnow()
    return max(0, int((assessment.expires_at - now).total_seconds()))


def is_expired(assessment: Optional[models.Assessment], now: Optional[datetime] = None) -> bool:
    if assessment is None or assessment.expires_at is None or assessment.completed_at is not None:
        return False
    return (now or datetime.utcnow()) >= assessment.expires_at


def _draft(assessment: models.Assessment) -> dict:
    try:
        data = json.loads(assessment.draft_answers or "{}")
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _loads(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def pick_coding_problems(db: Session, job: models.JobRole, count: int) -> list[models.CodingProblem]:
    if count <= 0:
        return []
    problems = (db.query(models.CodingProblem)
                .filter(models.CodingProblem.active.is_(True),
                        (models.CodingProblem.hr_account_id.is_(None)) |
                        (models.CodingProblem.hr_account_id == job.hr_account_id)).all())
    reqs = {normalize_skill(r) for r in parse_requirements(job.requirements or "")}
    order = {"easy": 0, "medium": 1, "hard": 2}

    def rank(p):
        tags = {normalize_skill(t) for t in (p.tags or "").split(",") if t.strip()}
        own = 0 if p.hr_account_id == job.hr_account_id and p.hr_account_id else 1
        return (own, -len(tags & reqs), order.get(p.difficulty, 1), p.problem_id)
    return sorted(problems, key=rank)[:count]


# ---- start ---------------------------------------------------------------------

def _generate_for_candidate(db: Session, app: models.Application, job: models.JobRole,
                            num_questions: int, mcq_ratio: float) -> GeneratedQuestionSet:
    """Legacy path (no published template): generate questions for this candidate."""
    # Assessments are an AI feature billed to the employer who owns the job.
    if job.hr_account_id:
        try:
            credits_service.spend(db, "hr", job.hr_account_id, "ai_assessment",
                                  f"AI assessment — {app.candidate.name} ({job.title})",
                                  reference=f"assessment:{app.application_id}", commit=False)
        except HTTPException as exc:
            if exc.status_code != 402:
                raise
            notify(db, "hr", job.hr_account_id, "credits_low", "Out of credits",
                   f"{app.candidate.name} couldn't start the {job.title} assessment because your credits ran out.",
                   "/hr/credits/buy")
            raise HTTPException(status_code=402, detail="The employer can't run assessments right now. "
                                                        "They have been notified — please try again later.")
    try:
        generated = assessment_llm.generate_questions(
            job_title=job.title, job_description=job.description or "", job_requirements=job.requirements or "",
            num_questions=num_questions, mcq_ratio=mcq_ratio)
    except Exception:
        db.rollback()
        logger.exception("Question generation failed for application %s", app.application_id)
        raise HTTPException(status_code=502, detail="The assessment could not be generated right now. "
                                                    "Please try again in a few minutes.")

    questions = [q for q in generated.questions if qtype(q) in ("mcq", "short_answer")]
    for p in pick_coding_problems(db, job, int(job.coding_questions or 0)):
        questions.append(GeneratedQuestion(type=QuestionType.CODING, skill=(p.tags or "programming").split(",")[0].strip(),
                                           difficulty=p.difficulty or "medium", question=p.title, problem_id=p.problem_id))
    return GeneratedQuestionSet(skills_covered=generated.skills_covered, questions=questions)



def start(db: Session, app: models.Application, num_questions: int = 8, mcq_ratio: float = 0.6) -> tuple[models.Assessment, list[int]]:
    """Explicit start (candidate clicked "Take Assessment"). Idempotent."""
    if app.candidate is None:
        raise HTTPException(status_code=400, detail="Application has no candidate")
    job = app.job
    if job is None:
        raise HTTPException(status_code=400, detail="Application has no associated job role")
    if app.status == "rejected":
        raise HTTPException(status_code=409, detail="This application is closed")
    existing = app.assessment
    state = assessment_state(existing)
    if state == "completed":
        raise HTTPException(status_code=409, detail="Assessment already completed for this application.")
    if state == "in_progress":
        return existing, []

    # A template the HR reviewed and published for this job takes precedence: every
    # candidate gets the same questions (already paid for when HR generated it).
    template = (db.query(models.AssessmentTemplate)
                .filter(models.AssessmentTemplate.job_id == job.job_id, models.AssessmentTemplate.status == "published")
                .order_by(models.AssessmentTemplate.published_at.desc().nullslast()).first())
    if template is not None:
        qset = GeneratedQuestionSet.model_validate_json(template.questions)
    else:
        qset = _generate_for_candidate(db, app, job, num_questions, mcq_ratio)

    now = datetime.utcnow()
    minutes = int((template.time_limit_minutes if template else None) or job.assessment_minutes or DEFAULT_MINUTES)
    assessment = existing or models.Assessment(application_id=app.application_id)
    if existing is None:
        db.add(assessment)
    assessment.questions = qset.model_dump_json()
    assessment.answers = None
    assessment.draft_answers = None
    assessment.score = None
    assessment.completed_at = None
    assessment.auto_submitted = False
    assessment.template_id = template.template_id if template else None
    assessment.started_at = now
    assessment.time_limit_minutes = minutes
    assessment.expires_at = now + timedelta(minutes=minutes)
    db.commit()
    db.refresh(assessment)
    return assessment, _started_events(db, app, assessment)


def _started_events(db: Session, app: models.Application, a: models.Assessment) -> list[int]:
    """send_assessment_invitation: candidate + HR notifications/emails on explicit start."""
    job, cand = app.job, app.candidate
    hr = ctx.hr_for_job(db, job)
    account = ctx.candidate_account_for(db, cand)
    n = len(question_set(a).questions)
    common = {"candidate_name": cand.name, "candidate_email": cand.email, "job_title": job.title,
              "company_name": ctx.company_name(db, hr), "questions": f"{n} questions",
              "time_limit": f"{a.time_limit_minutes} minutes",
              "started_at": a.started_at.strftime("%d %b %Y, %H:%M UTC"),
              "deadline": a.expires_at.strftime("%d %b %Y, %H:%M UTC")}
    ids = []
    if account:
        notify(db, "candidate", account.account_id, "assessment_started", "Assessment started",
               f"{job.title}: submit by {common['deadline']}", f"/assessment?application={app.application_id}")
    log = EmailService.queue(db, to=cand.email, subject=f"Assessment started — {job.title}", template="assessment_started",
                             context={**common, "audience": "candidate",
                                      "link": ctx.link(f"/assessment?application={app.application_id}")},
                             related_type="assessment", related_id=a.assessment_id,
                             recipient_role="candidate", recipient_id=account.account_id if account else None,
                             owner_role="hr", owner_id=hr.account_id if hr else None)
    if log:
        ids.append(log.email_id)
    if hr:
        notify(db, "hr", hr.account_id, "assessment_started", "Assessment started",
               f"{cand.name} started the {job.title} assessment", f"/hr/candidate/{cand.candidate_id}")
        log = EmailService.queue(db, to=hr.email, subject=f"{cand.name} started the {job.title} assessment",
                                 template="assessment_started",
                                 context={**common, "audience": "hr", "hr_name": hr.name,
                                          "link": ctx.link(f"/hr/candidate/{cand.candidate_id}")},
                                 related_type="assessment", related_id=a.assessment_id,
                                 recipient_role="hr", recipient_id=hr.account_id, owner_role="hr", owner_id=hr.account_id)
        if log:
            ids.append(log.email_id)
    return ids


# ---- read ----------------------------------------------------------------------

def _latest_submission(db: Session, a: models.Assessment, index: int, kind: Optional[str] = None):
    q = (db.query(models.CodingSubmission)
         .filter(models.CodingSubmission.assessment_id == a.assessment_id,
                 models.CodingSubmission.question_index == index))
    if kind:
        q = q.filter(models.CodingSubmission.kind == kind)
    return q.order_by(models.CodingSubmission.submission_id.desc()).first()


def coding_payload(db: Session, a: models.Assessment, index: int, problem_id: int) -> dict:
    p = db.get(models.CodingProblem, problem_id)
    if p is None:
        return {"problem_id": problem_id, "missing": True}
    last_submit = _latest_submission(db, a, index, "submit")
    last_any = _latest_submission(db, a, index)
    return {
        "problem_id": p.problem_id, "title": p.title, "statement": p.statement, "input_format": p.input_format,
        "output_format": p.output_format, "constraints": p.constraints, "examples": _loads(p.examples, []),
        "sample_tests": _loads(p.visible_tests, []),     # visible tests only; hidden tests never leave the server
        "hidden_test_count": len(_loads(p.hidden_tests, [])),
        "time_limit_ms": p.time_limit_ms, "memory_limit_mb": p.memory_limit_mb,
        "languages": code_runner.available_languages(),
        "last_source": last_any.source_code if last_any else None,
        "last_language": last_any.language if last_any else None,
        "last_submission": _submission_summary(last_submit) if last_submit else None,
    }


def _submission_summary(s: models.CodingSubmission) -> dict:
    return {"submission_id": s.submission_id, "status": s.status, "passed": s.passed, "total": s.total,
            "score": s.score, "language": s.language, "exec_time_ms": s.exec_time_ms, "memory_kb": s.memory_kb,
            "error": s.error, "submitted_at": s.submitted_at}


def questions_for_candidate(db: Session, a: models.Assessment) -> list[dict]:
    out = []
    for idx, q in enumerate(question_set(a).questions):
        item = {"index": idx, "type": qtype(q), "skill": q.skill, "difficulty": q.difficulty, "question": q.question,
                "options": [{"label": o.label, "text": o.text} for o in q.options] if q.options else None}
        if qtype(q) == "coding" and q.problem_id:
            item["coding"] = coding_payload(db, a, idx, q.problem_id)
        out.append(item)
    return out


# ---- coding --------------------------------------------------------------------

def _coding_question(a: models.Assessment, index: int) -> GeneratedQuestion:
    qs = question_set(a).questions
    if index < 0 or index >= len(qs) or qtype(qs[index]) != "coding" or not qs[index].problem_id:
        raise HTTPException(status_code=404, detail="Coding question not found")
    return qs[index]


def ensure_open(db: Session, app: models.Application) -> models.Assessment:
    a = app.assessment
    state = assessment_state(a)
    if state == "not_started":
        raise HTTPException(status_code=404, detail="Assessment has not been started")
    if state == "completed":
        raise HTTPException(status_code=409, detail="Assessment already submitted")
    if is_expired(a):
        if datetime.utcnow() > a.expires_at + timedelta(seconds=config.ASSESSMENT_GRACE_SECONDS):
            finalize_if_expired(db, app)
        raise HTTPException(status_code=409, detail="Time is up — your saved answers are being submitted")
    return a


def parse_code_draft(raw) -> Optional[dict]:
    """The candidate page autosaves an unsubmitted coding answer as JSON {"language", "source"} in the drafts."""
    if not raw or not isinstance(raw, str) or not raw.lstrip().startswith("{"):
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(d, dict) or not str(d.get("source") or "").strip() or not d.get("language"):
        return None
    source = str(d["source"])[:100_000]
    if source.strip() == (code_runner.STARTER_CODE.get(str(d["language"])) or "").strip():
        return None   # untouched starter template: nothing to grade
    return {"language": str(d["language"]), "source": source}


def run_code(db: Session, app: models.Application, index: int, language: str, source: str, kind: str) -> dict:
    a = ensure_open(db, app)
    return _execute_code(db, a, index, language, source, kind)


def _execute_code(db: Session, a: models.Assessment, index: int, language: str, source: str, kind: str) -> dict:
    q = _coding_question(a, index)
    problem = db.get(models.CodingProblem, q.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Coding problem not found")
    if not code_runner.is_available(language):
        raise HTTPException(status_code=422, detail=f"{language} is not available on this server")
    visible = _loads(problem.visible_tests, [])
    hidden = _loads(problem.hidden_tests, []) if kind == "submit" else []
    report = code_runner.execute(language, source, visible + hidden, problem.time_limit_ms or 2000,
                                 problem.memory_limit_mb or 256)
    sub = models.CodingSubmission(assessment_id=a.assessment_id, question_index=index, problem_id=problem.problem_id,
                                  language=language, source_code=source, kind=kind, status=report.status,
                                  passed=report.passed, total=report.total,
                                  score=report.score if kind == "submit" else None,
                                  exec_time_ms=report.time_ms, memory_kb=report.memory_kb, error=report.error)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    n_vis = len(visible)
    tests = []
    for i, t in enumerate(report.tests):
        if i < n_vis:
            tests.append({"name": f"Sample {i + 1}", "hidden": False, "passed": t.passed, "status": t.status,
                          "input": t.input, "expected": t.expected, "actual": t.actual, "stderr": t.stderr,
                          "time_ms": t.time_ms})
        else:  # hidden: result only
            tests.append({"name": f"Hidden test {i - n_vis + 1}", "hidden": True, "passed": t.passed,
                          "status": t.status, "time_ms": t.time_ms})
    return {**_submission_summary(sub), "kind": kind, "tests": tests,
            "hidden_passed": sum(1 for t in tests if t["hidden"] and t["passed"]),
            "hidden_total": sum(1 for t in tests if t["hidden"])}


# ---- submit --------------------------------------------------------------------

def submit(db: Session, app: models.Application, answers: dict[int, str], auto: bool = False) -> dict:
    a = app.assessment
    if a is not None:
        # Lock the row: a manual submit and the scheduler's auto-submit must not both grade it.
        a = (db.query(models.Assessment).filter(models.Assessment.assessment_id == a.assessment_id)
             .with_for_update().populate_existing().one())
    state = assessment_state(a)
    if state == "not_started":
        raise HTTPException(status_code=404, detail="Assessment has not been started for this application")
    if state == "completed":
        raise HTTPException(status_code=409, detail="Assessment already submitted")
    now = datetime.utcnow()
    late = a.expires_at is not None and now > a.expires_at + timedelta(seconds=config.ASSESSMENT_GRACE_SECONDS)
    if late and not auto:
        # Past the deadline: only the answers saved before time ran out count.
        answers, auto = {int(k): v for k, v in _draft(a).items()}, True
    else:
        a.draft_answers = json.dumps({str(k): v for k, v in answers.items()})
        db.commit()

    qs = question_set(a).questions
    results = []
    total = 0.0
    for idx, q in enumerate(qs):
        t = qtype(q)
        user_answer = answers.get(idx, "") or ""
        if t == "mcq":
            correct = user_answer.strip().upper() == (q.correct_option_label or "").strip().upper()
            score = 1.0 if correct else 0.0
            feedback = "Correct." if correct else f"Incorrect. The correct answer was {q.correct_option_label}."
        elif t == "coding":
            sub = _latest_submission(db, a, idx, "submit")
            draft = parse_code_draft(user_answer)
            if draft and (sub is None or sub.source_code != draft["source"] or sub.language != draft["language"]):
                # Code written (or edited) after the last "Submit Code" still counts: grade the latest draft.
                try:
                    _execute_code(db, a, idx, draft["language"], draft["source"], "submit")
                    sub = _latest_submission(db, a, idx, "submit")
                except HTTPException:
                    logger.warning("Could not grade the code draft for question %s of application %s", idx, app.application_id)
            if sub is None:
                correct, score, feedback, user_answer = False, 0.0, "No code was submitted.", ""
            else:
                score = (sub.score or 0.0) / 100
                correct = sub.passed == sub.total and sub.total > 0
                feedback = f"{sub.passed} / {sub.total} test cases passed ({sub.language})."
                user_answer = f"[{sub.language}] submission #{sub.submission_id}"
        elif not user_answer.strip():
            correct, score, feedback = False, 0.0, "No answer provided."
        else:
            try:
                grade = assessment_llm.grade_short_answer(question=q.question, reference_answer=q.reference_answer or "",
                                                          user_answer=user_answer)
                correct, score, feedback = grade.is_correct, grade.score, grade.feedback
            except Exception as exc:
                logger.exception("Grading failed on question %s for application %s", idx, app.application_id)
                raise HTTPException(status_code=502, detail=f"Grading failed on question {idx + 1}; your answers were saved, please try submitting again. ({exc})")
        total += score
        results.append({"index": idx, "question": q.question, "type": t, "user_answer": user_answer,
                        "correct": correct, "score": round(score, 4), "feedback": feedback})

    test_score = round(total / (len(qs) or 1) * 100, 1)
    a.answers = json.dumps(results)
    a.score = test_score
    a.completed_at = now
    a.auto_submitted = bool(auto)
    fs = get_or_create_final_score(db, app)
    fs.test_score = test_score
    fs.final_score = None
    if app.status in PRE_ASSESSMENT_STATUSES:
        app.status = "assessed"
    db.commit()   # the completed assessment is durable before anything optional runs

    screening_retry = None
    if fs.skill_score is None or fs.experience_score is None:
        resume = app.candidate.resume if app.candidate else None
        screening_retry = (run_and_store_screening(db, app, resume) if resume
                           else {"status": "failed", "error": "No resume on file"})
        db.refresh(fs)
    ranking = run_and_store_final_ranking(db, app, fs)
    db.refresh(fs)
    db.refresh(a)
    email_ids = _completed_events(db, app, a, fs)
    account = ctx.candidate_account_for(db, app.candidate)
    if account:
        referral_service.qualify(db, account.account_id)
    return {"results": results, "test_score": test_score, "final_score_row": fs, "assessment": a,
            "ranking": ranking, "screening_retry": screening_retry, "email_ids": email_ids}


def _completed_events(db: Session, app: models.Application, a: models.Assessment, fs: models.FinalScore) -> list[int]:
    from ..utils_format import pct
    job, cand = app.job, app.candidate
    hr = ctx.hr_for_job(db, job)
    account = ctx.candidate_account_for(db, cand)
    common = {"candidate_name": cand.name, "job_title": job.title, "test_score": pct(fs.test_score),
              "final_score": pct(fs.final_score), "auto_submitted": a.auto_submitted,
              "completed_at": a.completed_at.strftime("%d %b %Y, %H:%M UTC")}
    ids = []
    if account:
        notify(db, "candidate", account.account_id, "assessment_completed", "Assessment submitted",
               f"{job.title}: test score {pct(fs.test_score)}", "/applications")
        log = EmailService.queue(db, to=cand.email, subject=f"Assessment submitted — {job.title}",
                                 template="assessment_completed",
                                 context={**common, "audience": "candidate", "link": ctx.link("/applications")},
                                 related_type="assessment", related_id=a.assessment_id,
                                 recipient_role="candidate", recipient_id=account.account_id,
                                 owner_role="hr", owner_id=hr.account_id if hr else None)
        if log:
            ids.append(log.email_id)
    if hr:
        notify(db, "hr", hr.account_id, "assessment_completed", "Assessment completed",
               f"{cand.name} scored {pct(fs.test_score)} on {job.title}", f"/hr/candidate/{cand.candidate_id}")
        log = EmailService.queue(db, to=hr.email, subject=f"{cand.name} completed the {job.title} assessment",
                                 template="assessment_completed",
                                 context={**common, "audience": "hr", "hr_name": hr.name,
                                          "link": ctx.link(f"/hr/candidate/{cand.candidate_id}")},
                                 related_type="assessment", related_id=a.assessment_id,
                                 recipient_role="hr", recipient_id=hr.account_id, owner_role="hr", owner_id=hr.account_id)
        if log:
            ids.append(log.email_id)
    return ids


def finalize_if_expired(db: Session, app: models.Application) -> Optional[dict]:
    a = app.assessment
    if not is_expired(a) or datetime.utcnow() <= a.expires_at + timedelta(seconds=config.ASSESSMENT_GRACE_SECONDS):
        return None
    try:
        return submit(db, app, {int(k): v for k, v in _draft(a).items()}, auto=True)
    except HTTPException as exc:
        if exc.status_code == 409:
            return None
        logger.warning("Auto-submit for application %s failed: %s", app.application_id, exc.detail)
        return None


def finalize_expired_assessments(db: Session, dispatch: bool = True) -> int:
    from .email_service import dispatch_email
    grace = timedelta(seconds=config.ASSESSMENT_GRACE_SECONDS)
    rows = (db.query(models.Assessment)
            .filter(models.Assessment.completed_at.is_(None), models.Assessment.expires_at.isnot(None),
                    models.Assessment.expires_at < datetime.utcnow() - grace).all())
    done = 0
    for a in rows:
        try:
            app = db.get(models.Application, a.application_id)
            result = finalize_if_expired(db, app) if app else None
        except Exception:  # noqa: BLE001 - one bad row must not block the others
            db.rollback()
            logger.exception("Auto-submit failed for assessment %s", a.assessment_id)
            continue
        if result:
            done += 1
            if dispatch:
                for eid in result["email_ids"]:
                    dispatch_email(eid)
    return done
