"""
Ranking Agent
-------------
Calculates candidate final scores using the weights defined by HR for a job.

Current review scope:
- Skill score
- Experience score
- Assessment/Test score

Education is intentionally NOT included because the current HR job-creation
flow does not provide an education weight.

The agent does not modify the individual agent scores and does not penalize
candidates for bias. Bias correction/review, if needed, should happen before
this agent receives the scores.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _number(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to a float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_weight(job_data: Dict[str, Any], *names: str) -> float:
    """
    Read an HR-defined weight.

    Supports both:
      {"weight_skill": 40, ...}
    and:
      {"weights": {"skill": 40, ...}}

    This keeps the agent compatible with the existing project data shape
    without introducing a new weight system.
    """
    weights = job_data.get("weights")

    if isinstance(weights, dict):
        for name in names:
            if name in weights:
                return _number(weights[name])

    for name in names:
        if name in job_data:
            return _number(job_data[name])

    return 0.0


def _normalise_weights(
    skill_weight: float,
    experience_weight: float,
    assessment_weight: float,
) -> tuple[float, float, float]:
    """
    Convert HR weights to fractions.

    HR normally enters percentages such as 40, 30, 30.
    If fractions such as 0.4, 0.3, 0.3 are supplied, they are also accepted.
    """
    total = skill_weight + experience_weight + assessment_weight

    if total <= 0:
        raise ValueError(
            "Ranking weights are missing or all zero. "
            "HR must provide Skill, Experience and Assessment weights."
        )

    # Percentage-style weights: 40 + 30 + 30 = 100.
    if total > 1.0:
        return (
            skill_weight / total,
            experience_weight / total,
            assessment_weight / total,
        )

    # Fraction-style weights: 0.4 + 0.3 + 0.3 = 1.
    return skill_weight, experience_weight, assessment_weight


def _candidate_score(candidate: Dict[str, Any], *names: str) -> float:
    """Read a candidate score using the first available field name."""
    for name in names:
        if name in candidate:
            return max(0.0, min(100.0, _number(candidate[name])))
    return 0.0


def _recommendation(score: float) -> str:
    if score >= 80:
        return "Strongly Recommended"
    if score >= 65:
        return "Recommended"
    if score >= 50:
        return "Consider"
    return "Not Recommended"


def _explanation(
    skill_score: float,
    experience_score: float,
    assessment_score: float,
    skill_weight: float,
    experience_weight: float,
    assessment_weight: float,
    final_score: float,
) -> str:
    components = [
        ("skills", skill_score * skill_weight),
        ("experience", experience_score * experience_weight),
        ("assessment", assessment_score * assessment_weight),
    ]
    components.sort(key=lambda item: item[1], reverse=True)

    strongest = components[0][0]
    weakest = components[-1][0]

    return (
        f"Final score is {final_score:.2f}, calculated from the HR-defined "
        f"weights for skills, experience, and assessment. "
        f"The strongest weighted contribution is {strongest}; "
        f"the lowest weighted contribution is {weakest}."
    )


def rank_candidates(
    candidates: List[Dict[str, Any]],
    job_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Rank candidates for an HR-created job.

    Parameters
    ----------
    candidates:
        List of candidate evaluation dictionaries. Expected score fields:
        skill_score, experience_score, test_score/assessment_score.

        Candidate id/name fields are preserved.

    job_data:
        HR-created job data containing:
        weight_skill, weight_experience, weight_test

        or nested:
        weights = {
            "skill": ...,
            "experience": ...,
            "assessment": ...
        }

    Returns
    -------
    dict
        LangGraph-compatible structured result containing ranked candidates
        and the weights used.
    """
    if not isinstance(candidates, list):
        raise TypeError("candidates must be a list.")

    if not isinstance(job_data, dict):
        raise TypeError("job_data must be a dictionary.")

    skill_weight = _get_weight(
        job_data, "weight_skill", "skill_weight", "skill"
    )
    experience_weight = _get_weight(
        job_data, "weight_experience", "experience_weight", "experience"
    )
    assessment_weight = _get_weight(
        job_data,
        "weight_test",
        "weight_assessment",
        "test_weight",
        "assessment_weight",
        "assessment",
        "test",
    )

    skill_w, experience_w, assessment_w = _normalise_weights(
        skill_weight,
        experience_weight,
        assessment_weight,
    )

    ranked = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        skill_score = _candidate_score(
            candidate, "skill_score", "skill_match_score", "skill"
        )
        experience_score = _candidate_score(
            candidate, "experience_score", "experience"
        )
        assessment_score = _candidate_score(
            candidate,
            "test_score",
            "assessment_score",
            "assessment",
            "test",
        )

        final_score = (
            skill_score * skill_w
            + experience_score * experience_w
            + assessment_score * assessment_w
        )

        result = dict(candidate)
        result.update(
            {
                "final_score": round(final_score, 2),
                "recommendation": _recommendation(final_score),
                "ranking_explanation": _explanation(
                    skill_score,
                    experience_score,
                    assessment_score,
                    skill_w,
                    experience_w,
                    assessment_w,
                    final_score,
                ),
            }
        )
        ranked.append(result)

    ranked.sort(key=lambda item: item["final_score"], reverse=True)

    for position, candidate in enumerate(ranked, start=1):
        candidate["rank"] = position

    return {
        "ranked_candidates": ranked,
        "weights_used": {
            "skill": round(skill_w, 4),
            "experience": round(experience_w, 4),
            "assessment": round(assessment_w, 4),
        },
        "education_included": False,
    }


# Simple alias for future LangGraph integration if desired.
ranking_agent = rank_candidates


if __name__ == "__main__":
    sample_job = {
        "weight_skill": 50,
        "weight_experience": 30,
        "weight_test": 20,
    }

    sample_candidates = [
        {
            "candidate_id": 1,
            "candidate_name": "Candidate A",
            "skill_score": 80,
            "experience_score": 90,
            "test_score": 70,
        },
        {
            "candidate_id": 2,
            "candidate_name": "Candidate B",
            "skill_score": 90,
            "experience_score": 70,
            "test_score": 85,
        },
    ]

    result = rank_candidates(sample_candidates, sample_job)

    for candidate in result["ranked_candidates"]:
        print(
            f"Rank {candidate['rank']}: "
            f"{candidate.get('candidate_name', candidate.get('candidate_id'))} "
            f"-> {candidate['final_score']}"
        )
