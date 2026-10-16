"""Regression tests for the Sept-2026 fixes: persistent logins, document upload
validation, AI assessment builder (LangGraph) → publish → candidate attempt,
ATS report details and safe error messages."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("langgraph")

from conftest import PDF, auth, signup_candidate, signup_hr, verified_hr  # noqa: E402
from test_e2e_scores import JOB, World  # noqa: E402
from test_e2e_scores import pipeline  # noqa: E402,F401  (fixture)


# ---- auth persistence ---------------------------------------------------------------

def test_login_sessions_are_independent_and_survive(client):
    signup_candidate(client, email="a@example.com")
    t1 = client.post("/auth/candidate/login", json={"email": "a@example.com", "password": "secret1"}).json()["token"]
    t2 = client.post("/auth/candidate/login", json={"email": "a@example.com", "password": "secret1"}).json()["token"]
    # A second login (another tab/device) no longer logs the first one out.
    assert client.get("/auth/me", headers=auth(t1)).status_code == 200
    assert client.get("/auth/me", headers=auth(t2)).status_code == 200
    client.post("/auth/logout", headers=auth(t1))
    assert client.get("/auth/me", headers=auth(t1)).status_code == 401
    assert client.get("/auth/me", headers=auth(t2)).status_code == 200
    # Only a hash of the token is stored.
    from app.database import SessionLocal
    from app import models
    with SessionLocal() as db:
        assert db.query(models.AuthSession).filter(models.AuthSession.token_hash == t2).first() is None
        acc = db.query(models.CandidateAccount).filter_by(email="a@example.com").one()
        assert acc.password_hash != "secret1" and "secret1" not in acc.password_hash


def test_duplicate_signup_invalid_login_and_role_separation(client):
    signup_candidate(client, email="dup@example.com")
    r = client.post("/auth/candidate/signup", json={"name": "X", "email": "DUP@example.com", "password": "secret1"})
    assert r.status_code == 409
    assert client.post("/auth/candidate/login", json={"email": "dup@example.com", "password": "wrong!!"}).status_code == 401
    assert client.post("/auth/hr/login", json={"email": "dup@example.com", "password": "secret1"}).status_code == 401
    hr = signup_hr(client, email="dup@example.com")          # same email may exist as a separate HR account
    assert client.get("/auth/me", headers=auth(hr)).json()["role"] == "hr"
    assert client.post("/auth/candidate/signup", json={"name": "", "email": "x@example.com", "password": "secret1"}).status_code in (400, 422)


# ---- document upload -----------------------------------------------------------------

def test_company_document_validation_and_persistence(client):
    hr = signup_hr(client)
    bad = client.post("/hr/company/documents", headers=auth(hr), data={"doc_type": "id_proof"},
                      files={"file": ("id.exe", b"MZ....", "application/octet-stream")})
    assert bad.status_code == 400
    fake = client.post("/hr/company/documents", headers=auth(hr), data={"doc_type": "id_proof"},
                       files={"file": ("id.pdf", b"not really a pdf", "application/pdf")})
    assert fake.status_code == 400
    big = client.post("/hr/company/documents", headers=auth(hr), data={"doc_type": "id_proof"},
                      files={"file": ("id.pdf", PDF + b"0" * (2 * 1024 * 1024), "application/pdf")})
    assert big.status_code == 413
    ok = client.post("/hr/company/documents", headers=auth(hr), data={"doc_type": "id_proof"},
                     files={"file": ("my id.jpeg", b"\xff\xd8\xff\xe0" + b"0" * 64, "image/jpeg")})
    assert ok.status_code == 200, ok.text
    v = client.get("/hr/verification", headers=auth(hr)).json()      # persisted, tied to this HR
    assert v["status"] == "unverified"                               # uploading never verifies
    assert [d["file_name"] for d in v["company"]["documents"]] == ["my id.jpeg"]
    other = signup_hr(client, email="other@acme.com")
    doc_id = v["company"]["documents"][0]["document_id"]
    assert client.get(f"/hr/company/documents/{doc_id}", headers=auth(other)).status_code == 404


# ---- AI assessment builder -------------------------------------------------------------

def _fake_graph(**inputs):
    q = {"type": "mcq", "skill": "Python", "difficulty": inputs["difficulty"], "question": "2+2?",
         "options": [{"label": "A", "text": "4"}, {"label": "B", "text": "5"}], "correct_option_label": "A"}
    problem = {"title": "Echo", "skill": "Python", "statement": "Print the input.", "input_format": "a line",
               "output_format": "the line", "constraints": "len < 100", "examples": [{"input": "hi", "output": "hi"}],
               "tests": [{"input": "a", "output": "a"}, {"input": "b", "output": "b"}, {"input": "c", "output": "c"}],
               "reference_solution": "print(input())"}
    return {"question_set": {"skills_covered": ["Python"], "questions": [
        q, {"type": "coding", "skill": "Python", "difficulty": "easy", "question": "Echo"}]},
        "new_problems": [problem], "notes": []}


def test_ai_assessment_generate_edit_publish_and_candidate_attempt(client, pipeline, monkeypatch):
    from app.agents import assessment_graph
    monkeypatch.setattr(assessment_graph, "run_assessment_graph", _fake_graph)
    w = World(client)
    r = client.post("/hr/assessments/generate", headers=auth(w.hr), json={
        "job_id": w.job_id, "skills": ["Python"], "difficulty": "easy", "num_questions": 2,
        "assessment_type": "mixed", "time_limit_minutes": 15})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["status"] == "draft" and t["question_counts"] == {"mcq": 1, "short_answer": 0, "coding": 1}
    coding = t["questions"][1]
    assert coding["problem_id"] and coding["problem"]["title"] == "Echo"

    # Invalid edit is rejected, valid edit saved.
    qs = t["questions"]
    bad = [dict(qs[0], correct_option_label="Z"), qs[1]]
    assert client.put(f"/hr/assessments/templates/{t['template_id']}", headers=auth(w.hr), json={"questions": bad}).status_code == 422
    edited = [dict(qs[0], question="What is 2 + 2?"), qs[1]]
    r = client.put(f"/hr/assessments/templates/{t['template_id']}", headers=auth(w.hr), json={"questions": edited, "time_limit_minutes": 20})
    assert r.status_code == 200 and r.json()["questions"][0]["question"] == "What is 2 + 2?"
    assert client.post(f"/hr/assessments/templates/{t['template_id']}/publish", headers=auth(w.hr)).json()["status"] == "published"

    # Candidate gets the published questions (no per-candidate AI generation).
    assert w.upload().status_code == 200
    before = pipeline["generated"]
    r = w.c_post(f"/assessments/start/{w.aid}")
    assert r.status_code == 200, r.text
    assert pipeline["generated"] == before
    got = client.get(f"/assessments/{w.aid}", headers=auth(w.cand)).json()
    items = got.get("questions", got)
    assert items[0]["question"] == "What is 2 + 2?" and "correct_option_label" not in json.dumps(items)


def test_generation_failure_returns_safe_message_and_no_charge(client, monkeypatch):
    from app.agents import assessment_graph

    def boom(**_):
        raise RuntimeError("secret-internal-detail /etc/passwd")
    monkeypatch.setattr(assessment_graph, "run_assessment_graph", boom)
    hr = verified_hr(client)
    job_id = client.post("/jobs", json=JOB, headers=auth(hr)).json()["job_id"]
    before = client.get("/auth/me", headers=auth(hr)).json()["credits"]
    r = client.post("/hr/assessments/generate", headers=auth(hr), json={"job_id": job_id, "skills": ["SQL"]})
    assert r.status_code == 502 and "secret-internal-detail" not in r.text
    assert client.get("/auth/me", headers=auth(hr)).json()["credits"] == before


# ---- ATS -----------------------------------------------------------------------------

def test_ats_report_has_sections_preferred_skills_and_requirements(client):
    import io
    from docx import Document
    hr = verified_hr(client)
    job = dict(JOB, preferred_skills="Docker, Power BI", education_requirement="B.Tech in Computer Science", min_experience=2)
    job_id = client.post("/jobs", json=job, headers=auth(hr)).json()["job_id"]
    token = signup_candidate(client)
    doc = Document()
    for line in ["Neha", "neha@x.com", "Skills", "Python, SQL, Docker", "Experience",
                 "Analyst, Acme | Jan 2021 - Jan 2024", "Built dashboards, reduced time by 30%",
                 "Education", "B.Tech in Computer Science, 2020", "Projects", "Sales dashboard"]:
        doc.add_paragraph(line)
    buf = io.BytesIO(); doc.save(buf)
    r = client.post("/ats/check", headers=auth(token), data={"job_id": str(job_id)},
                    files={"file": ("cv.docx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 200, r.text   # free by default: no 402 for candidates
    rep = r.json()
    assert rep["preferred_skills"]["matched"] == ["Docker"] and rep["preferred_skills"]["missing"] == ["Power BI"]
    assert rep["education_match"]["meets"] is True
    assert rep["experience_match"]["required"] == 2
    assert "skills" in rep["section_details"]


def test_ats_rejects_unreadable_file_without_leaking_errors(client):
    token = signup_candidate(client)
    r = client.post("/ats/check", headers=auth(token), data={"job_description": "Python developer with SQL and cloud experience"},
                    files={"file": ("cv.pdf", b"%PDF-1.4 garbage", "application/pdf")})
    assert r.status_code == 422 and "Traceback" not in r.text


# ---- smart search + offer editor ----------------------------------------------------------

def test_job_search_endpoint_understands_natural_language(client):
    hr = verified_hr(client)
    client.post("/jobs", headers=auth(hr), json=dict(JOB, title="ML Engineer", location="Pune · Hybrid"))
    client.post("/jobs", headers=auth(hr), json=dict(JOB, title="Data Analyst", requirements="Excel, Tableau", location="Remote"))
    r = client.get("/jobs/search", params={"q": "pyhton jobs in pune"}).json()
    assert [c["label"] for c in r["understood"]] == ["Python", "Pune"]
    assert [j["title"] for j in r["results"]] == ["ML Engineer"] and r["results"][0]["relevance"] > 0
    assert client.get("/jobs/search", params={"q": "", "work_mode": "remote"}).json()["total"] == 1


def test_offer_custom_fields_validity_and_preview(client, pipeline):
    w = World(client)
    w.upload()
    client.patch(f"/candidates/applications/{w.aid}/status", headers=auth(w.hr), json={"status": "shortlisted"})
    client.post(f"/candidates/{w.cid}/unlock", headers=auth(w.hr))
    oid = client.post("/offers", headers=auth(w.hr), json={"application_id": w.aid}).json()["offer_id"]
    text = "Dear {{candidate_name}}, joining bonus {{joining_bonus}}, CTC {{ctc_amount}} from {{joining_date}}. Reply by {{acceptance_deadline}}."
    o = client.put(f"/offers/{oid}", headers=auth(w.hr), json={
        "template_content": text, "valid_days": 7,
        "fields": {"joining_bonus": "₹50,000", "ctc_amount": "₹9,00,000", "joining_date": "01 Jan 2027"}}).json()
    assert o["custom_fields"] == ["joining_bonus"] and o["valid_days"] == 7 and o["unresolved"] == []
    pdf = client.get(f"/offers/{oid}/preview.pdf", headers=auth(w.hr))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    sent = client.post(f"/offers/{oid}/send", headers=auth(w.hr)).json()
    assert sent["status"] == "sent" and "₹50,000" in sent["content"]
