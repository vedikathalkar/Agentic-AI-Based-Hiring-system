"""LangGraph agent that drafts an assessment for HR review.

    START → plan → generate_mcq → generate_coding → validate_coding ─┐
                                        ▲                           │ retry once if a
                                        └───────────────────────────┤ problem failed
                                                                    ▼
                                                                assemble → END

* plan            – splits the requested question count by type (mcq | coding | mixed).
* generate_mcq    – Groq LLM writes the MCQs (assessment_llm.generate_mcqs).
* generate_coding – Groq LLM writes stdin/stdout problems + a Python reference solution.
* validate_coding – runs each reference solution in the code sandbox on every test.
                    Expected outputs are taken from the *executed* reference solution
                    (not from the LLM's text), and a problem is rejected if the solution
                    crashes/times out or disagrees with most of the LLM's own outputs.
* assemble        – builds a GeneratedQuestionSet. Coding slots that still failed are
                    filled from the verified problem bank and reported in ``notes``.

Nothing here writes to the database; the route persists the draft for HR to edit.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import assessment_llm
from .assessment_llm import GeneratedQuestion, GeneratedQuestionSet, QuestionType

logger = logging.getLogger(__name__)

MAX_CODING = 5
MAX_CODING_ATTEMPTS = 2          # first try + one retry


class AssessmentGraphState(TypedDict, total=False):
    # input
    job_title: str
    job_description: str
    skills: List[str]
    difficulty: str
    num_questions: int
    assessment_type: str             # mcq | coding | mixed
    fallback_problems: List[Dict[str, Any]]   # verified bank problems {problem_id,title,difficulty,tags}
    # working
    mcq_count: int
    coding_count: int
    coding_attempts: int
    mcqs: List[Dict[str, Any]]
    coding_candidates: List[Dict[str, Any]]
    valid_coding: List[Dict[str, Any]]
    notes: List[str]
    # output
    question_set: Dict[str, Any]
    new_problems: List[Dict[str, Any]]


def plan_node(state: AssessmentGraphState) -> AssessmentGraphState:
    n = max(1, int(state.get("num_questions") or 10))
    kind = state.get("assessment_type") or "mixed"
    if kind == "mcq":
        mcq, coding = n, 0
    elif kind == "coding":
        mcq, coding = 0, min(n, MAX_CODING)
    else:
        coding = min(MAX_CODING, max(1, round(n * 0.3))) if n >= 2 else 0
        mcq = n - coding
    notes = []
    if kind == "coding" and n > MAX_CODING:
        notes.append(f"Coding assessments are limited to {MAX_CODING} problems; generated {MAX_CODING}.")
    return {"mcq_count": mcq, "coding_count": coding, "coding_attempts": 0, "mcqs": [],
            "coding_candidates": [], "valid_coding": [], "notes": notes}


def generate_mcq_node(state: AssessmentGraphState) -> AssessmentGraphState:
    count = state.get("mcq_count", 0)
    if count <= 0:
        return {}
    result = assessment_llm.generate_mcqs(state.get("job_title", ""), state.get("job_description", ""),
                                          state.get("skills", []), state.get("difficulty", "medium"), count)
    mcqs = []
    for q in result.questions:
        labels = [o.label for o in (q.options or [])]
        if q.type != QuestionType.MCQ or len(labels) < 2 or q.correct_option_label not in labels:
            continue   # malformed MCQ from the model: drop it rather than ship a broken question
        q.difficulty = state.get("difficulty", q.difficulty)
        mcqs.append(q.model_dump(mode="json"))
    notes = list(state.get("notes", []))
    if len(mcqs) < count:
        notes.append(f"The AI returned {len(mcqs)} valid MCQs of {count} requested; add or regenerate questions if needed.")
    return {"mcqs": mcqs[:count], "notes": notes}


def generate_coding_node(state: AssessmentGraphState) -> AssessmentGraphState:
    need = state.get("coding_count", 0) - len(state.get("valid_coding", []))
    attempts = state.get("coding_attempts", 0) + 1
    if need <= 0:
        return {"coding_attempts": attempts, "coding_candidates": []}
    avoid = [p["title"] for p in state.get("valid_coding", [])]
    candidates, notes = [], list(state.get("notes", []))
    for i in range(need):
        skills = state.get("skills", [])[i % len(state.get("skills", [])):] + state.get("skills", [])[: i % len(state.get("skills", []))]
        try:
            p = assessment_llm.generate_coding_problem(state.get("job_title", ""), skills, state.get("difficulty", "medium"),
                                                       avoid + [c["title"] for c in candidates])
            candidates.append(p.model_dump(mode="json"))
        except Exception:  # noqa: BLE001
            logger.warning("Coding problem generation failed", exc_info=True)
    return {"coding_attempts": attempts, "coding_candidates": candidates, "notes": notes}


def _validate_problem(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from ..services import code_runner
    tests = [{"input": t["input"], "output": ""} for t in p.get("tests", []) + p.get("examples", [])]
    if len(tests) < 3 or not code_runner.is_available("python"):
        return None
    report = code_runner.execute("python", p["reference_solution"], tests, time_limit_ms=2000)
    if report.status in ("compile_error", "error") or len(report.tests) != len(tests):
        return None
    outs = []
    for t in report.tests:
        if t.status not in ("passed", "wrong_answer"):      # crashed / timed out on its own tests
            return None
        outs.append(t.actual or "")
    llm_outs = [code_runner._normalize(t["output"]) for t in p.get("tests", []) + p.get("examples", [])]
    agree = sum(1 for a, b in zip(outs, llm_outs) if a == b)
    if agree < 0.6 * len(outs):
        return None                                            # statement and solution disagree
    n_tests = len(p.get("tests", []))
    validated = dict(p)
    validated["tests"] = [{"input": tests[i]["input"], "output": outs[i]} for i in range(n_tests)]
    validated["examples"] = [{**ex, "output": outs[n_tests + j]} for j, ex in enumerate(p.get("examples", []))]
    return validated


def validate_coding_node(state: AssessmentGraphState) -> AssessmentGraphState:
    valid = list(state.get("valid_coding", []))
    for p in state.get("coding_candidates", []):
        try:
            v = _validate_problem(p)
        except Exception:  # noqa: BLE001
            logger.warning("Validating a generated coding problem failed", exc_info=True)
            v = None
        if v:
            valid.append(v)
    return {"valid_coding": valid[: state.get("coding_count", 0)], "coding_candidates": []}


def route_after_validation(state: AssessmentGraphState) -> str:
    missing = state.get("coding_count", 0) - len(state.get("valid_coding", []))
    if missing > 0 and state.get("coding_attempts", 0) < MAX_CODING_ATTEMPTS:
        return "generate_coding"
    return "assemble"


def assemble_node(state: AssessmentGraphState) -> AssessmentGraphState:
    notes = list(state.get("notes", []))
    difficulty = state.get("difficulty", "medium")
    questions = [GeneratedQuestion.model_validate(q) for q in state.get("mcqs", [])]
    new_problems = []
    for p in state.get("valid_coding", []):
        new_problems.append(p)
        # problem_id is filled in by the route once the CodingProblem row exists.
        questions.append(GeneratedQuestion(type=QuestionType.CODING, skill=p.get("skill") or state.get("skills", [])[0],
                                           difficulty=difficulty, question=p["title"]))
    missing = state.get("coding_count", 0) - len(new_problems)
    if missing > 0:
        bank = state.get("fallback_problems", [])[:missing]
        for b in bank:
            questions.append(GeneratedQuestion(type=QuestionType.CODING, skill=(b.get("tags") or "programming").split(",")[0].strip(),
                                               difficulty=b.get("difficulty") or difficulty, question=b["title"],
                                               problem_id=b["problem_id"]))
        notes.append(f"{missing} AI coding problem(s) could not be verified by running the reference solution; "
                     f"{len(bank)} verified problem(s) from the problem bank were used instead.")
    skills_covered = sorted({q.skill for q in questions if q.skill})
    qset = GeneratedQuestionSet(skills_covered=skills_covered, questions=questions)
    return {"question_set": qset.model_dump(mode="json"), "new_problems": new_problems, "notes": notes}


def build_assessment_graph():
    graph = StateGraph(AssessmentGraphState)
    graph.add_node("plan", plan_node)
    graph.add_node("generate_mcq", generate_mcq_node)
    graph.add_node("generate_coding", generate_coding_node)
    graph.add_node("validate_coding", validate_coding_node)
    graph.add_node("assemble", assemble_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "generate_mcq")
    graph.add_edge("generate_mcq", "generate_coding")
    graph.add_edge("generate_coding", "validate_coding")
    graph.add_conditional_edges("validate_coding", route_after_validation,
                                {"generate_coding": "generate_coding", "assemble": "assemble"})
    graph.add_edge("assemble", END)
    return graph.compile()


_GRAPH = None


def run_assessment_graph(**inputs) -> AssessmentGraphState:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_assessment_graph()
    return _GRAPH.invoke(inputs)
