"""Shared glue between routes, the LangGraph pipeline and the database.

Routes call these helpers so that resume upload, the inline screening retry
on assessment submission, and final ranking all read the *same* inputs:

* job requirements always come from ``application.job`` (the job the
  candidate actually applied to), never from another job or the client;
* candidate skills always come from the stored ``Resume`` row.

Scores are stored exactly as the agents return them (floats 0-100). ``None``
means "not calculated"; a real 0 is stored as 0.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from . import models
from .agents import recruitment_graph as graph

logger = logging.getLogger(__name__)


def job_data_for(job: models.JobRole) -> Dict[str, Any]:
    return {
        "title": job.title,
        "description": job.description or "",
        "requirements": job.requirements or "",
        "min_experience": job.min_experience or 0,
        "weight_skill": job.weight_skill,
        "weight_experience": job.weight_experience,
        "weight_test": job.weight_test,
    }


def _derive_years(resume: models.Resume, entries: list) -> Optional[float]:
    if resume.experience_years is not None:
        return resume.experience_years
    months = [e.get("duration_months") for e in entries if isinstance(e, dict)]
    months = [m for m in months if isinstance(m, (int, float))]
    return round(sum(months) / 12, 2) if months else None


def parsed_resume_from_row(resume: models.Resume) -> Dict[str, Any]:
    """Rebuild the parser-shaped dict from the stored Resume row.

    ``experience_years`` stays None when it cannot be derived; the Experience
    Agent then derives it from entries itself instead of us inventing 0.
    """
    try:
        entries = json.loads(resume.experience_entries or "[]")
    except (TypeError, ValueError):
        entries = []
    return {
        "skills": resume.skills or "",
        "experience": resume.experience or "",
        "education": resume.education or "",  # informational only; never scored
        "experience_years": _derive_years(resume, entries),
        "experience_entries": entries,
    }


def newest_application(db: Session, candidate_id: int) -> Optional[models.Application]:
    return (
        db.query(models.Application)
        .filter(models.Application.candidate_id == candidate_id)
        .order_by(models.Application.applied_at.desc().nullslast(), models.Application.application_id.desc())
        .first()
    )


def get_or_create_final_score(db: Session, application: models.Application) -> models.FinalScore:
    row = (
        db.query(models.FinalScore)
        .filter(models.FinalScore.application_id == application.application_id)
        .first()
    )
    if row is None:
        row = models.FinalScore(application_id=application.application_id)
        db.add(row)
        db.flush()
    return row


def _join(values) -> Optional[str]:
    values = [str(v).strip() for v in (values or []) if str(v).strip()]
    return ", ".join(values) if values else None


def run_and_store_screening(db: Session, application: models.Application, resume: models.Resume) -> Dict[str, Any]:
    """Run skill/experience/bias screening for one application and persist it.

    Never raises: on failure the error is logged, stored on the FinalScore row
    and returned as ``{"status": "failed", "error": ...}``.
    """
    job = application.job
    parsed = parsed_resume_from_row(resume)
    try:
        if job is None:
            raise ValueError(f"Application {application.application_id} has no job")
        output = graph.run_screening_graph(
            job_id=job.job_id,
            candidate_id=application.candidate_id,
            application_id=application.application_id,
            job_data=job_data_for(job),
            parsed_resume=parsed,
        )
        final = output["final_result"]
        ranking = final.get("ranking_result") or {}
        skill_result = final.get("skill_result") or {}
        experience_result = final.get("experience_result") or {}

        skill_score = skill_result.get("score", ranking.get("skill_score"))
        experience_score = experience_result.get("experience_score", ranking.get("experience_score"))
        if skill_score is None or experience_score is None:
            raise ValueError("Screening graph did not return skill and experience scores")

        fs = get_or_create_final_score(db, application)
        fs.skill_score = float(skill_score)
        fs.experience_score = float(experience_score)
        fs.skill_matched = _join(skill_result.get("matched"))
        fs.skill_missing = _join(skill_result.get("missing"))
        fs.screening_status = "completed"
        fs.screening_error = None
        if fs.test_score is None:
            fs.final_score = None
            fs.recommendation = ranking.get("recommendation")
            fs.explanation = ranking.get("ranking_explanation")
        if application.status in (None, "submitted", "parsed"):
            application.status = "in_review"
        db.commit()
        return {
            "status": "completed",
            "skill_score": fs.skill_score,
            "experience_score": fs.experience_score,
            "matched_skills": skill_result.get("matched", []),
            "missing_skills": skill_result.get("missing", []),
            "job_requirements": job.requirements or "",
            "skill_result": skill_result,
            "experience_result": experience_result,
            "bias_result": final.get("bias_result"),
            "ranking_result": ranking,
        }
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        logger.exception(
            "Resume screening failed for candidate %s / application %s",
            application.candidate_id, application.application_id,
        )
        db.rollback()
        error = f"{type(exc).__name__}: {exc}"
        fs = get_or_create_final_score(db, application)
        # The resume changed, so any previous screening values are stale.
        fs.skill_score = None
        fs.experience_score = None
        fs.skill_matched = None
        fs.skill_missing = None
        fs.screening_status = "failed"
        fs.screening_error = error[:1000]
        if fs.test_score is None:
            fs.final_score = None
        db.commit()
        return {"status": "failed", "error": error}


def run_and_store_final_ranking(db: Session, application: models.Application, fs: models.FinalScore) -> Dict[str, Any]:
    """Blend stored skill/experience/test scores with the Ranking Agent.

    Stored experience is reused (the node skips recomputation). On failure the
    completed test score is kept and final_score stays None.
    """
    if fs.test_score is None:
        return {"status": "skipped", "error": "Assessment not completed"}
    if fs.skill_score is None or fs.experience_score is None:
        fs.final_score = None
        fs.recommendation = None
        fs.explanation = "Final ranking unavailable: resume screening scores were not computed."
        db.commit()
        return {"status": "failed", "error": fs.explanation}

    job = application.job
    resume = application.candidate.resume if application.candidate else None
    try:
        output = graph.run_final_ranking_graph(
            job_id=job.job_id,
            candidate_id=application.candidate_id,
            application_id=application.application_id,
            job_data=job_data_for(job),
            skill_result={"score": fs.skill_score},
            experience_result={"experience_score": fs.experience_score},
            test_score=fs.test_score,
            parsed_resume=parsed_resume_from_row(resume) if resume else {},
        )
        ranking = output["final_result"]["ranking_result"]
        fs.final_score = ranking.get("final_score")
        fs.recommendation = ranking.get("recommendation")
        fs.explanation = ranking.get("ranking_explanation")
        db.commit()
        return {"status": "completed", "final_score": fs.final_score}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Final ranking failed for application %s", application.application_id)
        db.rollback()
        fs.final_score = None
        fs.recommendation = None
        fs.explanation = f"Final ranking failed after the assessment was completed: {type(exc).__name__}: {exc}"
        db.commit()
        return {"status": "failed", "error": fs.explanation}


def assessment_state(assessment: Optional[models.Assessment]) -> str:
    if assessment is None or not assessment.questions:
        return "not_started"
    if assessment.completed_at is not None:
        return "completed"
    return "in_progress"
