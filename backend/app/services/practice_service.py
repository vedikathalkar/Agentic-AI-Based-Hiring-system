"""Practice zone: AI mock interviews and mock assessments for the role a candidate
is preparing for. Practice results are private to the candidate — they are never
shown to employers and never affect real applications."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..agents import mock_interview_llm as L
from ..agents.practice_bank import pick_mcqs
from ..agents.skill_agent import normalize_skill, parse_requirements
from . import code_runner, profile_service

GRACE_SECONDS = 10            # network delay allowance on per-question limits
ASSESSMENT_GRACE_SECONDS = 30


def _j(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# Shared context: what role is the candidate preparing for?
# ---------------------------------------------------------------------------

def candidate_skills(db: Session, account_id: int) -> list[str]:
    p = profile_service.get_candidate_profile(db, account_id)
    skills: list[str] = []
    for key in ("technical_skills", "frameworks", "tools", "languages"):
        skills += [s for s in profile_service._loads(getattr(p, key)) if isinstance(s, str)]
    if not skills:
        cand = (db.query(models.Candidate).filter(models.Candidate.account_id == account_id)
                .order_by(models.Candidate.candidate_id.desc()).first())
        if cand and cand.resume and cand.resume.skills:
            skills = [s.strip() for s in cand.resume.skills.split(",") if s.strip()]
    return list(dict.fromkeys(skills))


def build_context(db: Session, account_id: int, job_id: Optional[int], role_title: Optional[str],
                  skills: Optional[list[str]]) -> dict:
    job = db.get(models.JobRole, job_id) if job_id else None
    if job_id and job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    title = (job.title if job else (role_title or "").strip()) or ""
    if not title:
        raise HTTPException(status_code=422, detail="Choose a job or type the role you are preparing for")
    role_skills = [s.strip() for s in (skills or []) if s and s.strip()]
    if not role_skills and job:
        role_skills = parse_requirements(job.requirements or "")
    if not role_skills:
        raise HTTPException(status_code=422, detail="Add at least one skill for this role")
    mine = candidate_skills(db, account_id)
    have = {normalize_skill(s) for s in mine}
    gaps = [s for s in role_skills if normalize_skill(s) not in have]
    return {"job_id": job.job_id if job else None, "job_title": title, "job_description": (job.description if job else "") or "",
            "skills": role_skills[:12], "candidate_skills": mine[:30], "gaps": gaps[:6]}


def coding_pool(db: Session, skills: list[str], difficulty: str, count: int) -> list[models.CodingProblem]:
    if count <= 0 or not code_runner.available_languages():
        return []
    wanted = {normalize_skill(s) for s in skills}
    order = {"easy": 0, "medium": 1, "hard": 2}
    probs = db.query(models.CodingProblem).filter(models.CodingProblem.active.is_(True),
                                                  models.CodingProblem.hr_account_id.is_(None)).all()

    def rank(p):
        tags = {normalize_skill(t) for t in (p.tags or "").split(",") if t.strip()}
        return (-len(tags & wanted), abs(order.get(p.difficulty, 1) - order.get(difficulty, 1)), p.problem_id)
    return sorted(probs, key=rank)[:count]


def problem_payload(p: Optional[models.CodingProblem]) -> Optional[dict]:
    if p is None:
        return None
    return {"problem_id": p.problem_id, "title": p.title, "statement": p.statement, "input_format": p.input_format,
            "output_format": p.output_format, "constraints": p.constraints, "examples": _j(p.examples, []),
            "sample_tests": _j(p.visible_tests, []), "hidden_test_count": len(_j(p.hidden_tests, [])),
            "languages": code_runner.available_languages()}


def run_problem(p: models.CodingProblem, language: str, source: str, include_hidden: bool) -> dict:
    if not code_runner.is_available(language):
        raise HTTPException(status_code=422, detail=f"{language} is not available on this server")
    visible = _j(p.visible_tests, [])
    tests = visible + (_j(p.hidden_tests, []) if include_hidden else [])
    report = code_runner.execute(language, source or "", tests, p.time_limit_ms or 2000, p.memory_limit_mb or 256)
    out = {"status": report.status, "passed": report.passed, "total": report.total, "error": report.error,
           "time_ms": report.time_ms, "tests": []}
    for i, t in enumerate(report.tests):
        if i < len(visible):
            out["tests"].append({"name": f"Sample {i + 1}", "passed": t.passed, "status": t.status, "input": t.input,
                                 "expected": t.expected, "actual": t.actual, "stderr": t.stderr})
        else:
            out["tests"].append({"name": f"Hidden {i - len(visible) + 1}", "passed": t.passed, "status": t.status, "hidden": True})
    return out


def roles(db: Session, account_id: int) -> dict:
    applied = {a.job_id for a in db.query(models.Application).join(models.Candidate)
               .filter(models.Candidate.account_id == account_id).all()}
    jobs = (db.query(models.JobRole).filter((models.JobRole.status.is_(None)) | (models.JobRole.status == "open"))
            .order_by(models.JobRole.created_at.desc().nullslast()).limit(100).all())
    out = [{"job_id": j.job_id, "title": j.title, "skills": parse_requirements(j.requirements or ""),
            "applied": j.job_id in applied} for j in jobs]
    out.sort(key=lambda j: not j["applied"])
    return {"jobs": out, "my_skills": candidate_skills(db, account_id), "ai_available": L.ai_available(),
            "code_languages": [x["key"] for x in code_runner.available_languages()]}


# ---------------------------------------------------------------------------
# Mock interviews
# ---------------------------------------------------------------------------

def _graph():
    from ..agents import mock_interview_graph
    return mock_interview_graph


def _current(turns: list[dict]) -> Optional[dict]:
    return next((t for t in reversed(turns) if t.get("status") in ("pending", "active")), None)


def interview_dict(db: Session, iv: models.MockInterview, full: bool = True) -> dict:
    cfg, turns = _j(iv.config, {}), _j(iv.turns, [])
    out = {"interview_id": iv.interview_id, "role_title": iv.role_title, "job_id": iv.job_id, "status": iv.status,
           "config": cfg, "overall_score": iv.overall_score, "engine": iv.engine, "created_at": iv.created_at,
           "completed_at": iv.completed_at, "question_count": len([t for t in turns if t["kind"] == "question"]),
           "planned": len(_j(iv.plan, []))}
    if not full:
        return out
    now = datetime.utcnow()
    total = cfg.get("total_limit_minutes")
    if total and iv.started_at and iv.status == "in_progress":
        out["total_remaining_s"] = int(total * 60 - (now - iv.started_at).total_seconds())
    shown = []
    for t in turns:
        item = {k: v for k, v in t.items() if k not in ("points",)}
        if t.get("status") in ("answered", "skipped"):
            item["key_points"] = [p["text"] for p in t.get("points", [])]   # revealed after answering
        if t.get("status") == "active" and t.get("started_at"):
            item["remaining_s"] = int(t["time_limit_s"] - (now - datetime.fromisoformat(t["started_at"])).total_seconds())
        if t.get("problem_id"):
            item["problem"] = problem_payload(db.get(models.CodingProblem, t["problem_id"]))
        item["type_label"] = L.TYPE_LABELS.get(t["qtype"], t["qtype"])
        shown.append(item)
    out.update({"turns": shown, "plan": _j(iv.plan, []), "report": _j(iv.report, None),
                "current_index": (_current(turns) or {}).get("index")})
    return out


def _save(iv: models.MockInterview, state: dict) -> None:
    if "plan" in state:
        iv.plan = json.dumps(state["plan"])
    iv.turns = json.dumps(state.get("turns", []))
    if state.get("engine") == "ai":
        iv.engine = "ai"
    if state.get("report"):
        iv.report = json.dumps(state["report"])
        iv.overall_score = state["report"]["overall_score"]
        iv.status, iv.completed_at = "completed", datetime.utcnow()


def _state(iv: models.MockInterview, phase: str, db: Session, force_finish: bool = False) -> dict:
    cfg = _j(iv.config, {})
    ctx = cfg.get("context", {})
    turns = _j(iv.turns, [])
    plan = _j(iv.plan, [])
    slot_index = max([t["slot"] for t in turns], default=0)
    return {"phase": phase, "context": ctx, "config": cfg, "plan": plan, "turns": turns, "slot_index": slot_index,
            "followups_used": len([t for t in turns if t["kind"] == "followup"]), "force_finish": force_finish,
            "engine": iv.engine}


def create_interview(db: Session, account_id: int, data: dict) -> models.MockInterview:
    ctx = build_context(db, account_id, data.get("job_id"), data.get("role_title"), data.get("skills"))
    difficulty = data.get("difficulty", "medium")
    if data.get("interview_type") != "behavioural" and data.get("include_coding", True):
        pool = coding_pool(db, ctx["skills"], difficulty, 1)
        ctx["coding_pool"] = [{"problem_id": p.problem_id, "title": p.title} for p in pool]
    cfg = {"interview_type": data.get("interview_type", "mixed"), "difficulty": difficulty,
           "num_questions": data.get("num_questions", 5), "mode": data.get("mode", "interview"),
           "total_limit_minutes": data.get("total_limit_minutes"), "context": ctx}
    iv = models.MockInterview(account_id=account_id, job_id=ctx["job_id"], role_title=ctx["job_title"][:200],
                              config=json.dumps(cfg), engine="ai" if L.ai_available() else "offline")
    state = _graph().run({**_state(iv, "start", db), "phase": "start"})
    _save(iv, state)
    db.add(iv)
    db.commit()
    db.refresh(iv)
    return iv


def own_interview(db: Session, account_id: int, interview_id: int) -> models.MockInterview:
    iv = db.get(models.MockInterview, interview_id)
    if iv is None or iv.account_id != account_id:
        raise HTTPException(status_code=404, detail="Mock interview not found")
    return iv


def begin_question(db: Session, iv: models.MockInterview) -> None:
    """The candidate finished reading: start this question's clock (server time)."""
    if iv.status != "in_progress":
        raise HTTPException(status_code=409, detail="This mock interview is finished")
    turns = _j(iv.turns, [])
    cur = _current(turns)
    if cur is None:
        raise HTTPException(status_code=409, detail="No question is waiting")
    if cur["status"] == "pending":
        cur["status"], cur["started_at"] = "active", datetime.utcnow().isoformat()
        iv.started_at = iv.started_at or datetime.utcnow()
        iv.turns = json.dumps(turns)
        db.commit()


def answer_question(db: Session, iv: models.MockInterview, data: dict) -> None:
    if iv.status != "in_progress":
        raise HTTPException(status_code=409, detail="This mock interview is finished")
    cfg = _j(iv.config, {})
    turns = _j(iv.turns, [])
    cur = _current(turns)
    if cur is None:
        raise HTTPException(status_code=409, detail="No question is waiting for an answer")
    now = datetime.utcnow()
    started = datetime.fromisoformat(cur["started_at"]) if cur.get("started_at") else now
    used = max(0, int((now - started).total_seconds()))
    limit = cur["time_limit_s"]
    cur.update({"answered_at": now.isoformat(), "time_used_s": min(used, limit + GRACE_SECONDS) if cfg.get("mode") == "interview" else used,
                "answer_mode": data.get("answer_mode") or "text"})
    if data.get("skipped"):
        cur.update({"status": "skipped", "answer": ""})
    else:
        answer = (data.get("answer") or "")[:20000]
        cur.update({"status": "answered", "answer": answer})
        if cfg.get("mode") == "interview":
            cur["timed_out"] = bool(data.get("auto_submitted")) or used > limit + GRACE_SECONDS
        else:
            cur["overrun_s"] = max(0, used - limit)
        if cur["answer_mode"] == "voice":
            cur["speech"] = L.speech_metrics(answer, data.get("speaking_seconds"))
        if cur["qtype"] == "coding" and cur.get("problem_id"):
            p = db.get(models.CodingProblem, cur["problem_id"])
            lang = data.get("language") or "python"
            cur["language"] = lang
            cur["code_result"] = {k: v for k, v in run_problem(p, lang, answer, True).items() if k != "tests"} if (p and answer.strip()) else {"passed": 0, "total": 0}
    iv.turns = json.dumps(turns)
    total = cfg.get("total_limit_minutes")
    force = bool(total and iv.started_at and (now - iv.started_at).total_seconds() > total * 60 + GRACE_SECONDS)
    state = _graph().run(_state(iv, "answer", db, force_finish=force))
    _save(iv, state)
    db.commit()


def finish_interview(db: Session, iv: models.MockInterview) -> None:
    if iv.status != "in_progress":
        return
    state = _graph().run(_state(iv, "finish", db))
    _save(iv, state)
    db.commit()


def run_interview_code(db: Session, iv: models.MockInterview, language: str, source: str) -> dict:
    cur = _current(_j(iv.turns, []))
    if cur is None or not cur.get("problem_id"):
        raise HTTPException(status_code=409, detail="The current question is not a coding question")
    p = db.get(models.CodingProblem, cur["problem_id"])
    if p is None:
        raise HTTPException(status_code=404, detail="Coding problem not found")
    return run_problem(p, language, source, include_hidden=False)


# ---------------------------------------------------------------------------
# Mock assessments
# ---------------------------------------------------------------------------

def create_assessment(db: Session, account_id: int, data: dict) -> models.MockAssessment:
    ctx = build_context(db, account_id, data.get("job_id"), data.get("role_title"), data.get("skills"))
    difficulty = data.get("difficulty", "medium")
    n_mcq, n_code = int(data.get("num_mcq", 10)), int(data.get("num_coding", 1))
    questions: list[dict[str, Any]] = []
    engine = "offline"
    if n_mcq and L.ai_available():
        try:
            from ..agents import assessment_llm
            gen = assessment_llm.generate_mcqs(ctx["job_title"], ctx["job_description"], ctx["skills"], difficulty, n_mcq)
            for q in gen.questions:
                labels = [o.label for o in (q.options or [])]
                if q.correct_option_label in labels and len(labels) >= 2:
                    questions.append({"type": "mcq", "skill": q.skill, "difficulty": difficulty, "question": q.question,
                                      "options": [{"label": o.label, "text": o.text} for o in q.options],
                                      "correct": q.correct_option_label, "explanation": q.reference_answer})
            engine = "ai" if questions else "offline"
        except Exception:  # noqa: BLE001 - fall back to the bank below
            questions = []
    if len(questions) < n_mcq:
        for q in pick_mcqs(ctx["skills"], n_mcq - len(questions), difficulty, seed=account_id * 7919 + int(datetime.utcnow().timestamp())):
            questions.append({"type": "mcq", "skill": q["skill"], "difficulty": q["difficulty"], "question": q["question"],
                              "options": q["options"], "correct": q["correct_option_label"], "explanation": q.get("reference_answer")})
    for p in coding_pool(db, ctx["skills"], difficulty, n_code):
        questions.append({"type": "coding", "skill": "Coding", "difficulty": p.difficulty, "question": p.title, "problem_id": p.problem_id})
    for i, q in enumerate(questions):
        q["index"] = i
    if not questions:
        raise HTTPException(status_code=422, detail="Could not build a practice test for these skills")
    minutes = int(data.get("time_limit_minutes") or max(5, math.ceil(n_mcq * 1.5 + 15 * len([q for q in questions if q["type"] == "coding"]))))
    now = datetime.utcnow()
    m = models.MockAssessment(account_id=account_id, job_id=ctx["job_id"], role_title=ctx["job_title"][:200],
                              config=json.dumps({"skills": ctx["skills"], "gaps": ctx["gaps"], "difficulty": difficulty,
                                                 "num_mcq": n_mcq, "num_coding": n_code}),
                              questions=json.dumps(questions), answers="{}", code="{}", engine=engine,
                              time_limit_minutes=minutes, started_at=now, expires_at=now + timedelta(minutes=minutes))
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def own_assessment(db: Session, account_id: int, mock_id: int) -> models.MockAssessment:
    m = db.get(models.MockAssessment, mock_id)
    if m is None or m.account_id != account_id:
        raise HTTPException(status_code=404, detail="Mock assessment not found")
    return m


def assessment_dict(db: Session, m: models.MockAssessment, full: bool = True) -> dict:
    cfg = _j(m.config, {})
    qs = _j(m.questions, [])
    out = {"mock_id": m.mock_id, "role_title": m.role_title, "job_id": m.job_id, "config": cfg, "score": m.score,
           "engine": m.engine, "time_limit_minutes": m.time_limit_minutes, "started_at": m.started_at,
           "expires_at": m.expires_at, "completed_at": m.completed_at, "auto_submitted": m.auto_submitted,
           "status": "completed" if m.completed_at else "in_progress", "question_count": len(qs)}
    if not full:
        return out
    done = m.completed_at is not None
    if not done:
        out["remaining_s"] = int((m.expires_at - datetime.utcnow()).total_seconds())
    shown = []
    for q in qs:
        item = {k: v for k, v in q.items() if done or k not in ("correct", "explanation")}
        if q.get("problem_id"):
            item["problem"] = problem_payload(db.get(models.CodingProblem, q["problem_id"]))
        shown.append(item)
    out.update({"questions": shown, "answers": _j(m.answers, {}), "code": _j(m.code, {}), "results": _j(m.results, None)})
    return out


def save_progress(db: Session, m: models.MockAssessment, answers: dict, code: dict) -> None:
    if m.completed_at:
        raise HTTPException(status_code=409, detail="This practice test is already submitted")
    if datetime.utcnow() > m.expires_at + timedelta(seconds=ASSESSMENT_GRACE_SECONDS):
        raise HTTPException(status_code=409, detail="Time is up")
    m.answers = json.dumps({str(k): v for k, v in (answers or {}).items()})
    m.code = json.dumps({str(k): {"language": v.get("language"), "source": (v.get("source") or "")[:50000]}
                         for k, v in (code or {}).items() if isinstance(v, dict)})
    db.commit()


def run_assessment_code(db: Session, m: models.MockAssessment, index: int, language: str, source: str) -> dict:
    if m.completed_at:
        raise HTTPException(status_code=409, detail="This practice test is already submitted")
    q = next((q for q in _j(m.questions, []) if q["index"] == index and q["type"] == "coding"), None)
    p = db.get(models.CodingProblem, q["problem_id"]) if q else None
    if p is None:
        raise HTTPException(status_code=404, detail="Coding question not found")
    return run_problem(p, language, source, include_hidden=False)


def submit_assessment(db: Session, m: models.MockAssessment, answers: Optional[dict], code: Optional[dict]) -> None:
    if m.completed_at:
        raise HTTPException(status_code=409, detail="This practice test is already submitted")
    late = datetime.utcnow() > m.expires_at + timedelta(seconds=ASSESSMENT_GRACE_SECONDS)
    if late or answers is None:
        answers, code = _j(m.answers, {}), _j(m.code, {})      # only what was saved in time counts
        m.auto_submitted = late
    else:
        m.answers = json.dumps({str(k): v for k, v in answers.items()})
        m.code = json.dumps({str(k): v for k, v in (code or {}).items()})
    qs = _j(m.questions, [])
    per_q, by_skill = [], {}
    earned = 0.0
    for q in qs:
        k = str(q["index"])
        if q["type"] == "mcq":
            given = (answers.get(k) or "").strip().upper()
            pts = 1.0 if given and given == q["correct"] else 0.0
            per_q.append({"index": q["index"], "type": "mcq", "skill": q["skill"], "given": given or None, "correct": q["correct"],
                          "points": pts, "max": 1.0})
        else:
            c = (code or {}).get(k) or {}
            p = db.get(models.CodingProblem, q["problem_id"])
            res = run_problem(p, c.get("language") or "python", c["source"], True) if (p and (c.get("source") or "").strip()) else {"passed": 0, "total": 0, "status": "not_submitted"}
            pts = round(res["passed"] / res["total"], 3) if res.get("total") else 0.0
            per_q.append({"index": q["index"], "type": "coding", "skill": "Coding", "points": pts, "max": 1.0,
                          "passed": res.get("passed"), "total": res.get("total"), "status": res.get("status"), "error": res.get("error")})
        earned += pts
        s = by_skill.setdefault(q["skill"], {"skill": q["skill"], "points": 0.0, "max": 0})
        s["points"] += pts
        s["max"] += 1
    skills = [{**s, "percent": round(100 * s["points"] / s["max"])} for s in by_skill.values()]
    skills.sort(key=lambda s: s["percent"])
    weak = [s["skill"] for s in skills if s["percent"] < 60]
    m.score = round(100 * earned / len(qs), 1) if qs else 0.0
    m.results = json.dumps({"questions": per_q, "skills": skills,
                            "recommendations": ([f"Revise {w} — then try a mock interview focused on it." for w in weak[:3]]
                                                or ["Great work — try the next difficulty level or a timed mock interview."]),
                            "correct": sum(1 for r in per_q if r["points"] >= 1), "total": len(qs)})
    m.completed_at = datetime.utcnow()
    db.commit()
