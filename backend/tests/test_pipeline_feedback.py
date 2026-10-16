"""The six-stage pipeline and the explained-decision text (pure functions, no database)."""

import importlib.util
import sys
import types
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _load():
    # Load the two service modules without importing the web stack (their DB glue imports lazily).
    pkg = types.ModuleType("app"); pkg.__path__ = [str(APP)]; sys.modules.setdefault("app", pkg)
    sv = types.ModuleType("app.services"); sv.__path__ = [str(APP / "services")]; sys.modules.setdefault("app.services", sv)
    out = {}
    for name in ("pipeline_service", "feedback_service"):
        spec = importlib.util.spec_from_file_location(f"app.services.{name}", APP / "services" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec); sys.modules[f"app.services.{name}"] = mod; spec.loader.exec_module(mod)
        out[name] = mod
    return out["pipeline_service"], out["feedback_service"]


P, F = _load()
BASE = dict(has_resume=True, skill_score=72, experience_score=80, screening_status="completed")


def states(f):
    return {s["key"]: s["state"] for s in P.build_pipeline(f)["stages"]}


def test_stages_are_the_six_the_product_promises():
    assert P.KEYS == ["applied", "skill", "experience", "assessment", "interview", "offer"]


def test_fresh_application_waits_for_assessment():
    s = states(dict(BASE, status="in_review"))
    assert s == {"applied": "done", "skill": "done", "experience": "done", "assessment": "active", "interview": "pending", "offer": "pending"}


def test_rejection_after_assessment_stops_at_assessment_and_skips_the_rest():
    f = dict(BASE, status="rejected", test_score=35, assessment_state="completed")
    out = P.build_pipeline(f)
    assert states(f) == {"applied": "done", "skill": "done", "experience": "done", "assessment": "stopped", "interview": "skipped", "offer": "skipped"}
    assert out["outcome"]["state"] == "stopped" and out["outcome"]["stopped_at"] == "assessment"


def test_recorded_stop_stage_wins_over_inference():
    f = dict(BASE, status="rejected", assessment_state="completed", decision_stage="experience")
    assert states(f)["experience"] == "stopped" and states(f)["assessment"] == "skipped"


def test_rejection_after_screening_only():
    f = dict(BASE, status="rejected")
    assert P.infer_stop_stage(f) == "experience"
    assert P.infer_stop_stage({"status": "rejected"}) == "applied"


def test_shortlisted_scheduled_offered_hired():
    done = dict(BASE, test_score=80, assessment_state="completed")
    assert states(dict(done, status="shortlisted"))["interview"] == "active"
    assert states(dict(done, status="scheduled", has_interview=True))["interview"] == "active"
    s = states(dict(done, status="offered", has_interview=True, offer_status="sent"))
    assert s["interview"] == "done" and s["offer"] == "active"
    s = states(dict(done, status="hired", offer_status="accepted"))
    assert set(s.values()) == {"done"}


def test_declined_offer_stops_at_offer():
    f = dict(BASE, status="offer_declined", test_score=80, assessment_state="completed", offer_status="rejected")
    out = P.build_pipeline(f)
    assert states(f)["offer"] == "stopped" and out["outcome"]["by_candidate"] is True


def test_rejection_feedback_explains_where_and_why():
    f = dict(BASE, status="rejected", job_title="Python Developer", test_score=41, final_score=62, assessment_state="completed",
             skill_matched=["Python"], skill_missing=["Docker", "Kubernetes"], min_experience=3, experience_years=4,
             weights={"skill": 40, "experience": 30, "assessment": 30}, decision_note="Need deeper SQL.",
             assessment_results=[{"skill": "SQL", "score": 0}, {"skill": "SQL", "score": 0}, {"skill": "Python", "score": 1}])
    fb = F.build_feedback(f)
    assert fb["tone"] == "negative" and fb["stopped_at"] == "assessment"
    assert "stopped at the assessment stage" in fb["summary"]
    assert any("Docker" in g for g in fb["gaps"]) and any("SQL" in g for g in fb["gaps"])
    assert any("Practice zone" in n for n in fb["next_steps"])
    assert fb["hr_note"] == "Need deeper SQL." and fb["scores"]["test"] == 41
    assert fb["topics"][0]["skill"] == "SQL" and fb["topics"][0]["percent"] == 0       # weakest first


def test_feedback_mentions_integrity_termination():
    f = dict(BASE, status="rejected", assessment_state="completed", test_score=20, integrity="terminated", strikes=3)
    fb = F.build_feedback(f)
    assert fb["integrity"]["status"] == "terminated"
    assert any("ended automatically" in g for g in fb["gaps"])


def test_positive_feedback_for_shortlist():
    fb = F.build_feedback(dict(BASE, status="shortlisted", job_title="X", test_score=88, assessment_state="completed", skill_matched=["A"]))
    assert fb["tone"] == "positive" and "shortlisted" in fb["summary"]


def test_feedback_never_contains_other_candidates():
    fb = F.build_feedback(dict(BASE, status="rejected", assessment_state="completed"))
    assert "rank" not in " ".join(fb["strengths"] + fb["gaps"]).lower()
