"""
Explained decisions.

Every time HR shortlists, selects or rejects an application the candidate gets a written explanation of
what drove the outcome: where the process stopped, which scores counted, which skills matched or were
missing, how each assessment topic went, anything that affected the result (such as an assessment that
was ended for integrity reasons), and what to do next.

The text is assembled deterministically from the stored scores and answers, so it is reproducible and can
never contradict the numbers. It never includes other candidates' data, ranks or hidden test cases.

`build_feedback()` is a pure function over a plain dict of facts (unit-tested without a database);
`facts_for_application()` collects those facts from the database.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from .pipeline_service import LABEL, build_pipeline, facts_for_application as pipeline_facts

POSITIVE = ("shortlisted", "scheduled", "interviewed", "selected", "offered", "hired")


def _pct(v: Optional[float]) -> Optional[int]:
    return None if v is None else int(round(v))


def _join(items: list[str], limit: int = 5) -> str:
    items = [i for i in items if i][:limit]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def topic_breakdown(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-topic performance from graded answers: [{skill, correct, total, percent}] weakest first."""
    by: dict[str, list[float]] = {}
    for r in results:
        skill = (r.get("skill") or "General").strip() or "General"
        by.setdefault(skill, []).append(float(r.get("score") or 0))
    rows = [{"skill": s, "correct": round(sum(v), 1), "total": len(v), "percent": int(round(sum(v) / len(v) * 100))}
            for s, v in by.items()]
    return sorted(rows, key=lambda r: (r["percent"], r["skill"]))


def build_feedback(f: dict[str, Any]) -> dict[str, Any]:
    status = f.get("status") or "submitted"
    job = f.get("job_title") or "this role"
    skill, exp, test, final = (f.get(k) for k in ("skill_score", "experience_score", "test_score", "final_score"))
    matched, missing = f.get("skill_matched") or [], f.get("skill_missing") or []
    weights = f.get("weights") or {}
    pipe = build_pipeline(f)
    stopped = pipe["outcome"]["stopped_at"]
    topics = topic_breakdown(f.get("assessment_results") or [])
    exp_years, min_exp = f.get("experience_years"), f.get("min_experience")

    strengths: list[str] = []
    gaps: list[str] = []
    steps: list[str] = []

    if skill is not None:
        if skill >= 70:
            strengths.append(f"Strong skills match ({_pct(skill)}%)" + (f" — your resume showed {_join(matched)}." if matched else "."))
        elif matched:
            strengths.append(f"Your resume showed {_join(matched)} (skills match {_pct(skill)}%).")
    if missing:
        gaps.append(f"Skills the role asks for that your resume didn't show: {_join(missing, 6)}.")
        steps.append(f"If you have experience with {_join(missing, 3)}, add it to your profile and resume with a concrete project or result.")
    if exp is not None:
        if exp >= 70:
            strengths.append(f"Experience fits the role ({_pct(exp)}%)" + (f" — about {exp_years:g} years on your resume." if exp_years else "."))
        elif min_exp:
            have = f"{exp_years:g}" if exp_years is not None else "less"
            gaps.append(f"The role looks for around {min_exp:g}+ years of relevant experience; your resume shows {have}.")
            steps.append("Highlight relevant internships, freelance and project work with dates so your experience is measured fully.")
    if test is not None:
        good = [t["skill"] for t in topics if t["percent"] >= 75 and t["skill"].lower() != "coding"]
        weak = [t["skill"] for t in topics if t["percent"] < 50]
        if test >= 70:
            strengths.append(f"Assessment score of {_pct(test)}%" + (f", strongest in {_join(list(reversed(good)), 3)}." if good else "."))
        else:
            gaps.append(f"Assessment score of {_pct(test)}%" + (f"; the weakest topics were {_join(weak, 3)}." if weak else "."))
        if weak:
            steps.append(f"Practise {_join(weak, 3)} in the Practice zone — mock assessments there use the same format.")
    coding = f.get("coding") or []
    for c in coding:
        if c.get("total"):
            line = f"Coding: {c['passed']} of {c['total']} test cases passed"
            (strengths if c["passed"] == c["total"] else gaps).append(line + ".")

    integrity = f.get("integrity")
    integrity_note = None
    if integrity == "terminated":
        integrity_note = (f"Your assessment was ended automatically after {f.get('strikes', 0)} proctoring warnings, so only the "
                          "answers saved up to that point were graded. This affected your score.")
        gaps.append(integrity_note)
        steps.append("In future assessments, stay on the test tab and in full screen, keep your face in view and avoid background noise.")
    elif integrity == "flagged":
        integrity_note = (f"{f.get('strikes', 0)} proctoring warning(s) were recorded during your assessment and shared with the hiring team.")

    # ---- headline & summary ----
    scores_line = _scores_line(skill, exp, test)
    if status == "rejected":
        tone = "negative"
        if stopped == "assessment":
            headline = "Not taken forward to an interview"
            summary = (f"You completed the skill and experience evaluation for {job}{scores_line}, but after the assessment "
                       f"the hiring team decided not to move you to an interview. The process stopped at the assessment stage.")
        elif stopped in ("skill", "experience", "applied"):
            headline = "Not taken forward after screening"
            summary = (f"Your application for {job} was reviewed against the role's requirements{scores_line}. "
                       f"The hiring team decided not to continue; the process stopped at the {LABEL[stopped].lower()} stage.")
        elif stopped == "interview":
            headline = "Not taken forward after the interview"
            summary = f"You made it to the interview stage for {job}, but the hiring team decided not to continue to an offer."
        else:
            headline = "Application closed"
            summary = f"The hiring team closed your application for {job}."
        if final is not None:
            summary += f" Your overall weighted score was {_pct(final)}%."
        steps.append("Apply again when you've closed the gaps above — each application is evaluated fresh.")
    elif status in ("offered", "hired"):
        tone, headline = "positive", ("Welcome aboard" if status == "hired" else "You've been selected — an offer is on its way")
        summary = f"Congratulations. You progressed through every stage for {job}{scores_line}."
    elif status == "selected":
        tone, headline = "positive", "You've been selected"
        summary = f"The hiring team selected you for {job}{scores_line}. The offer letter is being prepared."
    elif status in ("shortlisted", "scheduled", "interviewed"):
        tone = "positive"
        headline = "You're through to the interview stage" if status != "interviewed" else "Interview completed"
        summary = f"You were shortlisted for {job}{scores_line}."
        if status == "shortlisted":
            steps.append("Watch for an interview invitation by email; you'll be able to confirm a slot from your Interviews page.")
    elif status == "offer_declined":
        tone, headline = "neutral", "Offer declined"
        summary = f"You declined the offer for {job}."
    else:
        tone, headline = "neutral", "Your progress so far"
        summary = f"Here is how your application for {job} stands{scores_line or ''}. No decision has been made yet."

    if final is not None and weights:
        w = [f"skills {int(weights.get('skill', 0))}%", f"experience {int(weights.get('experience', 0))}%", f"assessment {int(weights.get('assessment', 0))}%"]
        weighting = f"The role weighs {', '.join(w)}."
    else:
        weighting = None

    if not strengths and tone != "positive":
        strengths.append("Your application was fully evaluated against the role's requirements.")
    return {
        "status": status, "tone": tone, "headline": headline, "summary": summary,
        "stopped_at": stopped, "stopped_label": LABEL.get(stopped) if stopped else None,
        "scores": {"skill": _pct(skill), "experience": _pct(exp), "test": _pct(test), "final": _pct(final),
                   "weights": weights or None, "weighting": weighting},
        "skills": {"matched": matched, "missing": missing},
        "topics": topics, "coding": coding,
        "strengths": strengths, "gaps": gaps, "next_steps": _dedupe(steps),
        "integrity": {"status": integrity, "strikes": f.get("strikes", 0), "note": integrity_note} if integrity_note else None,
        "hr_note": (f.get("decision_note") or "").strip() or None,
        "pipeline": pipe,
        "decided_at": f.get("decision_at"),
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def _scores_line(skill, exp, test) -> str:
    bits = []
    if skill is not None:
        bits.append(f"skills {_pct(skill)}%")
    if exp is not None:
        bits.append(f"experience {_pct(exp)}%")
    if test is not None:
        bits.append(f"assessment {_pct(test)}%")
    return f" ({', '.join(bits)})" if bits else ""


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


# ---- database glue ------------------------------------------------------------------------------

def _csv(v: Optional[str]) -> list[str]:
    return [s.strip() for s in (v or "").split(",") if s.strip() and s.strip().lower() != "none detected"]


def facts_for_application(db, app) -> dict[str, Any]:
    from ..scoring_service import assessment_state  # noqa: F401  (kept for parity with pipeline facts)
    f = pipeline_facts(db, app)
    fs, job, a = app.final_score, app.job, app.assessment
    resume = app.candidate.resume if app.candidate else None
    f.update({
        "job_title": job.title if job else None,
        "final_score": fs.final_score if fs else None,
        "skill_matched": _csv(fs.skill_matched) if fs else [], "skill_missing": _csv(fs.skill_missing) if fs else [],
        "weights": ({"skill": job.weight_skill, "experience": job.weight_experience, "assessment": job.weight_test}
                    if job and job.weight_skill is not None else None),
        "min_experience": job.min_experience if job else None,
        "experience_years": resume.experience_years if resume else None,
        "decision_note": app.decision_note, "decision_at": app.decision_at.isoformat() + "Z" if app.decision_at else None,
        "integrity": a.integrity if a and a.proctored else None, "strikes": (a.strikes if a else 0) or 0,
    })
    if a is not None and a.completed_at is not None:
        f["assessment_results"], f["coding"] = _graded(db, a)
    return f


def _graded(db, a) -> tuple[list[dict], list[dict]]:
    """Per-question results with the skill each question tested; coding results summarised separately."""
    from . import assessment_service as svc
    try:
        answers = json.loads(a.answers or "[]")
        questions = svc.question_set(a).questions
    except Exception:
        return [], []
    results, coding = [], []
    for r in answers:
        idx = r.get("index")
        q = questions[idx] if isinstance(idx, int) and 0 <= idx < len(questions) else None
        skill = getattr(q, "skill", None) if q is not None else None
        if r.get("type") == "coding":
            sub = svc._latest_submission(db, a, idx, "submit")
            if sub is not None:
                coding.append({"title": getattr(q, "question", "Coding problem"), "passed": sub.passed, "total": sub.total,
                               "language": sub.language})
            continue
        results.append({"skill": skill, "score": r.get("score", 0)})
    return results, coding


def feedback_for_application(db, app) -> dict[str, Any]:
    """The stored snapshot taken at decision time, or a live explanation when no decision exists yet."""
    if app.decision_feedback and app.status in POSITIVE + ("rejected", "offer_declined"):
        try:
            snap = json.loads(app.decision_feedback)
            snap["pipeline"] = build_pipeline(pipeline_facts(db, app))     # always show the current pipeline
            return snap
        except ValueError:
            pass
    return build_feedback(facts_for_application(db, app))
