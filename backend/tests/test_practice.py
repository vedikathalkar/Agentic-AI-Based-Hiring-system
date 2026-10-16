"""Practice zone: AI mock interview (offline interviewer) and mock assessment, end to end over HTTP."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("langgraph")

from conftest import auth, signup_candidate  # noqa: E402

ARRAY_SUM = "n=int(input());print(sum(map(int,input().split())))"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MOCK_INTERVIEW_ENGINE", "offline")


def test_mock_interview_follow_up_time_limits_and_report(client):
    tok = signup_candidate(client)
    r = client.post("/practice/interviews", headers=auth(tok), json={
        "role_title": "Data Analyst", "skills": ["SQL", "Python"], "interview_type": "mixed", "num_questions": 3, "mode": "interview"})
    assert r.status_code == 200, r.text
    iv = r.json()
    assert len(iv["plan"]) == 3 and iv["turns"][0]["status"] == "pending"
    assert iv["turns"][0]["time_limit_s"] in (60, 90, 120, 180, 240)            # per-question limit
    assert "points" not in iv["turns"][0] and "key_points" not in iv["turns"][0]  # hidden until answered
    iid = iv["interview_id"]

    iv = client.post(f"/practice/interviews/{iid}/begin", headers=auth(tok)).json()
    assert iv["turns"][0]["status"] == "active" and iv["turns"][0]["remaining_s"] > 0
    iv = client.post(f"/practice/interviews/{iid}/answer", headers=auth(tok), json={"answer": "not sure", "answer_mode": "text"}).json()
    first = iv["turns"][0]
    assert first["evaluation"]["score"] < 5 and first["key_points"]
    assert iv["turns"][1]["kind"] == "followup"                                    # the agent probes a vague answer

    for _ in range(6):
        if iv["status"] == "completed":
            break
        client.post(f"/practice/interviews/{iid}/begin", headers=auth(tok))
        iv = client.post(f"/practice/interviews/{iid}/answer", headers=auth(tok), json={
            "answer": "For example in my project I used SQL WHERE and GROUP BY with HAVING; as a result reports were 30% faster.",
            "answer_mode": "voice", "speaking_seconds": 20}).json()
    if iv["status"] != "completed":
        iv = client.post(f"/practice/interviews/{iid}/finish", headers=auth(tok)).json()
    assert iv["status"] == "completed" and 0 <= iv["overall_score"] <= 100
    assert iv["report"]["competencies"] and iv["report"]["time_notes"]
    other = signup_candidate(client, email="other@example.com")
    assert client.get(f"/practice/interviews/{iid}", headers=auth(other)).status_code == 404   # private


def test_mock_assessment_grades_mcq_and_code(client):
    tok = signup_candidate(client)
    r = client.post("/practice/assessments", headers=auth(tok), json={
        "role_title": "Backend Developer", "skills": ["Python", "SQL"], "num_mcq": 5, "num_coding": 1, "difficulty": "easy"})
    assert r.status_code == 200, r.text
    m = r.json()
    assert len(m["questions"]) == 6 and all("correct" not in q for q in m["questions"])   # no answer keys while running
    coding = next(q for q in m["questions"] if q["type"] == "coding")
    sample = client.post(f"/practice/assessments/{m['mock_id']}/run-code", headers=auth(tok),
                         json={"question_index": coding["index"], "language": "python", "source": ARRAY_SUM}).json()
    assert sample["total"] >= 1
    answers = {str(q["index"]): "A" for q in m["questions"] if q["type"] == "mcq"}
    code = {str(coding["index"]): {"language": "python", "source": ARRAY_SUM}}
    done = client.post(f"/practice/assessments/{m['mock_id']}/submit", headers=auth(tok), json={"answers": answers, "code": code}).json()
    assert done["status"] == "completed" and done["score"] is not None
    assert all("correct" in q for q in done["questions"] if q["type"] == "mcq")              # revealed after submit
    assert done["results"]["skills"] and done["results"]["recommendations"]
