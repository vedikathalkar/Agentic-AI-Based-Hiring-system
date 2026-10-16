"""End-to-end score pipeline tests.

Only the resume parser (file -> dict) and the Groq-backed question
generator/grader are monkeypatched. The real LangGraph screening graph, skill,
experience, bias and ranking agents run against a real SQLite database.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("langgraph")

from app.agents.assessment_llm import GeneratedQuestion, GeneratedQuestionSet, MCQOption, QuestionType  # noqa: E402
from conftest import PDF, auth, signup_candidate, verified_hr  # noqa: E402

JOB = {"title": "ML Engineer, Associate", "requirements": "SQL, Python, Tableau", "min_experience": 1,
       "weight_skill": 40, "weight_experience": 20, "weight_test": 40}


def _parsed(skills):
    return {
        "skills": skills,
        "experience": "1 year of software development experience",
        "education": "B.E. Computer Engineering",
        "experience_years": 1.0,
        "experience_entries": [{"title_or_role": "Software Developer", "duration_months": 12,
                                "details": ["Python development"]}],
    }


def _questions(*args, **kwargs):
    return GeneratedQuestionSet(skills_covered=["Python"], questions=[
        GeneratedQuestion(
            type=QuestionType.MCQ, skill="Python", difficulty="easy", question="What is Python?",
            options=[MCQOption(label="A", text="A language"), MCQOption(label="B", text="A database"),
                     MCQOption(label="C", text="A browser"), MCQOption(label="D", text="An OS")],
            correct_option_label="A",
        ),
        GeneratedQuestion(
            type=QuestionType.MCQ, skill="SQL", difficulty="medium", question="Which keyword filters rows?",
            options=[MCQOption(label="A", text="ORDER BY"), MCQOption(label="B", text="WHERE"),
                     MCQOption(label="C", text="GROUP BY"), MCQOption(label="D", text="LIMIT")],
            correct_option_label="B",
        ),
    ])


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """Patch parser + Groq, count question generations."""
    from app.agents import assessment_llm
    from app.routes import resumes
    state = {"skills": "Python, MySQL", "generated": 0}

    def fake_parse(*args, **kwargs):
        return _parsed(state["skills"])

    def fake_generate(*args, **kwargs):
        state["generated"] += 1
        return _questions()

    monkeypatch.setattr(resumes, "parse_resume", fake_parse)
    monkeypatch.setattr(resumes, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(assessment_llm, "generate_questions", fake_generate)
    return state


class World:
    """A verified HR with a job, and a logged-in candidate who applied."""
    def __init__(self, client, job=JOB, cand_email="test@example.com", hr_token=None):
        self.client = client
        self.hr = hr_token or verified_hr(client)
        r = client.post("/jobs", json=job, headers=auth(self.hr))
        assert r.status_code == 200, r.text
        self.job_id = r.json()["job_id"]
        self.cand = signup_candidate(client, email=cand_email)
        r = client.post("/candidates", headers=auth(self.cand),
                        json={"name": "Test Candidate", "email": cand_email, "job_id": self.job_id})
        assert r.status_code == 200, r.text
        self.cid, self.aid = r.json()["candidate_id"], r.json()["application_id"]

    def upload(self, content=PDF):
        return self.client.post(f"/resumes/{self.cid}", headers=auth(self.cand),
                                files={"file": ("resume.pdf", content, "application/pdf")})

    def hr_get(self, path, **kw):
        return self.client.get(path, headers=auth(self.hr), **kw)

    def c_post(self, path, **kw):
        return self.client.post(path, headers=auth(self.cand), **kw)


ALL_RIGHT = {"answers": [{"index": 0, "user_answer": "A"}, {"index": 1, "user_answer": "B"}]}


def test_scores_end_to_end(client, pipeline):
    w = World(client)
    upload = w.upload()
    assert upload.status_code == 200, upload.text
    screening = upload.json()["screening_result"]
    assert screening["status"] == "completed"
    assert screening["skill_score"] == 33.3
    assert screening["experience_score"] is not None

    scores = w.hr_get(f"/candidates/{w.cid}/scores").json()
    assert scores["skill_score"] == 33.3
    experience_score = scores["experience_score"]
    assert experience_score is not None
    assert scores["test_score"] is None and scores["final_score"] is None
    assert scores["matched_skills"] == ["Python"]
    assert scores["missing_skills"] == ["SQL", "Tableau"]
    assert scores["job"]["requirements_list"] == ["SQL", "Python", "Tableau"]

    # The assessment must NOT start automatically after upload.
    assert pipeline["generated"] == 0
    assert client.get(f"/assessments/status/{w.aid}", headers=auth(w.cand)).json()["status"] == "not_started"
    assert client.get(f"/assessments/{w.aid}", headers=auth(w.cand)).status_code == 404

    started = w.c_post(f"/assessments/start/{w.aid}")
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "in_progress"
    assert 0 < body["remaining_seconds"] <= 30 * 60
    assert w.c_post(f"/assessments/start/{w.aid}").json()["assessment_id"] == body["assessment_id"]
    assert pipeline["generated"] == 1
    assert "correct_option_label" not in str(body)

    assert client.put(f"/assessments/progress/{w.aid}", headers=auth(w.cand), json={"answers": {"0": "A"}}).status_code == 200
    assert client.get(f"/assessments/{w.aid}", headers=auth(w.cand)).json()["draft_answers"] == {"0": "A"}

    submitted = w.c_post(f"/assessments/submit/{w.aid}", json=ALL_RIGHT)
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["test_score_percent"] == 100.0
    assert body["completed_at"] is not None
    assert body["ranking_status"] == "completed"
    expected = round(0.4 * 33.3 + 0.2 * experience_score + 0.4 * 100, 2)
    assert body["final_score"]["final_score"] == expected

    scores = w.hr_get(f"/candidates/{w.cid}/scores").json()
    assert scores["test_score"] == 100.0 and scores["final_score"] == expected
    assert w.c_post(f"/assessments/submit/{w.aid}", json={"answers": []}).status_code == 409
    assert w.c_post(f"/assessments/start/{w.aid}").status_code == 409

    hr_view = w.hr_get(f"/candidates/{w.cid}/assessment").json()
    assert hr_view["questions"][1]["candidate_answer"] == "B"
    assert hr_view["questions"][1]["correct_answer"] == "B"


def test_screening_failure_does_not_block_assessment(client, pipeline, monkeypatch):
    from app.agents import recruitment_graph
    monkeypatch.setattr(recruitment_graph, "run_screening_graph",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("simulated screening failure")))
    w = World(client, cand_email="fail@example.com")
    upload = w.upload()
    assert upload.status_code == 200
    assert upload.json()["screening_result"]["status"] == "failed"
    assert w.c_post(f"/assessments/start/{w.aid}").status_code == 200
    body = w.c_post(f"/assessments/submit/{w.aid}", json={"answers": [{"index": 0, "user_answer": "A"},
                                                                       {"index": 1, "user_answer": "C"}]}).json()
    assert body["test_score_percent"] == 50.0
    assert body["final_score"]["final_score"] is None
    assert body["ranking_status"] == "failed"
    assert w.hr_get(f"/candidates/{w.cid}/scores").json()["test_score"] == 50.0


def test_ranking_failure_keeps_completed_assessment(client, pipeline, monkeypatch):
    from app.agents import recruitment_graph
    monkeypatch.setattr(recruitment_graph, "run_final_ranking_graph",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("ranking exploded")))
    w = World(client, cand_email="rank@example.com")
    w.upload()
    w.c_post(f"/assessments/start/{w.aid}")
    body = w.c_post(f"/assessments/submit/{w.aid}", json=ALL_RIGHT).json()
    assert body["ranking_status"] == "failed" and "ranking exploded" in body["ranking_error"]
    assert body["final_score"]["test_score"] == 100.0 and body["final_score"]["final_score"] is None
    assert client.get(f"/assessments/status/{w.aid}", headers=auth(w.cand)).json()["status"] == "completed"


def test_reupload_updates_resume_and_rescreens(client, pipeline):
    from app.database import SessionLocal
    from app import models
    w = World(client, cand_email="reupload@example.com")
    assert w.upload().json()["screening_result"]["skill_score"] == 33.3
    pipeline["skills"] = "Python, SQL"
    assert w.upload().json()["screening_result"]["skill_score"] == 66.7
    pipeline["skills"] = "Python, SQL, Tableau"
    assert w.upload().json()["screening_result"]["skill_score"] == 100.0
    with SessionLocal() as db:
        assert db.query(models.Resume).filter(models.Resume.candidate_id == w.cid).count() == 1


def test_valid_zero_skill_score_is_not_null(client, pipeline):
    pipeline["skills"] = "Python, SQL, Tableau, Machine Learning, Pandas, NumPy, scikit-learn, REST APIs, Git"
    w = World(client, job=dict(JOB, title="ML Engineer", requirements="PyTorch, NLP"), cand_email="zero@example.com")
    w.upload()
    scores = w.hr_get(f"/candidates/{w.cid}/scores").json()
    assert scores["skill_score"] == 0.0
    assert scores["missing_skills"] == ["PyTorch", "NLP"]


def test_job_validation_and_verification_required(client):
    unverified = __import__("conftest").signup_hr(client, email="new@hr.com")
    assert client.post("/jobs", json=JOB, headers=auth(unverified)).status_code == 403
    hr = verified_hr(client)

    def post(**overrides):
        return client.post("/jobs", json={**JOB, **overrides}, headers=auth(hr))
    assert post(weight_skill=50, weight_experience=20, weight_test=20).status_code == 422
    assert post(weight_skill=None).status_code == 422
    assert post(weight_skill=40.5, weight_test=39.5).status_code == 422
    assert post(min_experience=-1).status_code == 422
    assert post(requirements=" ; ,\n ").status_code == 422
    assert post(requirements="Python; SQL\nTableau").status_code == 200


def test_resume_requires_unlock_for_hr(client, pipeline):
    w = World(client, cand_email="file@example.com")
    w.upload(content=b"%PDF-original-bytes")
    detail = w.hr_get(f"/candidates/{w.cid}").json()
    assert detail["contact_unlocked"] is False and "•" in detail["email"]
    assert w.hr_get(f"/candidates/{w.cid}/resume").status_code == 402
    before = client.get("/billing/summary", headers=auth(w.hr)).json()["balance"]
    r = client.post(f"/candidates/{w.cid}/unlock", headers=auth(w.hr))
    assert r.status_code == 200 and r.json()["balance"] == before - 10
    assert client.post(f"/candidates/{w.cid}/unlock", headers=auth(w.hr)).json()["charged"] == 0  # never twice
    inline = w.hr_get(f"/candidates/{w.cid}/resume")
    assert inline.status_code == 200 and inline.content == b"%PDF-original-bytes"
    assert w.hr_get(f"/candidates/{w.cid}").json()["email"] == "file@example.com"
    # The candidate can always see their own file.
    assert client.get(f"/candidates/{w.cid}/resume", headers=auth(w.cand)).status_code == 200
