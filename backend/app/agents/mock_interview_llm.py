"""Interviewer agent tools: question writing, answer evaluation and the final report.

Every function has two engines:
* "ai"      — Groq LLM with structured JSON output (agents/assessment_llm._call_json);
* "offline" — a built-in question bank and a transparent rubric scorer, used when
              GROQ_API_KEY is missing or the LLM call fails, so a mock interview
              never breaks (e.g. during a demo without internet).
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from pydantic import BaseModel, Field

# Seconds per question type and difficulty (easy, medium, hard).
TIME_LIMITS = {
    "concept": (60, 90, 120),
    "explain": (120, 180, 240),
    "behavioural": (120, 180, 180),
    "scenario": (240, 360, 480),
    "coding": (480, 720, 900),
    "followup": (60, 90, 120),
}
DIFFICULTIES = ("easy", "medium", "hard")
TYPE_LABELS = {"concept": "Concept", "explain": "Explain / compare", "behavioural": "Behavioural (STAR)",
               "scenario": "Scenario / design", "coding": "Coding", "followup": "Follow-up"}


def base_time_limit(qtype: str, difficulty: str) -> int:
    row = TIME_LIMITS.get(qtype, TIME_LIMITS["explain"])
    return row[DIFFICULTIES.index(difficulty) if difficulty in DIFFICULTIES else 1]


def clamp_time_limit(qtype: str, difficulty: str, suggested: Optional[int]) -> int:
    """The agent may stretch or shorten a limit, but only within 0.75x-1.5x of the table."""
    base = base_time_limit(qtype, difficulty)
    if not suggested:
        return base
    return int(max(base * 0.75, min(base * 1.5, int(suggested))) // 15 * 15) or base


def ai_available() -> bool:
    if os.getenv("MOCK_INTERVIEW_ENGINE", "auto").lower() == "offline":
        return False
    try:
        from . import assessment_llm
        return bool(assessment_llm.GROQ_API_KEY)
    except Exception:  # noqa: BLE001 - groq not installed etc.
        return False


# ---------------------------------------------------------------------------
# LLM schemas
# ---------------------------------------------------------------------------

class InterviewQuestion(BaseModel):
    question: str
    expected_points: List[str] = Field(description="3-5 short key points a strong answer covers")
    suggested_seconds: Optional[int] = None


class AnswerEvaluation(BaseModel):
    score: float = Field(description="0 to 10")
    feedback: str = Field(description="2-3 sentences, specific and encouraging")
    covered: List[str] = Field(default_factory=list, description="expected points the answer covered")
    missing: List[str] = Field(default_factory=list, description="expected points the answer missed")
    needs_follow_up: bool = False
    follow_up_question: Optional[str] = None
    star_situation: Optional[bool] = None
    star_task: Optional[bool] = None
    star_action: Optional[bool] = None
    star_result: Optional[bool] = None


class InterviewReport(BaseModel):
    summary: str
    strengths: List[str]
    improvements: List[str]
    study_topics: List[str]


_SYSTEM = """You are a friendly but rigorous technical interviewer running a PRACTICE interview for a job
candidate. Be specific, fair and encouraging. Never ask about or consider age, gender, religion, caste,
family, health, nationality or any other personal attribute. Return ONLY valid JSON for the schema."""


def _llm(prompt: str, schema, temperature: float = 0.5):
    from . import assessment_llm
    return assessment_llm._call_json(system_prompt=_SYSTEM, user_prompt=prompt, schema_model=schema,
                                     temperature=temperature)


# ---------------------------------------------------------------------------
# Offline question bank
# ---------------------------------------------------------------------------
# (type, question, [(point, [keywords...]), ...])
Q = tuple
BANK: dict[str, list[Q]] = {
    "python": [
        ("concept", "What is the difference between a list and a tuple in Python, and when would you use each?",
         [("lists are mutable, tuples immutable", ["mutable", "immutable", "change"]),
          ("tuples can be dict keys / hashable", ["hash", "key", "dictionary"]),
          ("use-case example", ["example", "coordinates", "record", "fixed"])]),
        ("explain", "Explain how Python manages memory, including garbage collection.",
         [("reference counting", ["reference count", "refcount", "references"]),
          ("cyclic garbage collector", ["cycle", "cyclic", "gc", "garbage collector"]),
          ("private heap / allocator", ["heap", "allocator", "pymalloc"])]),
        ("scenario", "A Python data-processing script has become very slow on a large file. How would you find and fix the bottleneck?",
         [("measure first with a profiler", ["profile", "cprofile", "timeit", "measure"]),
          ("streaming / chunking instead of loading all", ["chunk", "stream", "generator", "line by line"]),
          ("vectorise or use better data structures", ["numpy", "pandas", "vector", "set", "dict"]),
          ("parallelism if CPU bound", ["multiprocessing", "parallel", "concurrent"])]),
    ],
    "sql": [
        ("concept", "What is the difference between WHERE and HAVING in SQL?",
         [("WHERE filters rows before grouping", ["before", "rows", "where"]),
          ("HAVING filters groups after aggregation", ["after", "group", "aggregat"]),
          ("example with GROUP BY", ["group by", "count", "sum", "example"])]),
        ("explain", "Explain database indexes: how they speed up queries and what they cost.",
         [("B-tree / lookup structure", ["b-tree", "btree", "tree", "lookup"]),
          ("faster reads / avoids full scan", ["scan", "faster", "read"]),
          ("slower writes and extra storage", ["write", "insert", "storage", "space", "cost"])]),
        ("scenario", "A dashboard query that joins three large tables now takes 30 seconds. How would you speed it up?",
         [("read the query plan", ["explain", "plan", "analyze"]),
          ("add the right indexes", ["index"]),
          ("reduce data early / filter, select fewer columns", ["filter", "where", "columns", "limit"]),
          ("pre-aggregate or cache", ["materialized", "cache", "aggregate", "summary table"])]),
    ],
    "javascript": [
        ("concept", "What is the difference between let, const and var in JavaScript?",
         [("block vs function scope", ["block", "function scope", "scope"]),
          ("const cannot be reassigned", ["reassign", "const"]),
          ("hoisting / temporal dead zone", ["hoist", "temporal", "tdz"])]),
        ("explain", "Explain the JavaScript event loop and how async/await works on top of it.",
         [("single thread with call stack", ["single", "thread", "call stack"]),
          ("task / microtask queues", ["queue", "microtask", "macrotask", "callback"]),
          ("promises and await pause the async function", ["promise", "await", "async"])]),
    ],
    "react": [
        ("concept", "What are React hooks? Explain useState and useEffect.",
         [("state in function components", ["state", "usestate", "function component"]),
          ("side effects after render", ["side effect", "useeffect", "after render", "fetch"]),
          ("dependency array / cleanup", ["dependency", "cleanup", "array"])]),
        ("scenario", "A React page re-renders too often and feels slow. How would you diagnose and fix it?",
         [("measure with React Profiler / devtools", ["profiler", "devtools", "measure"]),
          ("memoisation: memo, useMemo, useCallback", ["memo", "usememo", "usecallback"]),
          ("stable keys / avoid new objects in props", ["key", "props", "reference"]),
          ("split state / virtualise long lists", ["virtual", "split", "state", "list"])]),
    ],
    "machine learning": [
        ("concept", "What is overfitting and how do you detect and prevent it?",
         [("good on training, poor on unseen data", ["training", "unseen", "test", "generalis", "generaliz"]),
          ("detect with validation / cross-validation", ["validation", "cross"]),
          ("regularisation, more data, simpler model, early stopping", ["regulari", "dropout", "early stopping", "more data", "simpler"])]),
        ("explain", "Explain precision, recall and F1, and when you would prefer recall over precision.",
         [("precision definition", ["precision", "false positive"]),
          ("recall definition", ["recall", "false negative"]),
          ("F1 harmonic mean", ["f1", "harmonic"]),
          ("example where recall matters (disease, fraud)", ["disease", "fraud", "cancer", "medical", "miss"])]),
        ("scenario", "Your model scores 95% accuracy offline but performs badly in production. What could be wrong?",
         [("data drift / distribution shift", ["drift", "distribution", "shift"]),
          ("data leakage in training", ["leak"]),
          ("class imbalance makes accuracy misleading", ["imbalance", "accuracy", "skew"]),
          ("monitor and retrain", ["monitor", "retrain"])]),
    ],
    "data analysis": [
        ("explain", "How would you clean a messy dataset before analysis?",
         [("handle missing values", ["missing", "null", "impute"]),
          ("remove duplicates / fix types", ["duplicate", "type", "format"]),
          ("detect outliers", ["outlier"]),
          ("document and validate", ["document", "validate", "check"])]),
        ("scenario", "Sign-ups dropped 20% last week. How would you investigate?",
         [("check data / tracking first", ["tracking", "data quality", "bug", "instrument"]),
          ("segment by channel, device, region", ["segment", "channel", "device", "region"]),
          ("compare with seasonality / releases", ["season", "release", "campaign", "change"]),
          ("form hypotheses and test", ["hypothes", "test", "experiment"])]),
    ],
    "java": [
        ("concept", "What is the difference between an interface and an abstract class in Java?",
         [("multiple interfaces vs single inheritance", ["multiple", "inherit", "extends", "implements"]),
          ("abstract class can hold state / constructors", ["state", "field", "constructor"]),
          ("default methods in interfaces", ["default"])]),
    ],
    "docker": [
        ("explain", "What is the difference between a Docker image and a container, and why use multi-stage builds?",
         [("image is a template, container a running instance", ["template", "instance", "running"]),
          ("layers / caching", ["layer", "cache"]),
          ("multi-stage keeps final image small", ["small", "size", "multi-stage", "build stage"])]),
    ],
    "statistics": [
        ("concept", "What does a p-value mean, and what does it not mean?",
         [("probability of data this extreme if null is true", ["null", "extreme", "probability"]),
          ("not the probability the hypothesis is true", ["not the probability", "not proof", "doesn't prove", "does not"]),
          ("threshold / significance level", ["0.05", "alpha", "significance"])]),
    ],
    "rest apis": [
        ("explain", "What makes an API RESTful, and how do you choose HTTP methods and status codes?",
         [("resources and URLs", ["resource", "url", "endpoint"]),
          ("methods GET/POST/PUT/DELETE and idempotency", ["get", "post", "put", "delete", "idempot"]),
          ("status codes 2xx/4xx/5xx", ["200", "201", "404", "400", "500", "status"]),
          ("stateless", ["stateless", "state"])]),
    ],
}
GENERIC = [
    ("concept", "What is {topic}, and what problem does it solve? Give an example.",
     [("clear definition of {topic}", ["{topic}", "is a", "means"]),
      ("the problem it solves", ["problem", "solve", "because", "helps"]),
      ("a concrete example", ["example", "for instance", "e.g", "project"])]),
    ("explain", "Explain how you have used {topic} in a project. What trade-offs did you face?",
     [("the project context", ["project", "built", "worked"]),
      ("how {topic} was used", ["{topic}", "used", "implemented"]),
      ("trade-offs or alternatives", ["trade", "instead", "alternative", "but", "however"]),
      ("result or lesson", ["result", "learned", "improved", "outcome"])]),
    ("scenario", "Something built with {topic} is failing in production. Walk me through how you would investigate and fix it.",
     [("reproduce and gather logs/metrics", ["log", "metric", "reproduce", "monitor"]),
      ("isolate the root cause", ["root cause", "isolate", "narrow", "debug"]),
      ("fix and verify with tests", ["fix", "test", "verify"]),
      ("prevent recurrence", ["prevent", "alert", "postmortem", "monitor"])]),
]
BEHAVIOURAL = [
    ("Teamwork", "Tell me about a time you worked with a teammate who had a very different working style. What did you do?"),
    ("Conflict", "Describe a disagreement you had with a colleague or teammate. How did you resolve it?"),
    ("Failure", "Tell me about a time something you worked on failed. What did you learn?"),
    ("Deadline", "Describe a time you had to deliver under a tight deadline. How did you manage it?"),
    ("Ownership", "Tell me about a time you took ownership of a problem nobody else was handling."),
    ("Learning", "Tell me about a time you had to learn a new technology quickly to finish a task."),
    ("Leadership", "Describe a situation where you led a group or influenced others without formal authority."),
    ("Communication", "Tell me about a time you had to explain something technical to a non-technical person."),
]
STAR_POINTS = [("Situation: set the scene", ["when", "situation", "project", "at my", "in my", "during", "while"]),
               ("Task: your responsibility or goal", ["task", "goal", "responsib", "needed to", "had to", "my role"]),
               ("Action: what YOU did, step by step", ["i decided", "i did", "i built", "i led", "i spoke", "i created",
                                                        "i used", "i organised", "i organized", "i proposed", "i talked", "i set up", "i "]),
               ("Result: outcome with numbers or lessons", ["result", "outcome", "improved", "reduced", "increased",
                                                             "%", "learned", "learnt", "delivered", "finally", "as a result"])]
FILLERS = ["um", "uh", "erm", "basically", "actually", "you know", "kind of", "sort of", "like"]


def _bank_for(topic: str) -> list[Q]:
    key = (topic or "").lower()
    if key in BANK:
        return BANK[key]
    for k in BANK:
        if k in key or key in k:
            return BANK[k]
    return [(t, q.replace("{topic}", topic), [(p.replace("{topic}", topic), [w.replace("{topic}", key) for w in kws])
                                              for p, kws in pts]) for t, q, pts in GENERIC]


def offline_question(slot: dict, used: set[str]) -> dict:
    qtype, topic, difficulty = slot["qtype"], slot["topic"], slot["difficulty"]
    if qtype == "behavioural":
        options = [b for b in BEHAVIOURAL if b[1] not in used] or BEHAVIOURAL
        comp, text = next((b for b in options if b[0] == topic), options[0])
        return {"question": text, "points": [{"text": p, "keywords": k} for p, k in STAR_POINTS], "competency": comp}
    bank = _bank_for(topic)
    pick = next((b for b in bank if b[0] == qtype and b[1] not in used), None) \
        or next((b for b in bank if b[1] not in used), bank[0])
    return {"question": pick[1], "points": [{"text": p, "keywords": k} for p, k in pick[2]]}


def ai_question(slot: dict, context: dict, used: list[str]) -> dict:
    kind = TYPE_LABELS.get(slot["qtype"], slot["qtype"])
    prompt = f"""Job: {context.get('job_title') or 'Software role'}
Job description: {(context.get('job_description') or '')[:1500]}
Candidate skills: {', '.join(context.get('candidate_skills', [])[:20]) or 'unknown'}
Write ONE {slot['difficulty']} "{kind}" interview question about: {slot['topic']}.
{"Use the STAR format (ask for a specific past situation)." if slot['qtype'] == 'behavioural' else ''}
Do not repeat: {' | '.join(used[-8:]) or 'none'}.
Give 3-5 expected_points a strong answer should cover, and suggested_seconds (time to answer out loud)."""
    q = _llm(prompt, InterviewQuestion, 0.7)
    points = [{"text": p, "keywords": _keywords(p)} for p in q.expected_points[:5]]
    if slot["qtype"] == "behavioural":
        points = [{"text": p, "keywords": k} for p, k in STAR_POINTS]
    return {"question": q.question.strip(), "points": points, "suggested_seconds": q.suggested_seconds}


def _keywords(point: str) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z+#.-]{3,}", point.lower())
             if w not in {"with", "that", "this", "when", "what", "they", "their", "from", "into", "about", "your", "should"}]
    return words[:6] or [point.lower()]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _has(text: str, kw: str) -> bool:
    kw = kw.lower()
    if kw.endswith(" ") or not re.match(r"^[a-z0-9]", kw):
        return kw in text
    return re.search(rf"(?<![a-z0-9]){re.escape(kw)}", text) is not None


def star_check(answer: str) -> dict:
    t = f" {answer.lower()} "
    names = ["situation", "task", "action", "result"]
    return {n: any(_has(t, k) for k in kws) for n, (_, kws) in zip(names, STAR_POINTS)}


def speech_metrics(answer: str, speaking_seconds: Optional[float]) -> dict:
    words = len(re.findall(r"\b\w+\b", answer or ""))
    low = f" {(answer or '').lower()} "
    fillers = {f: len(re.findall(rf"(?<![a-z]){re.escape(f)}(?![a-z])", low)) for f in FILLERS}
    fillers = {k: v for k, v in fillers.items() if v}
    out = {"words": words, "fillers": fillers, "filler_count": sum(fillers.values())}
    if speaking_seconds and speaking_seconds >= 5:
        out["wpm"] = round(words / (speaking_seconds / 60))
    return out


def offline_evaluate(turn: dict) -> dict:
    answer = (turn.get("answer") or "").strip()
    text = f" {answer.lower()} "
    words = len(answer.split())
    points = turn.get("points") or []
    covered = [p["text"] for p in points if any(_has(text, k) for k in p.get("keywords", []))]
    missing = [p["text"] for p in points if p["text"] not in covered]
    if not answer:
        return {"score": 0.0, "feedback": "No answer was given.", "covered": [], "missing": missing,
                "needs_follow_up": False, "engine": "offline"}
    coverage = len(covered) / len(points) if points else 0.5
    depth = 0 if words < 15 else 1 if words < 40 else 2 if words < 120 else 2.5
    example = 0.5 if re.search(r"for example|for instance|e\.g\.|such as|in my (last )?project|at my (last )?(job|internship)", text) else 0
    score = min(10.0, round(7 * coverage + depth + example, 1))
    star = None
    if turn.get("qtype") == "behavioural":
        star = star_check(answer)
        score = min(10.0, round(6 * sum(star.values()) / 4 + depth + example + (1 if words >= 80 else 0), 1))
    parts = []
    if covered:
        parts.append("Good: you covered " + "; ".join(c.split(":")[0].lower() for c in covered[:3]) + ".")
    if missing:
        parts.append("To improve, also cover " + "; ".join(m.split(":")[0].lower() for m in missing[:3]) + ".")
    if words < 40:
        parts.append("The answer is short — aim for 1–2 minutes with a concrete example.")
    elif not example and turn.get("qtype") != "coding":
        parts.append("Add a concrete example from your own work.")
    result = {"score": score, "feedback": " ".join(parts), "covered": covered, "missing": missing,
              "needs_follow_up": score < 5 and words < 60, "engine": "offline"}
    if star is not None:
        result["star"] = star
    return result


def ai_evaluate(turn: dict, context: dict) -> dict:
    points = "\n".join(f"- {p['text']}" for p in turn.get("points") or [])
    behavioural = turn.get("qtype") == "behavioural"
    prompt = f"""Job: {context.get('job_title') or 'Software role'}
Question ({TYPE_LABELS.get(turn.get('qtype'), '')}, {turn.get('difficulty')}): {turn['question']}
Expected key points:
{points}
Candidate answer ({turn.get('answer_mode') or 'text'}{', cut off by the time limit' if turn.get('timed_out') else ''}):
\"\"\"{(turn.get('answer') or '')[:6000]}\"\"\"
Score 0-10 for correctness, depth and clarity (a spoken transcript may contain small speech-to-text errors;
do not penalise those). List covered and missing expected points (use the exact point text).
needs_follow_up = true if the answer is vague, generic or lacks an example; then write ONE short follow_up_question.
{"Also set star_situation, star_task, star_action, star_result for the STAR structure." if behavioural else ''}"""
    e = _llm(prompt, AnswerEvaluation, 0.2)
    out = {"score": round(max(0.0, min(10.0, e.score)), 1), "feedback": e.feedback.strip(), "covered": e.covered,
           "missing": e.missing, "needs_follow_up": bool(e.needs_follow_up),
           "follow_up_question": (e.follow_up_question or "").strip() or None, "engine": "ai"}
    if behavioural:
        out["star"] = {"situation": bool(e.star_situation), "task": bool(e.star_task),
                       "action": bool(e.star_action), "result": bool(e.star_result)}
    return out


def coding_evaluate(turn: dict) -> dict:
    r = turn.get("code_result") or {}
    total, passed = r.get("total") or 0, r.get("passed") or 0
    if not (turn.get("answer") or "").strip():
        return {"score": 0.0, "feedback": "No code was submitted.", "covered": [], "missing": [], "engine": "tests"}
    score = round(10 * passed / total, 1) if total else 0.0
    status = (r.get("status") or "").replace("_", " ")
    fb = f"{passed} of {total} test cases passed ({status})."
    if r.get("error"):
        fb += " The code did not compile or crashed — check the error output."
    elif score < 10:
        fb += " Think about edge cases: empty input, negative numbers, very large values."
    else:
        fb += " All tests pass — be ready to explain its time and space complexity."
    return {"score": score, "feedback": fb, "covered": [], "missing": [], "engine": "tests",
            "needs_follow_up": score >= 7}


def offline_follow_up(turn: dict) -> str:
    if turn.get("qtype") == "coding":
        return "What is the time and space complexity of your solution, and how would you improve it?"
    if turn.get("qtype") == "behavioural":
        star = (turn.get("evaluation") or {}).get("star") or {}
        if not star.get("result"):
            return "What was the final outcome, and how did you measure it?"
        return "What exactly did YOU do in that situation, step by step?"
    missing = (turn.get("evaluation") or {}).get("missing") or []
    if missing:
        return f"Your answer didn't cover one key idea — {missing[0].split(':')[0].rstrip('.')}. Can you explain that part, with an example?"
    return f"Can you give a concrete example of {turn.get('topic')} from a project you worked on?"


def ai_report(context: dict, turns: list[dict]) -> dict:
    lines = []
    for t in turns:
        ev = t.get("evaluation") or {}
        lines.append(f"- [{t.get('qtype')}/{t.get('topic')}] Q: {t['question'][:200]} | score {ev.get('score')} | "
                     f"missing: {', '.join(ev.get('missing') or [])[:200]}")
    prompt = f"""Practice interview for: {context.get('job_title') or 'Software role'}
Results per question:
{chr(10).join(lines)}
Write a short summary (2-3 sentences), 2-4 strengths, 2-4 concrete improvements and 3-6 study topics."""
    r = _llm(prompt, InterviewReport, 0.4)
    return {"summary": r.summary, "strengths": r.strengths[:4], "improvements": r.improvements[:4],
            "study_topics": r.study_topics[:6]}
