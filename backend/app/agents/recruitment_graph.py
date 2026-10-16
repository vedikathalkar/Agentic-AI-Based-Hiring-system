"""
LangGraph orchestration for the recruitment pipeline.

Wires the existing, already-tested agents together as a single StateGraph:

    START -> resume_parser -> skill_evaluation -> experience_evaluation
          -> bias_check -> [conditional routing] -> ranking -> final_result -> END

Every node is a thin adapter: it reads what it needs out of the shared
state, calls the existing agent function with its existing signature, and
writes the agent's own return value back untouched. No agent's internal
scoring/extraction logic is changed by this file.

Two entry points are used by the existing routes:

- `run_screening_graph(...)` — called right after resume upload
  (routes/resumes.py). Runs Skill + Experience evaluation and Bias check.
  No assessment/test score exists yet at this point in the existing
  lifecycle, so Ranking here only produces skill/experience-based numbers
  and reports "pending_assessment" rather than a final blended score.
  This fills the "resume screening" phase that routes/assessments.py's
  FinalScore upsert comment already anticipated but nothing populated.

- `run_final_ranking_graph(...)` — called after the candidate submits
  their assessment (routes/assessments.py). The skill/experience scores
  already computed and stored at screening time are passed back in
  (nodes skip recomputation when a result is already present in state),
  and the freshly-known test_score is added, so Ranking now has all
  three inputs and produces the real final_score via the existing
  Ranking Agent — this is what backs `final_score_row` instead of the
  old inline weighted-average formula.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from .resume_parser import parse_resume
from .skill_agent import score_skills
from .experience_agent import score_experience
from .bias_agent import check_bias
from .ranking_agent import rank_candidates


class RecruitmentState(TypedDict, total=False):
    # Identifiers
    job_id: int
    candidate_id: int
    application_id: int

    # Inputs
    resume_file_path: str
    candidate_name: str
    job_data: Dict[str, Any]  # title/description/requirements/min_experience/weight_*
    test_score: Optional[float]  # only known once the assessment is submitted

    # Per-node outputs
    parsed_resume: Dict[str, Any]
    skill_result: Dict[str, Any]
    experience_result: Dict[str, Any]
    bias_result: Dict[str, Any]
    ranking_result: Dict[str, Any]
    final_result: Dict[str, Any]


def _map_experience_entries(entries: Optional[List[dict]]) -> List[dict]:
    """Adapts Resume Parser experience entries (title_or_role/organization/
    duration_months/details) into the field names the Experience Agent's
    optional `experience_entries` parameter reads (title/years/description).
    Pure field-name adaptation, per integration Rule #3 — no scoring logic."""
    mapped = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        months = entry.get("duration_months")
        years = round(months / 12, 2) if isinstance(months, (int, float)) else 0.0
        details = entry.get("details") or []
        description = " ".join(details) if isinstance(details, list) else str(details)
        mapped.append({
            "title": entry.get("title_or_role") or entry.get("role") or "",
            "years": years,
            "description": description,
        })
    return mapped


def resume_parser_node(state: RecruitmentState) -> dict:
    """Wraps the existing Resume Parser Agent. Skipped when the caller
    already supplies `parsed_resume` — routes/resumes.py already parses
    the uploaded file itself (it needs the result to save the Resume row
    regardless of the graph), so this node mostly exists for completeness
    and any future caller that only has a file path."""
    if state.get("parsed_resume"):
        return {}
    file_path = state.get("resume_file_path")
    if not file_path:
        return {"parsed_resume": {}}
    parsed = parse_resume(file_path, candidate_name=state.get("candidate_name", ""))
    return {"parsed_resume": parsed}


def skill_evaluation_node(state: RecruitmentState) -> dict:
    """Wraps the existing Skill Agent."""
    if state.get("skill_result") is not None:
        return {}
    parsed = state.get("parsed_resume") or {}
    job = state.get("job_data") or {}
    result = score_skills(parsed.get("skills", ""), job.get("requirements", ""))
    return {"skill_result": result}


def experience_evaluation_node(state: RecruitmentState) -> dict:
    """Wraps the existing Experience Agent."""
    if state.get("experience_result") is not None:
        return {}
    parsed = state.get("parsed_resume") or {}
    job = state.get("job_data") or {}
    result = score_experience(
        candidate_years=parsed.get("experience_years", 0.0),
        min_experience=job.get("min_experience", 0.0),
        candidate_experience_text=parsed.get("experience", ""),
        job_title=job.get("title", ""),
        job_requirements=job.get("requirements", ""),
        job_description=job.get("description", ""),
        experience_entries=_map_experience_entries(parsed.get("experience_entries")),
    )
    return {"experience_result": result}


def bias_check_node(state: RecruitmentState) -> dict:
    """Wraps the existing Bias/Fairness Agent. Cheap deterministic regex
    checks, so this always runs (no skip-guard needed)."""
    parsed = state.get("parsed_resume") or {}
    job = state.get("job_data") or {}
    evaluation_data = {
        "skill_result": state.get("skill_result"),
        "experience_result": state.get("experience_result"),
    }
    result = check_bias(parsed, job, evaluation_data)
    return {"bias_result": result}


def _route_after_bias(state: RecruitmentState) -> str:
    """The Bias Agent never changes, reduces, or increases a score (see its
    own docstring) — it only flags for review. Per integration Rule #8,
    processing always continues to Ranking using job-relevant information
    regardless of the flag; `bias_result` stays attached to state for the
    caller/HR to review. Kept as a real conditional-edge (rather than a
    plain edge) so the graph structure matches the required flow and so a
    future review-routing branch can be added here without touching the
    rest of the graph."""
    return "ranking"


def ranking_node(state: RecruitmentState) -> dict:
    """Wraps the existing Ranking Agent. Always called with a
    single-candidate list — this is a per-candidate scoring point in the
    existing lifecycle (resume screening, then post-assessment), not the
    HR-facing "rank all candidates for a job" list view, but the exact
    same scoring/weighting logic in ranking_agent.py is reused rather than
    reimplemented, per Rule #9."""
    job = state.get("job_data") or {}
    skill_result = state.get("skill_result") or {}
    experience_result = state.get("experience_result") or {}
    test_score = state.get("test_score")

    skill_score = skill_result.get("score", 0.0)
    experience_score = experience_result.get(
        "experience_score", experience_result.get("score", 0.0)
    )

    candidate = {
        "candidate_id": state.get("candidate_id"),
        "skill_score": skill_score,
        "experience_score": experience_score,
        # Ranking Agent normalizes weights itself; a candidate needs a
        # numeric test_score to be ranked at all, so use 0 as a neutral
        # placeholder pre-assessment and rely on `status` below to make
        # clear the result isn't final yet.
        "test_score": test_score if test_score is not None else 0.0,
    }

    ranking_output = rank_candidates([candidate], job)
    ranked = ranking_output["ranked_candidates"][0]

    result = {
        "skill_score": skill_score,
        "experience_score": experience_score,
        "test_score": test_score,
        "weights_used": ranking_output["weights_used"],
        "final_score": ranked["final_score"] if test_score is not None else None,
        "recommendation": (
            ranked["recommendation"] if test_score is not None else "Pending assessment"
        ),
        "ranking_explanation": (
            ranked["ranking_explanation"]
            if test_score is not None
            else "Skill and experience scores computed; final ranking is pending the candidate's assessment score."
        ),
        "status": "final" if test_score is not None else "pending_assessment",
    }
    return {"ranking_result": result}


def final_result_node(state: RecruitmentState) -> dict:
    """Assembles the graph's output. Education is intentionally excluded
    here (Rule #4/#9) even though it may exist on the parsed resume."""
    return {
        "final_result": {
            "job_id": state.get("job_id"),
            "candidate_id": state.get("candidate_id"),
            "application_id": state.get("application_id"),
            "skill_result": state.get("skill_result"),
            "experience_result": state.get("experience_result"),
            "bias_result": state.get("bias_result"),
            "ranking_result": state.get("ranking_result"),
        }
    }


def _build_graph():
    graph = StateGraph(RecruitmentState)
    graph.add_node("resume_parser", resume_parser_node)
    graph.add_node("skill_evaluation", skill_evaluation_node)
    graph.add_node("experience_evaluation", experience_evaluation_node)
    graph.add_node("bias_check", bias_check_node)
    graph.add_node("ranking", ranking_node)
    graph.add_node("final_result", final_result_node)

    graph.add_edge(START, "resume_parser")
    graph.add_edge("resume_parser", "skill_evaluation")
    graph.add_edge("skill_evaluation", "experience_evaluation")
    graph.add_edge("experience_evaluation", "bias_check")
    graph.add_conditional_edges("bias_check", _route_after_bias, {"ranking": "ranking"})
    graph.add_edge("ranking", "final_result")
    graph.add_edge("final_result", END)

    return graph.compile()


_recruitment_graph = _build_graph()


def run_screening_graph(
    *,
    job_id: int,
    candidate_id: int,
    application_id: int,
    job_data: Dict[str, Any],
    parsed_resume: Dict[str, Any],
) -> Dict[str, Any]:
    """Runs the full graph right after resume upload. `parsed_resume` is
    passed in directly (the upload route already parsed the file to save
    the Resume row) rather than re-parsing. No test_score yet, so the
    ranking node reports a pending result."""
    state: RecruitmentState = {
        "job_id": job_id,
        "candidate_id": candidate_id,
        "application_id": application_id,
        "job_data": job_data,
        "parsed_resume": parsed_resume,
        "test_score": None,
    }
    return _recruitment_graph.invoke(state)


def run_final_ranking_graph(
    *,
    job_id: int,
    candidate_id: int,
    application_id: int,
    job_data: Dict[str, Any],
    skill_result: Dict[str, Any],
    experience_result: Dict[str, Any],
    test_score: float,
    parsed_resume: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Runs the graph after the assessment is submitted. Skill/experience
    results already computed at screening time are supplied directly so
    those nodes skip recomputation; the now-known test_score lets Ranking
    produce the real final_score."""
    state: RecruitmentState = {
        "job_id": job_id,
        "candidate_id": candidate_id,
        "application_id": application_id,
        "job_data": job_data,
        # Keep the original parsed resume available to the final Bias node.
        # Skill/experience results are supplied from screening and therefore
        # those agent nodes skip recomputation.
        "parsed_resume": parsed_resume or {},
        "skill_result": skill_result,
        "experience_result": experience_result,
        "test_score": test_score,
    }
    return _recruitment_graph.invoke(state)
