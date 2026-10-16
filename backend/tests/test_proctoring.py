"""Proctored assessments, the stop-at-stage pipeline and the explained decision, through the API."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("langgraph")

from conftest import auth  # noqa: E402
from test_e2e_scores import ALL_RIGHT, World  # noqa: E402,F401
from test_e2e_scores import pipeline  # noqa: E402,F401  (fixture)

GOOD = {"proctoring": {"consent": True, "checks": {"rules": True, "camera": True, "microphone": True, "face": True},
                       "engine": "test"}}


@pytest.fixture
def proctored(monkeypatch):
    from app.services import config
    monkeypatch.setattr(config, "PROCTORING_ENABLED", True)
    monkeypatch.setattr(config, "PROCTOR_MAX_STRIKES", 3)


def _events(w, *kinds, answers=None):
    body = {"events": [{"kind": k} for k in kinds]}
    if answers:
        body["answers"] = answers
    return w.c_post(f"/assessments/{w.aid}/proctor/events", json=body)


def test_start_requires_consent_and_all_checks(client, pipeline, proctored):
    w = World(client); w.upload()
    assert w.c_post(f"/assessments/start/{w.aid}").status_code == 400
    partial = {"proctoring": {"consent": True, "checks": {"rules": True, "camera": True}}}
    r = w.c_post(f"/assessments/start/{w.aid}", json=partial)
    assert r.status_code == 400 and "microphone" in r.json()["detail"]
    assert w.c_post(f"/assessments/start/{w.aid}", json=GOOD).status_code == 200
    st = client.get(f"/assessments/status/{w.aid}", headers=auth(w.cand)).json()
    assert st["proctored"] and st["integrity"] == "clean" and st["max_strikes"] == 3


def test_strikes_are_counted_by_the_server_and_the_last_one_submits(client, pipeline, proctored):
    w = World(client); w.upload()
    w.c_post(f"/assessments/start/{w.aid}", json=GOOD)
    r = _events(w, "tab_hidden").json()
    assert r["strikes"] == 1 and not r["terminated"] and r["notices"][0]["strike_no"] == 1
    # blur + fullscreen exit fired by the same incident are not extra strikes
    r = _events(w, "window_blur", "fullscreen_exit").json()
    assert r["strikes"] == 1
    # an unknown kind sent by a tampered client is ignored; the server-only kinds can't be forged
    assert _events(w, "made_up", "consent").json()["strikes"] == 1
    assert _events(w, "no_face").json()["strikes"] == 2
    r = _events(w, "multiple_faces", answers={"0": "A", "1": "B"}).json()
    assert r["terminated"] and r["submitted"] and r["strikes"] == 3
    st = client.get(f"/assessments/status/{w.aid}", headers=auth(w.cand)).json()
    assert st["status"] == "completed" and st["integrity"] == "terminated" and st["test_score"] == 100.0
    report = w.hr_get(f"/assessments/{w.aid}/integrity").json()
    assert report["strikes"] == 3 and report["counts"]["tab_hidden"] == 1


def test_warning_events_do_not_cost_a_strike(client, pipeline, proctored):
    w = World(client); w.upload()
    w.c_post(f"/assessments/start/{w.aid}", json=GOOD)
    r = _events(w, "paste_attempt", "copy_attempt").json()
    assert r["strikes"] == 0 and r["integrity"] == "flagged"


def test_rejection_stops_the_pipeline_and_explains(client, pipeline):
    w = World(client); w.upload()
    w.c_post(f"/assessments/start/{w.aid}")
    w.c_post(f"/assessments/submit/{w.aid}", json={"answers": [{"index": 0, "user_answer": "B"}, {"index": 1, "user_answer": "A"}]})
    r = client.patch(f"/candidates/applications/{w.aid}/status", headers=auth(w.hr),
                     json={"status": "rejected", "note": "We need stronger SQL."})
    assert r.status_code == 200, r.text
    apps = client.get("/me/applications", headers=auth(w.cand)).json()
    pipe = apps[0]["pipeline"]
    assert pipe["outcome"]["state"] == "stopped" and pipe["outcome"]["stopped_at"] == "assessment"
    assert [s["state"] for s in pipe["stages"]][-3:] == ["stopped", "skipped", "skipped"]
    fb = client.get(f"/candidates/applications/{w.aid}/feedback", headers=auth(w.cand)).json()
    assert fb["tone"] == "negative" and fb["stopped_at"] == "assessment" and fb["hr_note"] == "We need stronger SQL."
    assert fb["gaps"] and fb["next_steps"]
    # another candidate cannot read it
    from conftest import signup_candidate
    other = signup_candidate(client, email="other@example.com")
    assert client.get(f"/candidates/applications/{w.aid}/feedback", headers=auth(other)).status_code == 404
