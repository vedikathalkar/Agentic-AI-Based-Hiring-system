"""
Proctoring (the invigilation agent's server side).

The browser watches the candidate (camera, microphone, tab focus, full screen) and reports what it sees.
This module is the authority on what counts: it records every event, decides which ones are strikes,
de-duplicates one incident that fires several browser events, and ends the assessment when the strike
limit is reached — so tampering with the front-end can't raise the limit or hide a strike it reported.

    info      recorded for the hiring team, no penalty (consent, resume after refresh, copy attempts ...)
    warning   recorded and shown to the candidate, no strike
    strike    counts toward the limit (PROCTOR_MAX_STRIKES); the last one ends the assessment

Limits worth knowing: this is browser-based proctoring. It deters and documents; it cannot see a second
device or a person off-camera, and a determined attacker controlling their own browser can withhold events.
The missing-heartbeat check ("monitoring_gap") is what surfaces that.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from .. import models
from . import config

logger = logging.getLogger(__name__)

# kind -> (severity, message shown to the candidate)
KINDS: dict[str, tuple[str, str]] = {
    "tab_hidden": ("strike", "You left the assessment tab."),
    "window_blur": ("strike", "The assessment window lost focus."),
    "fullscreen_exit": ("strike", "You exited full screen."),
    "no_face": ("strike", "Your face was not visible to the camera."),
    "multiple_faces": ("strike", "More than one person was detected."),
    "looking_away": ("strike", "You looked away from the screen for too long."),
    "loud_audio": ("strike", "Sustained speech or noise was detected."),
    "camera_lost": ("strike", "The camera stopped working."),
    "mic_lost": ("strike", "The microphone stopped working."),
    "screen_extended": ("strike", "A second display is connected."),
    "left_assessment": ("strike", "You left the assessment page."),
    "copy_attempt": ("warning", "Copying is disabled during the assessment."),
    "paste_attempt": ("warning", "Pasting is disabled during the assessment."),
    "context_menu": ("warning", "The right-click menu is disabled during the assessment."),
    "devtools_attempt": ("warning", "Developer tools are not allowed during the assessment."),
    "monitoring_gap": ("warning", "Monitoring was interrupted."),
    "consent": ("info", "Candidate accepted the proctoring rules."),
    "precheck_passed": ("info", "Camera, microphone and face check passed."),
    "session_started": ("info", "Proctored session started."),
    "session_resumed": ("info", "Candidate returned to the assessment after leaving the page."),
}
FOCUS_GROUP = {"tab_hidden", "window_blur", "fullscreen_exit"}   # one incident often fires all three
FOCUS_DEDUPE_SECONDS = 12
SAME_KIND_DEDUPE_SECONDS = 8
HEARTBEAT_GAP_SECONDS = 60
MAX_SNAPSHOT_CHARS = 40_000
MAX_EVENTS_PER_CALL = 20


def enabled() -> bool:
    return bool(config.PROCTORING_ENABLED)


def max_strikes() -> int:
    return int(config.PROCTOR_MAX_STRIKES)


def on_start(db, assessment: models.Assessment, payload: Optional[dict]) -> None:
    """Record consent and the pre-exam check when the candidate starts a proctored assessment."""
    if not enabled() or assessment.proctored:
        return
    now = datetime.utcnow()
    assessment.proctored = True
    assessment.integrity = "clean"
    assessment.strikes = 0
    assessment.proctor_consent_at = now
    assessment.last_seen = now
    checks = {k: bool(v) for k, v in ((payload or {}).get("checks") or {}).items()}
    assessment.precheck = json.dumps({"checks": checks, "engine": (payload or {}).get("engine"),
                                      "user_agent": ((payload or {}).get("user_agent") or "")[:200]})
    db.add(models.ProctorEvent(assessment_id=assessment.assessment_id, kind="consent", severity="info",
                               message=KINDS["consent"][1], at=now))
    db.add(models.ProctorEvent(assessment_id=assessment.assessment_id, kind="precheck_passed", severity="info",
                               message=KINDS["precheck_passed"][1], meta=json.dumps(checks), at=now))
    db.commit()


def _recent(db, assessment_id: int, kinds: set[str], since: datetime, severity: Optional[str] = None):
    q = db.query(models.ProctorEvent).filter(models.ProctorEvent.assessment_id == assessment_id,
                                             models.ProctorEvent.kind.in_(kinds), models.ProctorEvent.at >= since)
    if severity:
        q = q.filter(models.ProctorEvent.severity == severity)
    return q.first()


def record(db, assessment: models.Assessment, events: list[dict[str, Any]], now: Optional[datetime] = None) -> dict:
    """Store reported events, apply the strike rules and report the result. Returns
    {strikes, max_strikes, terminated, notices:[{kind, severity, message, strike_no}]}."""
    now = now or datetime.utcnow()
    notices: list[dict] = []
    if not assessment.proctored or assessment.completed_at is not None:
        return _state(assessment, notices)

    # Monitoring gap: the browser stopped reporting for too long while the test was open.
    if assessment.last_seen and now - assessment.last_seen > timedelta(seconds=HEARTBEAT_GAP_SECONDS):
        gap = int((now - assessment.last_seen).total_seconds())
        db.add(models.ProctorEvent(assessment_id=assessment.assessment_id, kind="monitoring_gap", severity="warning",
                                   message=f"No monitoring signal for {gap}s.", meta=json.dumps({"seconds": gap}), at=now))
        notices.append({"kind": "monitoring_gap", "severity": "warning", "message": KINDS["monitoring_gap"][1]})
    assessment.last_seen = now

    limit = max_strikes()
    for ev in (events or [])[:MAX_EVENTS_PER_CALL]:
        kind = str(ev.get("kind") or "")
        if kind not in KINDS or kind in ("consent", "precheck_passed", "session_started"):
            continue                                             # the server decides these, not the browser
        severity, message = KINDS[kind]
        meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else None
        if severity == "strike":
            same = _recent(db, assessment.assessment_id, {kind}, now - timedelta(seconds=SAME_KIND_DEDUPE_SECONDS), "strike")
            group = kind in FOCUS_GROUP and _recent(db, assessment.assessment_id, FOCUS_GROUP,
                                                     now - timedelta(seconds=FOCUS_DEDUPE_SECONDS), "strike")
            if same or group:
                severity = "info"                                 # same incident as a strike just counted
        strike_no = None
        if severity == "strike":
            assessment.strikes = (assessment.strikes or 0) + 1
            strike_no = assessment.strikes
        snap = ev.get("snapshot")
        row = models.ProctorEvent(
            assessment_id=assessment.assessment_id, kind=kind, severity=severity, message=message, strike_no=strike_no,
            meta=json.dumps(meta) if meta else None, at=now,
            snapshot=snap if (severity == "strike" and isinstance(snap, str) and snap.startswith("data:image/")
                              and len(snap) <= MAX_SNAPSHOT_CHARS) else None)
        db.add(row)
        db.flush()                                              # so the next event in this batch sees it
        if severity in ("strike", "warning"):
            notices.append({"kind": kind, "severity": severity, "message": message, "strike_no": strike_no})
        if (assessment.strikes or 0) >= limit:
            break

    if (assessment.strikes or 0) >= limit:
        assessment.integrity = "terminated"
    elif (assessment.strikes or 0) > 0 or any(n["severity"] == "warning" for n in notices):
        if assessment.integrity != "terminated":
            assessment.integrity = "flagged"
    db.commit()
    return _state(assessment, notices)


def heartbeat(db, assessment: models.Assessment, now: Optional[datetime] = None) -> dict:
    return record(db, assessment, [], now)


def _state(a: models.Assessment, notices: list[dict]) -> dict:
    return {"strikes": a.strikes or 0, "max_strikes": max_strikes(), "terminated": a.integrity == "terminated",
            "integrity": a.integrity, "notices": notices}


def public_status(a: Optional[models.Assessment]) -> dict:
    """The proctoring fields included in the assessment status payload."""
    return {"proctoring_enabled": enabled(), "proctored": bool(a and a.proctored), "integrity": (a.integrity if a and a.proctored else None),
            "strikes": (a.strikes or 0) if a else 0, "max_strikes": max_strikes()}


def report(db, a: models.Assessment, with_snapshots: bool = True) -> dict:
    rows = (db.query(models.ProctorEvent).filter(models.ProctorEvent.assessment_id == a.assessment_id)
            .order_by(models.ProctorEvent.at, models.ProctorEvent.event_id).all())
    counts: dict[str, int] = {}
    for r in rows:
        if r.severity in ("strike", "warning"):
            counts[r.kind] = counts.get(r.kind, 0) + 1
    try:
        precheck = json.loads(a.precheck) if a.precheck else None
    except ValueError:
        precheck = None
    return {
        "proctored": bool(a.proctored), "integrity": a.integrity if a.proctored else "unmonitored",
        "strikes": a.strikes or 0, "max_strikes": max_strikes(), "consent_at": a.proctor_consent_at,
        "precheck": precheck, "counts": counts,
        "events": [{"event_id": r.event_id, "kind": r.kind, "severity": r.severity, "message": r.message,
                    "strike_no": r.strike_no, "at": r.at, "meta": _loads(r.meta),
                    "snapshot": r.snapshot if with_snapshots else None} for r in rows],
    }


def _loads(v):
    try:
        return json.loads(v) if v else None
    except ValueError:
        return None
