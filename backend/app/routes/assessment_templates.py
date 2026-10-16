"""HR assessment builder: AI-generate (LangGraph) → review/edit → publish.

A job has at most one *published* template. Candidates who start the job's
assessment receive a copy of it (assessment_service.start)."""

import json
import logging
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from .. import models
from ..agents.assessment_llm import GeneratedQuestion, GeneratedQuestionSet, QuestionType
from ..agents.skill_agent import parse_requirements
from ..database import get_db
from ..security import Principal, ensure_verified_hr, hr_can_access_job, require_hr
from ..services import assessment_service, credits_service

router = APIRouter(prefix="/hr/assessments", tags=["assessment builder"])
logger = logging.getLogger(__name__)


class GenerateIn(BaseModel):
    job_id: int
    title: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    num_questions: int = Field(10, ge=1, le=30)
    assessment_type: Literal["mcq", "coding", "mixed"] = "mixed"
    time_limit_minutes: int = Field(30, ge=5, le=180)


class TemplateUpdate(BaseModel):
    title: Optional[str] = None
    time_limit_minutes: Optional[int] = Field(None, ge=5, le=180)
    questions: Optional[List[dict]] = None


def _job(db: Session, user: Principal, job_id: int) -> models.JobRole:
    job = db.get(models.JobRole, job_id)
    if job is None or not hr_can_access_job(user, job):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _template(db: Session, user: Principal, template_id: int) -> models.AssessmentTemplate:
    t = db.get(models.AssessmentTemplate, template_id)
    if t is None or t.hr_account_id != user.id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return t


def _problem_summary(p: Optional[models.CodingProblem]) -> Optional[dict]:
    if p is None:
        return None
    return {"problem_id": p.problem_id, "title": p.title, "difficulty": p.difficulty, "statement": p.statement,
            "input_format": p.input_format, "output_format": p.output_format, "constraints": p.constraints,
            "examples": json.loads(p.examples or "[]"),
            "test_count": len(json.loads(p.visible_tests or "[]")) + len(json.loads(p.hidden_tests or "[]")),
            "ai_generated": bool(p.slug is None and p.hr_account_id)}


def template_dict(db: Session, t: models.AssessmentTemplate, full: bool = True) -> dict:
    qset = json.loads(t.questions or '{"questions": []}')
    job = db.get(models.JobRole, t.job_id)
    counts = {"mcq": 0, "short_answer": 0, "coding": 0}
    for q in qset.get("questions", []):
        counts[q.get("type", "mcq")] = counts.get(q.get("type", "mcq"), 0) + 1
    out = {"template_id": t.template_id, "job_id": t.job_id, "job_title": job.title if job else None,
           "title": t.title, "assessment_type": t.assessment_type, "difficulty": t.difficulty,
           "time_limit_minutes": t.time_limit_minutes, "skills": json.loads(t.skills or "[]"),
           "status": t.status, "question_counts": counts, "num_questions": sum(counts.values()),
           "notes": json.loads(t.generation_notes or "[]"), "created_at": t.created_at,
           "updated_at": t.updated_at, "published_at": t.published_at}
    if full:
        qs = []
        for q in qset.get("questions", []):
            item = dict(q)
            if q.get("type") == "coding":
                item["problem"] = _problem_summary(db.get(models.CodingProblem, q.get("problem_id"))) if q.get("problem_id") else None
            qs.append(item)
        out["questions"] = qs
    return out


def _save_problem(db: Session, user: Principal, p: dict, difficulty: str) -> models.CodingProblem:
    tests = p["tests"]
    row = models.CodingProblem(
        hr_account_id=user.id, title=p["title"][:200], difficulty=difficulty, tags=p.get("skill") or "",
        statement=p["statement"], input_format=p.get("input_format"), output_format=p.get("output_format"),
        constraints=p.get("constraints"), examples=json.dumps(p.get("examples", [])),
        visible_tests=json.dumps(tests[:2]), hidden_tests=json.dumps(tests[2:]), active=True)
    db.add(row)
    db.flush()
    return row


@router.post("/generate")
def generate(data: GenerateIn, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    ensure_verified_hr(db, user)
    job = _job(db, user, data.job_id)
    skills = [s.strip() for s in data.skills if s.strip()] or parse_requirements(job.requirements or "")
    if not skills:
        raise HTTPException(status_code=422, detail="Add at least one skill to assess")
    # Check the balance up front, but only charge after the agent succeeds, so no
    # transaction (or lock) is held open during the slow LLM + sandbox run.
    cost = credits_service.config.CREDIT_COSTS.get("ai_assessment", 0)
    if cost > 0 and credits_service.balance(db, "hr", user.id) < cost:
        raise HTTPException(status_code=402, detail=f"Not enough credits: {cost} needed. Buy credits to continue.")
    fallback = [{"problem_id": p.problem_id, "title": p.title, "difficulty": p.difficulty, "tags": p.tags}
                for p in assessment_service.pick_coding_problems(db, job, 5)]
    try:
        from ..agents.assessment_graph import run_assessment_graph
        result = run_assessment_graph(job_title=job.title, job_description=job.description or "", skills=skills,
                                      difficulty=data.difficulty, num_questions=data.num_questions,
                                      assessment_type=data.assessment_type, fallback_problems=fallback)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Assessment generation failed for job %s", job.job_id)
        raise HTTPException(status_code=502, detail="The AI could not generate this assessment right now (check that "
                                                    "GROQ_API_KEY is configured). No credits were used — please try again.")
    qset = result["question_set"]
    new_iter = iter(result.get("new_problems", []))
    for q in qset["questions"]:
        if q["type"] == "coding" and not q.get("problem_id"):
            q["problem_id"] = _save_problem(db, user, next(new_iter), data.difficulty).problem_id
    if not qset["questions"]:
        db.rollback()
        raise HTTPException(status_code=502, detail="The AI returned no usable questions. No credits were used — please try again.")
    t = models.AssessmentTemplate(
        job_id=job.job_id, hr_account_id=user.id, title=(data.title or f"{job.title} assessment").strip()[:200],
        assessment_type=data.assessment_type, difficulty=data.difficulty, num_questions=len(qset["questions"]),
        time_limit_minutes=data.time_limit_minutes, skills=json.dumps(skills), questions=json.dumps(qset),
        generation_notes=json.dumps(result.get("notes", [])), status="draft")
    db.add(t)
    db.flush()
    credits_service.spend(db, "hr", user.id, "ai_assessment", f"AI assessment draft — {job.title}",
                          reference=f"assessment:template:{t.template_id}", commit=False)
    db.commit()
    db.refresh(t)
    return template_dict(db, t)


@router.get("/templates")
def list_templates(job_id: Optional[int] = None, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    q = db.query(models.AssessmentTemplate).filter(models.AssessmentTemplate.hr_account_id == user.id,
                                                   models.AssessmentTemplate.status != "archived")
    if job_id:
        q = q.filter(models.AssessmentTemplate.job_id == job_id)
    return [template_dict(db, t, full=False) for t in q.order_by(models.AssessmentTemplate.template_id.desc()).all()]


@router.get("/templates/{template_id}")
def get_template(template_id: int, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    return template_dict(db, _template(db, user, template_id))


def _validate_questions(db: Session, user: Principal, raw: List[dict]) -> GeneratedQuestionSet:
    questions = []
    for i, q in enumerate(raw, start=1):
        q = {k: v for k, v in q.items() if k != "problem"}
        try:
            gq = GeneratedQuestion.model_validate(q)
        except ValidationError:
            raise HTTPException(status_code=422, detail=f"Question {i} is incomplete or invalid")
        if not gq.question.strip():
            raise HTTPException(status_code=422, detail=f"Question {i} has no text")
        if gq.type == QuestionType.MCQ:
            opts = [o for o in (gq.options or []) if o.text.strip()]
            if len(opts) < 2:
                raise HTTPException(status_code=422, detail=f"Question {i} needs at least two options")
            if gq.correct_option_label not in {o.label for o in opts}:
                raise HTTPException(status_code=422, detail=f"Question {i}: choose the correct option")
            gq.options = opts
        elif gq.type == QuestionType.SHORT_ANSWER:
            if not (gq.reference_answer or "").strip():
                raise HTTPException(status_code=422, detail=f"Question {i} needs a reference answer for grading")
        else:
            p = db.get(models.CodingProblem, gq.problem_id) if gq.problem_id else None
            if p is None or not (p.hr_account_id is None or p.hr_account_id == user.id):
                raise HTTPException(status_code=422, detail=f"Question {i}: choose a coding problem")
            gq.question = gq.question or p.title
        questions.append(gq)
    return GeneratedQuestionSet(skills_covered=sorted({q.skill for q in questions if q.skill}), questions=questions)


@router.put("/templates/{template_id}")
def update_template(template_id: int, data: TemplateUpdate, user: Principal = Depends(require_hr),
                    db: Session = Depends(get_db)):
    t = _template(db, user, template_id)
    if t.status == "archived":
        raise HTTPException(status_code=409, detail="Archived assessments can't be edited")
    if data.title is not None:
        if not data.title.strip():
            raise HTTPException(status_code=422, detail="Title is required")
        t.title = data.title.strip()[:200]
    if data.time_limit_minutes is not None:
        t.time_limit_minutes = data.time_limit_minutes
    if data.questions is not None:
        qset = _validate_questions(db, user, data.questions)
        if not qset.questions and t.status == "published":
            raise HTTPException(status_code=422, detail="A published assessment needs at least one question")
        t.questions = qset.model_dump_json()
        t.num_questions = len(qset.questions)
    db.commit()
    db.refresh(t)
    return template_dict(db, t)


@router.post("/templates/{template_id}/publish")
def publish_template(template_id: int, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    t = _template(db, user, template_id)
    if t.status == "archived":
        raise HTTPException(status_code=409, detail="Archived assessments can't be published")
    if not json.loads(t.questions or "{}").get("questions"):
        raise HTTPException(status_code=422, detail="Add at least one question before publishing")
    (db.query(models.AssessmentTemplate)
     .filter(models.AssessmentTemplate.job_id == t.job_id, models.AssessmentTemplate.status == "published",
             models.AssessmentTemplate.template_id != t.template_id)
     .update({"status": "archived"}, synchronize_session=False))
    t.status, t.published_at = "published", datetime.utcnow()
    db.commit()
    db.refresh(t)
    return template_dict(db, t)


@router.post("/templates/{template_id}/unpublish")
def unpublish_template(template_id: int, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    t = _template(db, user, template_id)
    if t.status != "published":
        raise HTTPException(status_code=409, detail="This assessment is not published")
    t.status = "draft"
    db.commit()
    return template_dict(db, t)


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    t = _template(db, user, template_id)
    used = db.query(models.Assessment).filter(models.Assessment.template_id == t.template_id).count()
    if used:
        t.status = "archived"        # candidates already took it: keep it for their results
    else:
        db.delete(t)
    db.commit()
    return {"deleted": True, "archived": bool(used)}
