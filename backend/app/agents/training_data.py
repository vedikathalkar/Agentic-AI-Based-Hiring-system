"""
Generates labeled training examples for the resume NER model.

Real hand-annotated resume datasets are hard to get in bulk for a student
project, so this uses *distant supervision*: known skills and degree names
are dropped into varied sentence templates that mimic how they actually
appear in resumes ("Proficient in X", "worked with X and Y", "Completed a
X in ..."). Every occurrence is auto-labeled with its character span, so
the output is standard spaCy training format without manual annotation.

This is a legitimate, commonly used technique for bootstrapping NER
training data before layering in a smaller set of hand-corrected real
examples (which is the natural next step if you want to improve accuracy
further).
"""
import random

SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "Go", "React",
    "Node.js", "FastAPI", "Flask", "Django", "Spring Boot", "HTML", "CSS",
    "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "AWS", "Docker",
    "Kubernetes", "Git", "Machine Learning", "Deep Learning", "NLP",
    "TensorFlow", "PyTorch", "Scikit-learn", "Pandas", "NumPy",
    "Data Structures", "Algorithms", "REST APIs", "GraphQL", "Linux",
    "Tableau", "Power BI", "Figma", "Kotlin", "Flutter",
]

DEGREES = [
    "B.E. Information Technology", "B.Tech Computer Science",
    "M.Tech Data Science", "Bachelor of Computer Applications",
    "Master of Computer Applications", "MBA", "MCA", "BCA",
    "Bachelor of Engineering", "Master of Science in Artificial Intelligence",
    "Diploma in Computer Engineering", "Ph.D. in Machine Learning",
]

SKILL_TEMPLATES = [
    "Proficient in {a} and {b}.",
    "Worked extensively with {a}, {b}, and {c}.",
    "Skills include {a}, {b}, {c}.",
    "Built projects using {a} and {b}.",
    "Strong hands-on experience with {a}.",
    "Technical stack: {a}, {b}, {c}.",
    "Hands-on with {a} for backend development and {b} for the frontend.",
    "Comfortable working in {a}, {b}.",
    "Used {a} to build scalable APIs alongside {b}.",
    "Familiar with {a}, {b}, and {c} for data analysis.",
]

DEGREE_TEMPLATES = [
    "Completed a {deg} from a recognized university.",
    "Holds a {deg} degree.",
    "Graduated with a {deg}.",
    "Currently pursuing a {deg}.",
    "{deg}, graduated in 2024.",
    "Education: {deg}.",
    "Pursuing {deg} with a focus on software engineering.",
]

MIXED_TEMPLATES = [
    "{deg} graduate skilled in {a} and {b}.",
    "{deg} with strong knowledge of {a}, {b}, and {c}.",
]

# Resume text is bullet/heading formatted, not clean prose — train on that
# shape too so the model isn't only tuned to full sentences.
BULLET_SKILL_TEMPLATES = [
    "Skills\n{a}, {b}, {c}",
    "Technical Skills: {a}, {b}, {c}",
    "- {a}\n- {b}\n- {c}",
    "Built REST APIs using {a} and {b}",
    "Developed the frontend in {a} with {b} for styling",
]

BULLET_DEGREE_TEMPLATES = [
    "{deg}, Vidyalankar Institute of Technology, 2022-2026",
    "Education\n{deg}",
    "{deg} — Graduated 2024",
]


def _place(template: str, **spans) -> tuple[str, list[tuple[int, int, str]]]:
    """Fill a template and return (text, entity spans) by locating each
    inserted value's exact character offset after substitution."""
    text = template
    entities = []
    # process placeholders left to right so offsets stay accurate
    for key, (value, label) in spans.items():
        placeholder = "{" + key + "}"
        idx = text.find(placeholder)
        if idx == -1:
            continue
        text = text[:idx] + value + text[idx + len(placeholder):]
        entities.append((idx, idx + len(value), label))
    return text, entities


def generate_examples(n: int = 400, seed: int = 42) -> list[tuple[str, dict]]:
    random.seed(seed)
    examples = []

    for _ in range(n):
        kind = random.choice(["skill", "degree", "mixed", "bullet_skill", "bullet_degree"])

        if kind == "skill":
            template = random.choice(SKILL_TEMPLATES)
            picks = random.sample(SKILLS, k=template.count("{") )
            spans = {}
            for letter, val in zip(["a", "b", "c"], picks):
                spans[letter] = (val, "SKILL")
            text, ents = _place(template, **spans)

        elif kind == "degree":
            template = random.choice(DEGREE_TEMPLATES)
            deg = random.choice(DEGREES)
            text, ents = _place(template, deg=(deg, "DEGREE"))

        elif kind == "bullet_skill":
            template = random.choice(BULLET_SKILL_TEMPLATES)
            picks = random.sample(SKILLS, k=template.count("{"))
            spans = {}
            for letter, val in zip(["a", "b", "c"], picks):
                spans[letter] = (val, "SKILL")
            text, ents = _place(template, **spans)

        elif kind == "bullet_degree":
            template = random.choice(BULLET_DEGREE_TEMPLATES)
            deg = random.choice(DEGREES)
            text, ents = _place(template, deg=(deg, "DEGREE"))

        else:
            template = random.choice(MIXED_TEMPLATES)
            deg = random.choice(DEGREES)
            picks = random.sample(SKILLS, k=template.count("{") - 1)
            spans = {"deg": (deg, "DEGREE")}
            for letter, val in zip(["a", "b", "c"], picks):
                spans[letter] = (val, "SKILL")
            text, ents = _place(template, **spans)

        examples.append((text, {"entities": ents}))

    return examples
