"""
Assessment Agent — Groq service layer.

Uses Groq for both assessment question generation and short-answer grading.
The rest of the assessment API remains unchanged: routes/assessments.py still
receives/returns the same Pydantic models and stores the same JSON payloads.
"""

import json
import os
from pathlib import Path
from enum import Enum
from typing import List, Optional, Type, TypeVar

from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel, Field, ValidationError

# Support both project-root .env and backend/.env.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env", override=False)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_ASSESSMENT_MODEL", "openai/gpt-oss-120b")
GROQ_TEMPERATURE = float(os.getenv("GROQ_ASSESSMENT_TEMPERATURE", "0.4"))

if not GROQ_API_KEY:
    import warnings
    warnings.warn(
        "GROQ_API_KEY is not set. Assessment generation/grading will fail "
        "until you set it in .env"
    )


def _get_client() -> Groq:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=GROQ_API_KEY)


class QuestionType(str, Enum):
    MCQ = "mcq"
    SHORT_ANSWER = "short_answer"
    CODING = "coding"  # added by the platform from the coding problem bank, never by the LLM


class MCQOption(BaseModel):
    label: str = Field(description="Option label, e.g. 'A', 'B', 'C', 'D'")
    text: str


class GeneratedQuestion(BaseModel):
    type: QuestionType
    skill: str = Field(description="The skill/topic this question tests")
    difficulty: str = Field(description="easy | medium | hard")
    question: str
    options: Optional[List[MCQOption]] = None
    correct_option_label: Optional[str] = None
    reference_answer: Optional[str] = Field(
        default=None,
        description="Only for short-answer questions — rubric used later for grading.",
    )
    problem_id: Optional[int] = Field(default=None, description="Leave null.")


class GeneratedQuestionSet(BaseModel):
    skills_covered: List[str]
    questions: List[GeneratedQuestion]


class GradeResult(BaseModel):
    score: float = Field(description="Score from 0.0 to 1.0")
    is_correct: bool
    feedback: str = Field(description="1-2 sentences of constructive feedback")


T = TypeVar("T", bound=BaseModel)


def _call_json(
    *,
    system_prompt: str,
    user_prompt: str,
    schema_model: Type[T],
    temperature: float,
) -> T:
    """Call Groq and validate the JSON response with the existing Pydantic model."""
    client = _get_client()
    schema = schema_model.model_json_schema()

    # Groq supports JSON Schema output for gpt-oss-120b. Best-effort mode is
    # used because our Pydantic models intentionally contain optional fields.
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_model.__name__.lower(),
                "strict": False,
                "schema": schema,
            },
        },
    )

    content = response.choices[0].message.content or "{}"
    try:
        return schema_model.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(f"Groq returned invalid assessment JSON: {exc}") from exc


_GEN_SYSTEM_PROMPT = """You are an expert technical interviewer and assessment designer.
Write clear, unambiguous, skill-specific interview questions based on a job role's
information and required skills. Never invent skills that aren't implied by the
job information. Calibrate difficulty realistically.

For MCQ questions:
- Provide exactly 4 options labeled A, B, C, D.
- Exactly one option is correct.
- Distractors must be plausible.

For short-answer questions:
- Provide a concise 2-4 sentence reference_answer containing the key points a
  correct answer should include.

Return ONLY valid JSON matching the requested schema."""


def generate_questions(
    job_title: str,
    job_description: str,
    job_requirements: str,
    num_questions: int = 8,
    mcq_ratio: float = 0.6,
) -> GeneratedQuestionSet:
    mcq_count = round(num_questions * mcq_ratio)
    short_count = num_questions - mcq_count
    if num_questions >= 2:
        mcq_count = max(1, mcq_count)
        short_count = max(1, short_count)

    user_prompt = f"""Job title: {job_title or ''}

Job description:
---
{job_description or ''}
---

Required skills: {job_requirements or ''}

Generate exactly {num_questions} questions total.
Approximately {mcq_count} should be type "mcq" and {short_count} should be type "short_answer".
Base every question on a required skill or something clearly implied by the description.
Vary difficulty across easy, medium, and hard.

The JSON must have:
- skills_covered: array of strings
- questions: array of objects with type, skill, difficulty, question, options,
  correct_option_label, and reference_answer
- For MCQs, options must contain exactly A/B/C/D and correct_option_label must be set.
- For short answers, options and correct_option_label should be null and reference_answer must be set.
"""

    return _call_json(
        system_prompt=_GEN_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_model=GeneratedQuestionSet,
        temperature=GROQ_TEMPERATURE,
    )


_GRADE_SYSTEM_PROMPT = """You are a fair, consistent technical grader.
Grade a candidate's short answer against the reference answer/rubric.
Give partial credit for partially correct answers. Do not require exact wording;
grade for understanding and correctness of the key concepts.
Set is_correct to true only when score >= 0.6.
Return ONLY valid JSON matching the requested schema."""


def grade_short_answer(question: str, reference_answer: str, user_answer: str) -> GradeResult:
    user_prompt = f"""Question:
{question}

Reference answer / rubric (key points expected):
{reference_answer or ''}

Candidate's answer:
{user_answer}

Return:
- score: number from 0.0 to 1.0
- is_correct: boolean
- feedback: 1-2 concise sentences explaining the result
"""
    return _call_json(
        system_prompt=_GRADE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_model=GradeResult,
        temperature=0.0,
    )


# ---------------------------------------------------------------------------
# HR-driven assessment creation (used by agents/assessment_graph.py)
# ---------------------------------------------------------------------------

class GeneratedTestCase(BaseModel):
    input: str = Field(description="Exact stdin, newline separated")
    output: str = Field(description="Exact expected stdout")


class GeneratedExample(GeneratedTestCase):
    explanation: Optional[str] = None


class GeneratedCodingProblem(BaseModel):
    title: str
    skill: str
    statement: str
    input_format: str
    output_format: str
    constraints: str
    examples: List[GeneratedExample] = Field(description="2 worked examples shown to the candidate")
    tests: List[GeneratedTestCase] = Field(description="6-10 test cases incl. edge cases")
    reference_solution: str = Field(description="Complete Python 3 program reading stdin and writing stdout")


def generate_mcqs(job_title: str, job_description: str, skills: List[str], difficulty: str, count: int) -> GeneratedQuestionSet:
    """Exactly ``count`` MCQs at the requested difficulty (no short answers)."""
    user_prompt = f"""Job title: {job_title}

Job description:
---
{(job_description or '')[:4000]}
---

Skills to assess: {', '.join(skills)}
Difficulty: {difficulty} (keep every question at this level)

Generate exactly {count} questions, ALL of type "mcq", spread evenly across the skills.
Each must have options A, B, C, D with exactly one correct option (correct_option_label),
reference_answer = one sentence explaining why the correct option is right.
skills_covered: the skills actually covered."""
    return _call_json(system_prompt=_GEN_SYSTEM_PROMPT, user_prompt=user_prompt,
                      schema_model=GeneratedQuestionSet, temperature=GROQ_TEMPERATURE)


_CODING_SYSTEM_PROMPT = """You design stdin/stdout programming problems for hiring assessments
(like HackerRank). Problems must be self-contained, deterministic, and solvable in any
language in under a second. Inputs are plain text on stdin; outputs are plain text on stdout
with no extra prompts. Provide a correct, complete Python 3 reference solution.
Return ONLY valid JSON matching the requested schema."""


def generate_coding_problem(job_title: str, skills: List[str], difficulty: str, avoid_titles: List[str]) -> GeneratedCodingProblem:
    user_prompt = f"""Role: {job_title}
Relevant skills: {', '.join(skills)}
Difficulty: {difficulty}
Do not repeat these problems: {', '.join(avoid_titles) or 'none'}

Write ONE programming problem relevant to the role (data processing, algorithms or
logic the role would use). Include input_format, output_format, constraints,
2 examples with explanations, 6-10 tests (include edge cases such as empty/minimum
input and large values) and reference_solution (Python 3, reads sys.stdin)."""
    return _call_json(system_prompt=_CODING_SYSTEM_PROMPT, user_prompt=user_prompt,
                      schema_model=GeneratedCodingProblem, temperature=GROQ_TEMPERATURE)
