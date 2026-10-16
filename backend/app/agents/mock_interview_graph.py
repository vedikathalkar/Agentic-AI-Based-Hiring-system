"""LangGraph interviewer agent for practice (mock) interviews.

One compiled graph handles the whole conversation; each API call enters it with
a `phase` and the graph decides what happens next:

    START ─(phase)─┬─ start  → plan → ask_question → END
                   ├─ answer → evaluate ─(decide)─┬─ follow_up    → END
                   │                              ├─ ask_question → END
                   │                              └─ report       → END
                   └─ finish → report → END

* plan          — chooses topics from the job's skills (candidate's skill gaps first),
                  question types for the interview style, difficulty and time limits.
* ask_question  — writes the next question (Groq LLM, or the offline bank) with the
                  key points a strong answer covers and a per-question time limit.
* evaluate      — scores the answer 0–10 (LLM rubric / test results for code /
                  offline rubric) and checks STAR structure for behavioural answers.
* decide        — the agent's choice: probe with a follow-up when an answer is vague
                  (at most one per topic, two per interview, never when time is up),
                  otherwise move on, or finish.
* report        — overall score, competencies, time management and study plan.
"""

from __future__ import annotations

import logging
from datetime import datetime
from statistics import mean
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import mock_interview_llm as L

logger = logging.getLogger(__name__)
MAX_FOLLOW_UPS = 2
BEHAVIOURAL_TOPICS = ["Teamwork", "Conflict", "Failure", "Deadline", "Ownership", "Learning", "Leadership", "Communication"]


class InterviewState(TypedDict, total=False):
    phase: str                      # start | answer | finish
    context: Dict[str, Any]         # job_title, job_description, skills, candidate_skills, gaps, coding_pool
    config: Dict[str, Any]          # interview_type, difficulty, num_questions, mode
    plan: List[Dict[str, Any]]
    turns: List[Dict[str, Any]]
    slot_index: int
    followups_used: int
    force_finish: bool
    engine: str
    report: Optional[Dict[str, Any]]
    decision: str


def _ai() -> bool:
    return L.ai_available()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def plan_node(state: InterviewState) -> InterviewState:
    cfg, ctx = state["config"], state["context"]
    n = int(cfg.get("num_questions") or 5)
    kind, difficulty = cfg.get("interview_type", "mixed"), cfg.get("difficulty", "medium")
    gaps = [s for s in ctx.get("gaps", []) if s]
    skills = list(dict.fromkeys(gaps + [s for s in ctx.get("skills", []) if s])) or ["problem solving"]
    coding_pool = ctx.get("coding_pool") or []

    if kind == "behavioural":
        types = ["behavioural"] * n
    else:
        tech_cycle = ["concept", "explain", "scenario"]
        n_beh = 0 if kind == "technical" else max(1, round(n / 3))
        n_code = 1 if (coding_pool and n >= (4 if kind == "technical" else 5)) else 0
        n_tech = n - n_beh - n_code
        types = [tech_cycle[i % 3] for i in range(n_tech)]
        # interleave: behavioural questions spread through the interview, coding near the end
        for i in range(n_beh):
            types.insert(min(len(types), 1 + i * 3), "behavioural")
        if n_code:
            types.insert(max(1, len(types) - 1), "coding")
    plan, t_i, b_i = [], 0, 0
    for i, qtype in enumerate(types):
        if qtype == "behavioural":
            topic = BEHAVIOURAL_TOPICS[b_i % len(BEHAVIOURAL_TOPICS)]; b_i += 1
        elif qtype == "coding":
            topic = coding_pool[0]["title"]
        else:
            topic = skills[t_i % len(skills)]; t_i += 1
        # Warm up with an easier first question.
        d = difficulty if i else {"hard": "medium", "medium": "easy"}.get(difficulty, difficulty)
        plan.append({"slot": i, "qtype": qtype, "topic": topic, "difficulty": d,
                     "reason": "skill gap for this role" if topic in gaps else ("behavioural competency" if qtype == "behavioural" else "core skill for this role")})
    return {"plan": plan, "slot_index": 0, "followups_used": 0, "turns": []}


def ask_question_node(state: InterviewState) -> InterviewState:
    turns = list(state.get("turns", []))
    slot = state["plan"][state["slot_index"]]
    ctx = state["context"]
    used = {t["question"] for t in turns}
    engine = "offline"
    if slot["qtype"] == "coding":
        prob = (ctx.get("coding_pool") or [{}])[0]
        q = {"question": f"Solve “{prob.get('title')}”. Talk through your approach in comments, run the sample tests, then submit.",
             "points": [], "problem_id": prob.get("problem_id")}
        engine = "tests"
    else:
        q = None
        if _ai():
            try:
                q = L.ai_question(slot, ctx, list(used))
                engine = "ai"
            except Exception:  # noqa: BLE001
                logger.warning("AI question generation failed; using the offline bank", exc_info=True)
        if q is None:
            q = L.offline_question(slot, used)
    limit = L.clamp_time_limit(slot["qtype"], slot["difficulty"], q.get("suggested_seconds"))
    turns.append({
        "index": len(turns), "slot": slot["slot"], "kind": "question", "qtype": slot["qtype"], "topic": slot["topic"],
        "difficulty": slot["difficulty"], "question": q["question"], "points": q.get("points", []),
        "problem_id": q.get("problem_id"), "competency": q.get("competency"), "time_limit_s": limit,
        "status": "pending", "engine": engine, "created_at": datetime.utcnow().isoformat(),
    })
    return {"turns": turns, "engine": "ai" if engine == "ai" else state.get("engine", "offline")}


def evaluate_node(state: InterviewState) -> InterviewState:
    turns = list(state["turns"])
    turn = dict(turns[-1])
    if turn.get("status") == "skipped":
        ev = {"score": 0.0, "feedback": "Skipped.", "covered": [], "missing": [p["text"] for p in turn.get("points", [])],
              "engine": "none"}
    elif turn["qtype"] == "coding":
        ev = L.coding_evaluate(turn)
    else:
        ev = None
        if _ai() and (turn.get("answer") or "").strip():
            try:
                ev = L.ai_evaluate(turn, state["context"])
            except Exception:  # noqa: BLE001
                logger.warning("AI evaluation failed; using the offline rubric", exc_info=True)
        if ev is None:
            ev = L.offline_evaluate(turn)
    turn["evaluation"] = ev
    turns[-1] = turn
    return {"turns": turns}


def decide(state: InterviewState) -> str:
    turn = state["turns"][-1]
    ev = turn.get("evaluation") or {}
    is_main = turn.get("kind") == "question"
    slot_has_follow = any(t["slot"] == turn["slot"] and t["kind"] == "followup" for t in state["turns"])
    wants_probe = ev.get("needs_follow_up") and turn.get("status") == "answered" and not turn.get("timed_out")
    if (not state.get("force_finish") and is_main and wants_probe and not slot_has_follow
            and state.get("followups_used", 0) < MAX_FOLLOW_UPS):
        return "follow_up"
    if state.get("force_finish") or state["slot_index"] + 1 >= len(state["plan"]):
        return "report"
    return "next"


def follow_up_node(state: InterviewState) -> InterviewState:
    turns = list(state["turns"])
    base = turns[-1]
    text = (base.get("evaluation") or {}).get("follow_up_question") or L.offline_follow_up(base)
    limit = L.clamp_time_limit("followup", base["difficulty"], None)
    turns.append({
        "index": len(turns), "slot": base["slot"], "kind": "followup", "qtype": "followup" if base["qtype"] != "behavioural" else "behavioural",
        "topic": base["topic"], "difficulty": base["difficulty"], "question": text,
        "points": base.get("points", []) if base["qtype"] == "behavioural" else
                  [{"text": m, "keywords": L._keywords(m)} for m in (base.get("evaluation") or {}).get("missing", [])[:3]],
        "time_limit_s": limit, "status": "pending", "engine": base.get("engine"), "follow_up_of": base["index"],
        "created_at": datetime.utcnow().isoformat(),
    })
    return {"turns": turns, "followups_used": state.get("followups_used", 0) + 1, "decision": "follow_up"}


def next_slot_node(state: InterviewState) -> InterviewState:
    return {"slot_index": state["slot_index"] + 1, "decision": "next"}


def _slot_scores(turns: list[dict]) -> dict[int, float]:
    out: dict[int, float] = {}
    for slot in sorted({t["slot"] for t in turns}):
        main = next((t for t in turns if t["slot"] == slot and t["kind"] == "question"), None)
        if main is None or main.get("status") == "pending":
            continue
        s = (main.get("evaluation") or {}).get("score") or 0.0
        follow = next((t for t in turns if t["slot"] == slot and t["kind"] == "followup" and t.get("evaluation")), None)
        if follow:
            s = max(s, round((s + follow["evaluation"].get("score", 0)) / 2, 1))   # a good follow-up can lift it
        out[slot] = s
    return out


def report_node(state: InterviewState) -> InterviewState:
    turns = [t for t in state["turns"] if t.get("status") != "pending"]
    scores = _slot_scores(turns)
    overall = round(mean(scores.values()) * 10, 1) if scores else 0.0
    mains = [t for t in turns if t["kind"] == "question"]

    # Competencies: each technical topic, plus behavioural, problem solving and communication.
    comp: dict[str, list[float]] = {}
    for t in mains:
        s = scores.get(t["slot"])
        if s is None:
            continue
        key = "Behavioural (STAR)" if t["qtype"] == "behavioural" else ("Coding" if t["qtype"] == "coding" else t["topic"])
        comp.setdefault(key, []).append(s)
        if t["qtype"] in ("scenario", "coding"):
            comp.setdefault("Problem solving", []).append(s)
    spoken = [t for t in turns if t.get("speech") and t.get("answer_mode") == "voice"]
    written = [t for t in turns if t.get("status") == "answered" and t["qtype"] != "coding"]
    if written:
        def clarity(t):
            words = (t.get("speech") or {}).get("words") or len((t.get("answer") or "").split())
            fill = (t.get("speech") or {}).get("filler_count", 0)
            base = 4 if words < 25 else 7 if words < 60 else 9
            return max(0.0, base - min(3, fill / 3))
        comp["Communication"] = [clarity(t) for t in written]
    competencies = [{"name": k, "score": round(mean(v) * 10)} for k, v in comp.items()]
    competencies.sort(key=lambda c: (c["name"] in ("Communication", "Problem solving"), -c["score"]))

    # Time management notes (separate from the score).
    notes = []
    answered = [t for t in turns if t.get("status") == "answered"]
    timed_out = [t for t in answered if t.get("timed_out")]
    if len(timed_out) >= 2:
        notes.append(f"{len(timed_out)} answers hit the time limit — outline your answer first, then add detail.")
    short_beh = [t for t in answered if t["qtype"] == "behavioural" and t.get("time_used_s", 0) < 0.3 * t["time_limit_s"]]
    if short_beh:
        notes.append("Behavioural answers were very short — give a fuller STAR story (about 1.5–2 minutes).")
    over = [t for t in answered if t.get("overrun_s", 0) > 0]
    if over and state["config"].get("mode") == "practice":
        notes.append(f"You went over the limit on {len(over)} question(s); interview mode would have submitted automatically.")
    if not notes and answered:
        notes.append("Good pacing — your answers fit comfortably within the time limits.")
    wpm = [t["speech"]["wpm"] for t in spoken if t["speech"].get("wpm")]
    fillers = sum((t.get("speech") or {}).get("filler_count", 0) for t in spoken)
    speaking = None
    if wpm:
        avg = round(mean(wpm))
        speaking = {"wpm": avg, "fillers": fillers,
                    "note": "Comfortable pace." if 110 <= avg <= 170 else ("A little fast — slow down and pause between points." if avg > 170 else "A little slow — practise to sound more fluent.")}

    # Narrative: LLM when available, otherwise rule-based.
    weak = [c["name"] for c in competencies if c["score"] < 60 and c["name"] not in ("Communication",)]
    strong = [c["name"] for c in competencies if c["score"] >= 75]
    missing = [m for t in mains if t["qtype"] not in ("behavioural", "coding")
               for m in (t.get("evaluation") or {}).get("missing", [])][:8]
    narrative = None
    if _ai() and mains:
        try:
            narrative = L.ai_report(state["context"], turns)
        except Exception:  # noqa: BLE001
            logger.warning("AI report failed; using the rule-based summary", exc_info=True)
    if narrative is None:
        level = "strong" if overall >= 75 else "solid" if overall >= 55 else "developing"
        narrative = {
            "summary": f"A {level} practice interview for {state['context'].get('job_title') or 'this role'}: "
                       f"{len([t for t in mains if t.get('status') == 'answered'])} of {len(state['plan'])} questions answered, overall {overall:.0f}/100.",
            "strengths": [f"Confident on {s}" for s in strong[:3]] or ["You attempted every question — keep practising to build depth."],
            "improvements": ([f"Strengthen {w}" for w in weak[:3]] + (["Use the STAR structure: situation, task, action, result"]
                                                                      if any(t["qtype"] == "behavioural" and scores.get(t["slot"], 10) < 6 for t in mains) else []))
                            or ["Add concrete examples and numbers from your own projects"],
            "study_topics": list(dict.fromkeys(weak + [m.split(":")[0] for m in missing]))[:6],
        }
    report = {"overall_score": overall, "competencies": competencies, "time_notes": notes, "speaking": speaking,
              "answered": len([t for t in mains if t.get("status") == "answered"]), "planned": len(state["plan"]),
              "skipped": len([t for t in mains if t.get("status") == "skipped"]), **narrative}
    return {"report": report, "decision": "report",
            "turns": [t for t in state["turns"] if t.get("status") != "pending"]}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _entry(state: InterviewState) -> str:
    return {"start": "plan", "answer": "evaluate", "finish": "report"}[state["phase"]]


def build_mock_interview_graph():
    g = StateGraph(InterviewState)
    g.add_node("plan", plan_node)
    g.add_node("ask_question", ask_question_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("follow_up", follow_up_node)
    g.add_node("next_slot", next_slot_node)
    g.add_node("report", report_node)
    g.add_conditional_edges(START, _entry, {"plan": "plan", "evaluate": "evaluate", "report": "report"})
    g.add_edge("plan", "ask_question")
    g.add_conditional_edges("evaluate", decide, {"follow_up": "follow_up", "next": "next_slot", "report": "report"})
    g.add_edge("next_slot", "ask_question")
    g.add_edge("ask_question", END)
    g.add_edge("follow_up", END)
    g.add_edge("report", END)
    return g.compile()


_GRAPH = None


def run(state: InterviewState) -> InterviewState:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_mock_interview_graph()
    return _GRAPH.invoke(state)
