"""
The candidate-facing hiring pipeline.

    Applied -> Skill evaluation -> Experience evaluation -> Assessment -> Interview -> Offer letter

`build_pipeline()` is a pure function over a plain dict of facts so it can be unit-tested without a
database; `pipeline_for_application()` gathers those facts from an Application row.

Each stage has one of these states:
    done      finished successfully
    active    where the application is right now
    pending   not reached yet
    stopped   the process ended here (a rejection, or the candidate declined the offer)
    skipped   would have come after the stage where the process stopped
    issue     needs attention (for example screening could not run)
"""

from __future__ import annotations

from typing import Any, Optional

STAGES = [
    ("applied", "Applied"),
    ("skill", "Skill evaluation"),
    ("experience", "Experience evaluation"),
    ("assessment", "Assessment"),
    ("interview", "Interview"),
    ("offer", "Offer letter"),
]
KEYS = [k for k, _ in STAGES]
LABEL = dict(STAGES)

INTERVIEW_DONE = ("interviewed", "selected", "offered", "hired", "offer_declined")
STOP_DETAIL = {
    "applied": "The process ended before screening.",
    "skill": "The process ended after the skill evaluation.",
    "experience": "The process ended after the experience evaluation.",
    "assessment": "Not taken forward to an interview after the assessment.",
    "interview": "Not taken forward to an offer after the interview.",
    "offer": "The offer was declined.",
}


def infer_stop_stage(f: dict[str, Any]) -> str:
    """The furthest stage an application reached; used when a rejection did not record one."""
    if f.get("has_interview") or f.get("status") in ("interviewed", "scheduled"):
        return "interview"
    if f.get("assessment_state") in ("completed", "in_progress"):
        return "assessment"
    if f.get("experience_score") is not None:
        return "experience"
    if f.get("skill_score") is not None:
        return "skill"
    return "applied"


def build_pipeline(f: dict[str, Any]) -> dict[str, Any]:
    status = f.get("status") or "submitted"
    a_state = f.get("assessment_state") or "not_started"
    skill, exp = f.get("skill_score"), f.get("experience_score")
    failed = f.get("screening_status") == "failed"
    has_resume = f.get("has_resume", True)
    offer = f.get("offer_status")           # latest non-draft offer: sent | viewed | accepted | rejected | expired | withdrawn

    state = {k: "pending" for k in KEYS}
    detail = {k: "" for k in KEYS}
    state["applied"], detail["applied"] = "done", "Application received"

    stopped_at: Optional[str] = None
    by_candidate = False

    if status == "rejected":
        stopped_at = f.get("decision_stage") if f.get("decision_stage") in KEYS else infer_stop_stage(f)
    elif status == "offer_declined" or offer == "rejected":
        stopped_at, by_candidate = "offer", True

    # ---- what has genuinely happened ----
    if skill is not None:
        state["skill"], detail["skill"] = "done", f"Skill match {round(skill)}%"
    if exp is not None:
        state["experience"], detail["experience"] = "done", f"Experience match {round(exp)}%"
    if a_state == "completed":
        state["assessment"], detail["assessment"] = "done", (
            f"Scored {round(f['test_score'])}%" if f.get("test_score") is not None else "Completed")
    if status in INTERVIEW_DONE or f.get("interview_status") == "completed":
        state["interview"], detail["interview"] = "done", "Interview completed"
    if status == "hired" or offer == "accepted":
        state["offer"], detail["offer"] = "done", "Offer accepted"

    if not stopped_at:
        # ---- where it is now ----
        if state["skill"] != "done":
            if failed:
                state["skill"], detail["skill"] = "issue", "Resume screening could not be completed"
            elif not has_resume:
                state["skill"], detail["skill"] = "issue", "Attach your resume to be evaluated"
            else:
                state["skill"], detail["skill"] = "active", "Being evaluated against the role's skills"
        if state["experience"] != "done":
            if failed or not has_resume:
                state["experience"], detail["experience"] = "issue", "Could not be evaluated yet"
            else:
                state["experience"], detail["experience"] = "active", "Being evaluated against the role's experience"
        if state["assessment"] != "done":
            if a_state == "in_progress":
                state["assessment"], detail["assessment"] = "active", "In progress"
            elif has_resume:
                state["assessment"], detail["assessment"] = "active", "Ready — take the assessment"
            else:
                detail["assessment"] = "Needs a resume first"
        if state["interview"] != "done":
            if status == "scheduled":
                state["interview"], detail["interview"] = "active", "Interview scheduled"
            elif status == "shortlisted":
                state["interview"], detail["interview"] = "active", "Shortlisted — waiting for an interview slot"
            elif a_state == "completed":
                detail["interview"] = "HR is reviewing your results"
        if state["offer"] != "done":
            if status == "offered" or offer in ("sent", "viewed"):
                state["offer"], detail["offer"] = "active", "Offer sent — your response is awaited"
            elif status == "selected":
                state["offer"], detail["offer"] = "active", "Selected — offer letter being prepared"
    else:
        # ---- the process stopped: before = done, stop stage = stopped, after = skipped ----
        idx = KEYS.index(stopped_at)
        for i, k in enumerate(KEYS):
            if i < idx:
                if state[k] != "done":
                    state[k] = "done"
                    detail[k] = detail[k] or "Completed"
            elif i == idx:
                state[k], detail[k] = "stopped", STOP_DETAIL[k]
            else:
                state[k], detail[k] = "skipped", ""
        if by_candidate:
            detail["offer"] = "You declined the offer"

    # ---- headline ----
    live = [k for k in KEYS if state[k] in ("active", "issue")]
    current = live[-1] if live else (stopped_at if stopped_at else None)
    if stopped_at:
        out_state = "stopped"
        headline = "You declined the offer." if by_candidate else f"Process stopped at {LABEL[stopped_at].lower()}."
    elif state["offer"] == "done":
        out_state, headline = "completed", "Offer accepted — welcome aboard."
    else:
        out_state = "in_progress"
        cur = current or next((k for k in KEYS if state[k] == "pending"), "offer")
        headline = LABEL[cur] + (f": {detail[cur]}" if detail[cur] else "")
        current = cur
    return {
        "stages": [{"key": k, "label": LABEL[k], "state": state[k], "detail": detail[k]} for k in KEYS],
        "outcome": {"state": out_state, "headline": headline, "current": current,
                    "stopped_at": stopped_at if out_state == "stopped" else None,
                    "stopped_label": LABEL[stopped_at] if out_state == "stopped" and stopped_at else None,
                    "by_candidate": by_candidate},
    }


def stage_index(key: str) -> int:
    return KEYS.index(key) if key in KEYS else 0


def facts_for_application(db, app) -> dict[str, Any]:
    """Collect the facts build_pipeline() needs from an Application row."""
    from .. import models
    from ..scoring_service import assessment_state

    fs = app.final_score
    resume = app.candidate.resume if app.candidate else None
    offer_status = None
    if db is not None:
        offer = (db.query(models.OfferLetter).filter(models.OfferLetter.application_id == app.application_id,
                                                     models.OfferLetter.status != "draft")
                 .order_by(models.OfferLetter.offer_id.desc()).first())
        offer_status = offer.status if offer else None
    iv = app.interview
    return {
        "status": app.status, "decision_stage": app.decision_stage,
        "skill_score": fs.skill_score if fs else None, "experience_score": fs.experience_score if fs else None,
        "test_score": fs.test_score if fs else None,
        "screening_status": fs.screening_status if fs else None,
        "assessment_state": assessment_state(app.assessment),
        "has_resume": resume is not None,
        "has_interview": iv is not None, "interview_status": iv.status if iv else None,
        "offer_status": offer_status,
    }


def pipeline_for_application(db, app) -> dict[str, Any]:
    return build_pipeline(facts_for_application(db, app))
