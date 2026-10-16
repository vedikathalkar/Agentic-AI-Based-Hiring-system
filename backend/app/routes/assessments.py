"""
Assessment routes (thin; logic lives in services/assessment_service.py).

    POST /assessments/start/{application_id}     candidate clicks "Take Assessment" (idempotent)
    GET  /assessments/status/{application_id}    not_started | in_progress | completed (+ server timer)
    GET  /assessments/{application_id}           questions (no answer keys, no hidden tests)
    PUT  /assessments/progress/{application_id}  save draft answers
    POST /assessments/submit/{application_id}    grade, persist, final ranking
    POST /assessments/{application_id}/start     alias of /start/{id}
    POST /assessments/{application_id}/submit    alias of /submit/{id}
    POST /assessments/generate/{application_id}  backwards-compatible alias of /start

Only the candidate who owns the application may start/answer/submit.
"""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Application
from ..schemas_assessment_addendum import (AssessmentStatusOut, FinalScoreOut, GradedQuestionOut, ProctorEventsRequest,
                                           SaveProgressRequest, StartAssessmentRequest, SubmitAssessmentRequest,
                                           SubmitAssessmentResponse)
from ..scoring_service import assessment_state
from ..security import (Principal, assert_application_access, assert_candidate_application, current_user,
                        require_candidate)
from ..services import assessment_service as svc
from ..services import proctor_service as proctor
from ..services.email_service import dispatch_email

router = APIRouter(prefix="/assessments", tags=["assessments"])


def _app(db: Session, application_id: int) -> Application:
    return db.query(Application).filter(Application.application_id == application_id).first()


def _questions_response(db: Session, application_id: int, a) -> dict:
    qset = svc.question_set(a)
    return {
        "assessment_id": a.assessment_id, "application_id": application_id,
        "skills_covered": qset.skills_covered, "questions": svc.questions_for_candidate(db, a),
        "status": assessment_state(a), "started_at": a.started_at, "completed_at": a.completed_at,
        "expires_at": a.expires_at, "time_limit_minutes": a.time_limit_minutes,
        "remaining_seconds": svc.remaining_seconds(a), "server_time": datetime.utcnow(),
        "draft_answers": svc._draft(a),
    }


DEFAULT_NUM_QUESTIONS, DEFAULT_MCQ_RATIO = 8, 0.6


REQUIRED_CHECKS = ("rules", "camera", "microphone", "face")


def _start(application_id: int, num_questions: int, mcq_ratio: float, background: BackgroundTasks,
           user: Principal, db: Session, body: StartAssessmentRequest | None = None) -> dict:
    app = assert_candidate_application(user, _app(db, application_id))
    # Assessment size is decided by the server, never by the candidate's request.
    num_questions, mcq_ratio = DEFAULT_NUM_QUESTIONS, DEFAULT_MCQ_RATIO
    pro = body.proctoring if body else None
    if proctor.enabled() and assessment_state(app.assessment) == "not_started":
        missing = [c for c in REQUIRED_CHECKS if not (pro and pro.checks.get(c))]
        if not pro or not pro.consent or missing:
            raise HTTPException(status_code=400, detail="Complete the pre-exam check first: accept the rules and pass the "
                                                        "camera, microphone and face checks"
                                                        + (f" (missing: {', '.join(missing)})." if missing else "."))
    assessment, email_ids = svc.start(db, app, num_questions, mcq_ratio)
    if pro:
        proctor.on_start(db, assessment, pro.model_dump())
    for eid in email_ids:
        background.add_task(dispatch_email, eid)
    return _questions_response(db, application_id, assessment)


@router.post("/start/{application_id}")
def start_assessment(application_id: int, background: BackgroundTasks, body: StartAssessmentRequest | None = None,
                     num_questions: int = 8, mcq_ratio: float = 0.6,
                     user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return _start(application_id, num_questions, mcq_ratio, background, user, db, body)


@router.post("/{application_id}/start")
def start_assessment_alias(application_id: int, background: BackgroundTasks, body: StartAssessmentRequest | None = None,
                           num_questions: int = 8, mcq_ratio: float = 0.6, user: Principal = Depends(require_candidate),
                           db: Session = Depends(get_db)):
    return _start(application_id, num_questions, mcq_ratio, background, user, db, body)


@router.post("/generate/{application_id}")
def generate_assessment(application_id: int, background: BackgroundTasks, body: StartAssessmentRequest | None = None,
                        num_questions: int = 8, mcq_ratio: float = 0.6, user: Principal = Depends(require_candidate),
                        db: Session = Depends(get_db)):
    return _start(application_id, num_questions, mcq_ratio, background, user, db, body)


@router.get("/status/{application_id}", response_model=AssessmentStatusOut)
def assessment_status(application_id: int, background: BackgroundTasks, user: Principal = Depends(current_user),
                      db: Session = Depends(get_db)):
    application = assert_application_access(user, _app(db, application_id))
    result = svc.finalize_if_expired(db, application)   # enforce the server timer
    if result:
        for eid in result["email_ids"]:
            background.add_task(dispatch_email, eid)
        db.refresh(application)
    assessment = application.assessment
    fs = application.final_score
    num_questions = None
    if assessment and assessment.questions:
        try:
            num_questions = len(svc.question_set(assessment).questions)
        except Exception:
            num_questions = None
    return AssessmentStatusOut(
        application_id=application_id, candidate_id=application.candidate_id,
        status=assessment_state(assessment),
        assessment_id=assessment.assessment_id if assessment else None, num_questions=num_questions,
        started_at=assessment.started_at if assessment else None,
        completed_at=assessment.completed_at if assessment else None,
        expires_at=assessment.expires_at if assessment else None,
        remaining_seconds=svc.remaining_seconds(assessment),
        time_limit_minutes=(assessment.time_limit_minutes if assessment else None)
        or (application.job.assessment_minutes if application.job else None),
        auto_submitted=bool(assessment.auto_submitted) if assessment else False,
        coding_questions=(application.job.coding_questions or 0) if application.job else 0,
        test_score=fs.test_score if fs else None, final_score=fs.final_score if fs else None,
        skill_score=fs.skill_score if fs else None, experience_score=fs.experience_score if fs else None,
        screening_status=fs.screening_status if fs else None,
        job_title=application.job.title if application.job else None,
        **proctor.public_status(assessment),
    )


@router.get("/{application_id}")
def get_assessment(application_id: int, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    app = assert_candidate_application(user, _app(db, application_id))
    assessment = app.assessment
    if not assessment or not assessment.questions:
        raise HTTPException(status_code=404, detail="Assessment has not been started for this application")
    return _questions_response(db, application_id, assessment)


@router.put("/progress/{application_id}")
def save_progress(application_id: int, payload: SaveProgressRequest, user: Principal = Depends(require_candidate),
                  db: Session = Depends(get_db)):
    import json
    app = assert_candidate_application(user, _app(db, application_id))
    assessment = svc.ensure_open(db, app)
    assessment.draft_answers = json.dumps({str(k): str(v) for k, v in payload.answers.items()})
    db.commit()
    return {"application_id": application_id, "saved": len(payload.answers),
            "remaining_seconds": svc.remaining_seconds(assessment)}


def _submit(application_id: int, payload: SubmitAssessmentRequest, background: BackgroundTasks,
            user: Principal, db: Session) -> SubmitAssessmentResponse:
    app = assert_candidate_application(user, _app(db, application_id))
    result = svc.submit(db, app, {a.index: a.user_answer for a in payload.answers})
    for eid in result["email_ids"]:
        background.add_task(dispatch_email, eid)
    ranking = result["ranking"]
    return SubmitAssessmentResponse(
        application_id=application_id, test_score_percent=result["test_score"],
        results=[GradedQuestionOut(**r) for r in result["results"]],
        final_score=FinalScoreOut.model_validate(result["final_score_row"]),
        completed_at=result["assessment"].completed_at, auto_submitted=bool(result["assessment"].auto_submitted),
        ranking_status=ranking.get("status"), ranking_error=ranking.get("error"),
        screening_retry=result["screening_retry"],
    )


@router.post("/submit/{application_id}", response_model=SubmitAssessmentResponse)
def submit_assessment(application_id: int, payload: SubmitAssessmentRequest, background: BackgroundTasks,
                      user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return _submit(application_id, payload, background, user, db)


@router.post("/{application_id}/submit", response_model=SubmitAssessmentResponse)
def submit_assessment_alias(application_id: int, payload: SubmitAssessmentRequest, background: BackgroundTasks,
                            user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return _submit(application_id, payload, background, user, db)


# ---- proctoring -----------------------------------------------------------------------------

def _open_proctored(db: Session, app: Application):
    a = app.assessment
    if a is None or not a.questions:
        raise HTTPException(status_code=404, detail="Assessment has not been started for this application")
    return a


@router.post("/{application_id}/proctor/events")
def proctor_events(application_id: int, payload: ProctorEventsRequest, background: BackgroundTasks,
                   user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    """The browser reports what the invigilation agent saw. The server applies the strike rules and, on the
    last allowed strike, submits the answers saved so far."""
    import json
    app = assert_candidate_application(user, _app(db, application_id))
    a = _open_proctored(db, app)
    if assessment_state(a) == "completed":
        return {"strikes": a.strikes or 0, "max_strikes": proctor.max_strikes(), "terminated": a.integrity == "terminated",
                "integrity": a.integrity, "notices": [], "submitted": True}
    if payload.answers:        # keep the very latest answers before a strike can end the test
        a.draft_answers = json.dumps({str(k): str(v) for k, v in payload.answers.items()})
        db.commit()
    state = proctor.record(db, a, [e.model_dump() for e in payload.events])
    state["submitted"] = False
    if state["terminated"]:
        try:
            result = svc.submit(db, app, {int(k): v for k, v in svc._draft(a).items()}, auto=True)
            for eid in result["email_ids"]:
                background.add_task(dispatch_email, eid)
            state["submitted"] = True
        except HTTPException as exc:
            if exc.status_code == 409:
                state["submitted"] = True
            else:
                raise
    state["remaining_seconds"] = svc.remaining_seconds(a)
    return state


@router.get("/{application_id}/integrity")
def integrity_report(application_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """HR/admin: the proctoring timeline for an attempt (with evidence snapshots). A candidate sees their own
    summary without snapshots."""
    application = assert_application_access(user, _app(db, application_id))
    a = application.assessment
    if a is None:
        raise HTTPException(status_code=404, detail="No assessment for this application")
    return proctor.report(db, a, with_snapshots=user.role in ("hr", "admin"))
