"""
Resume Parsing Agent (Phase 3, NLP version) — hybrid pipeline.

Pipeline (see module functions in this order):
    1. Text extraction        pdfplumber (PDF) / python-docx (DOCX) -> plain text
    2. Text cleaning          unicode/whitespace/bullet normalization
    3. Flexible section detection   header-alias matching -> {section: text}
    4. Section-aware extraction     each field is pulled from its own section
                                     first, which is what makes this robust
                                     across different resume templates
    5. spaCy NER               custom-trained SKILL/DEGREE model + the
                                pretrained ORG/GPE/PERSON/DATE labels that
                                ship with en_core_web_sm
    6. Rule/keyword fallback   curated keyword lists + regexes fill in
                                anything sections/NER missed
    7. Validation/filtering    blocklists + heuristics reject false
                                positives (headings, months, generic words,
                                proficiency levels, spoken languages, etc.)
    8. Structured output       a dict; all pre-existing keys keep their
                                original type/format so the FastAPI route
                                and DB columns (Text/Float) don't break

Because the custom NER model is trained on synthetic (template-generated)
data rather than hand-annotated real resumes, it has real failure modes —
it can mislabel proper nouns as SKILL or stray numbers as DEGREE. Section
awareness (step 3/4) does most of the heavy lifting to fix this: pulling
skills primarily from a detected "Skills" section, or a degree primarily
from a detected "Education" section, is far more reliable than asking a
model trained on isolated sentences to find the same things in a whole,
unstructured document. NER and keyword matching remain as a safety net
for resumes with no clean section headers, or where a field is mentioned
outside its "home" section.
"""
import os

import re
import unicodedata
from datetime import date
from pathlib import Path
from .skill_discovery_agent import discover_skills
import json
import spacy
import pdfplumber
from docx import Document

MODEL_DIR = Path(__file__).parent / "ner_model"
_nlp = None       # trained custom model (SKILL, DEGREE, + original labels)
_base_nlp = None  # untouched pretrained model, used for ORG/GPE/PERSON/DATE

# ---------------------------------------------------------------------------
# 1. Vocabularies / lookup tables
# ---------------------------------------------------------------------------

# Used to sanity-check the model's SKILL predictions and as a keyword
# fallback for resumes with no clean Skills section. Keyed by lowercase
# match text; value is the display casing (so "aws" renders as "AWS" and
# not "Aws", "node.js" stays "Node.js", etc.) instead of blind .title().
SKILL_DISPLAY = {
    "python": "Python", "java": "Java", "javascript": "JavaScript", "typescript": "TypeScript",
    "c++": "C++", "c#": "C#", "c": "C", "go": "Go", "rust": "Rust",
    "react": "React", "react.js": "React.js", "angular": "Angular", "vue": "Vue", "vue.js": "Vue.js",
    "next.js": "Next.js", "node.js": "Node.js", "express": "Express", "express.js": "Express.js",
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "spring": "Spring",
    "spring boot": "Spring Boot", "laravel": "Laravel",
    "html": "HTML", "html5": "HTML5", "css": "CSS", "css3": "CSS3", "sass": "Sass",
    "tailwind": "Tailwind CSS", "bootstrap": "Bootstrap", "jquery": "jQuery",
    "sql": "SQL", "mysql": "MySQL", "postgresql": "PostgreSQL", "mongodb": "MongoDB",
    "sqlite": "SQLite", "redis": "Redis", "firebase": "Firebase", "oracle": "Oracle DB",
    "aws": "AWS", "azure": "Azure", "gcp": "GCP", "docker": "Docker", "kubernetes": "Kubernetes",
    "ci/cd": "CI/CD", "git": "Git", "github": "GitHub", "gitlab": "GitLab",
    "machine learning": "Machine Learning", "deep learning": "Deep Learning", "nlp": "NLP",
    "natural language processing": "Natural Language Processing", "computer vision": "Computer Vision",
    "generative ai": "Generative AI", "llm": "LLM", "llms": "LLMs",
    "tensorflow": "TensorFlow", "pytorch": "PyTorch", "keras": "Keras",
    "scikit-learn": "scikit-learn", "pandas": "Pandas", "numpy": "NumPy", "opencv": "OpenCV",
    "data analysis": "Data Analysis", "data structures": "Data Structures", "algorithms": "Algorithms",
    "rest api": "REST API", "rest apis": "REST APIs", "graphql": "GraphQL",
    "microservices": "Microservices", "agile": "Agile", "scrum": "Scrum", "jira": "Jira",
    "linux": "Linux", "unix": "Unix", "bash": "Bash", "shell scripting": "Shell Scripting",
    "kotlin": "Kotlin", "swift": "Swift", "flutter": "Flutter", "dart": "Dart",
    "android": "Android", "ios": "iOS",
    "r": "R", "matlab": "MATLAB", "tableau": "Tableau", "power bi": "Power BI", "excel": "Excel",
    "figma": "Figma", "ui/ux": "UI/UX", "photoshop": "Photoshop",
    "ansible": "Ansible", "terraform": "Terraform", "jenkins": "Jenkins", "postman": "Postman",
    "webpack": "Webpack", "vite": "Vite",
    "hadoop": "Hadoop", "spark": "Spark", "airflow": "Airflow", "kafka": "Kafka",
    "elasticsearch": "Elasticsearch",
    "ml": "ML", "ai": "AI", "genai": "GenAI", "kaggle": "Kaggle",
    "unit testing": "Unit Testing", "selenium": "Selenium", "junit": "JUnit", "pytest": "pytest",
    "cypress": "Cypress",
    "c/c++": "C/C++", "asp.net": "ASP.NET", ".net": ".NET", "dotnet": ".NET",
    "php": "PHP", "ruby": "Ruby", "ruby on rails": "Ruby on Rails", "scala": "Scala",
    "solidity": "Solidity", "blockchain": "Blockchain", "web3": "Web3",
    "mern": "MERN Stack", "mern stack": "MERN Stack", "mean stack": "MEAN Stack",
}
SKILL_KEYWORDS = set(SKILL_DISPLAY.keys())

# ---------------------------------------------------------
# Soft skills
# ---------------------------------------------------------

SOFT_SKILL_DISPLAY = {
    "communication": "Communication",
    "leadership": "Leadership",
    "teamwork": "Teamwork",
    "team management": "Team Management",
    "problem solving": "Problem Solving",
    "problem-solving": "Problem Solving",
    "collaboration": "Collaboration",
    "adaptability": "Adaptability",
    "analytical thinking": "Analytical Thinking",
    "critical thinking": "Critical Thinking",
    "time management": "Time Management",
    "attention to detail": "Attention to Detail",
    "decision making": "Decision Making",
    "decision-making": "Decision Making",
    "creativity": "Creativity",
    "conflict resolution": "Conflict Resolution",
    "presentation": "Presentation",
    "interpersonal skills": "Interpersonal Skills",
    "organizational skills": "Organizational Skills",
    "work ethic": "Work Ethic",
    "mentoring": "Mentoring",
    "negotiation": "Negotiation",
}

SOFT_SKILL_KEYWORDS = set(SOFT_SKILL_DISPLAY.keys())

def _unique_list(items):
    """Return items with case-insensitive duplicates removed."""
    result = []
    seen = set()
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result

# Generic bucket/category words that appear as sub-labels inside a Skills
# section (e.g. "Languages: Python, Java") but are never skills themselves.
SKILL_CATEGORY_LABELS = {
    "languages", "language", "frameworks", "framework", "libraries", "library",
    "tools", "technologies", "technology", "databases", "database", "cloud",
    "cloud platforms", "platforms", "concepts", "soft skills", "other skills",
    "frontend", "front end", "backend", "back end", "devops", "methodologies",
    "developer tools", "areas of interest", "coursework", "relevant coursework",
    "misc", "miscellaneous", "domains", "operating systems",
    "tech", "tech skills", "technical skills", "technical", "soft",
    "hard skills", "key skills", "core skills", "skill set", "skillset",
}

# Section-header/category words that, when a candidate is nothing but a
# concatenation of these (e.g. a two-column PDF merging "TECH SKILLS" and
# "SOFT SKILLS" onto the same line as "TECH SKILLS SOFT SKILLS"), mean the
# whole candidate is a formatting artifact rather than a real skill token.
_HEADER_ARTIFACT_WORDS = {
    "tech", "technical", "soft", "skills", "skill", "hard", "core", "key", "set",
}

# Known certificate/course/training providers and similar program names that
# frequently appear near a Skills or Certifications section but are never
# themselves a skill (the "FOSSEE problem" — see problem statement §4).
# This is a small, specific list of known non-skill entities, not a blanket
# rejection of every organization name.
KNOWN_NON_SKILL_ORGS = {
    "fossee", "udemy", "coursera", "edx", "nptel", "simplilearn", "swayam",
    "internshala", "great learning", "hackerrank", "hackerearth", "datacamp",
    "pluralsight", "udacity", "codecademy", "geeksforgeeks", "scaler", "upgrad",
    "linkedin learning",
}

# Contact-related words that should never be treated as skill candidates
# (problem statement §1/§4 — "Phone" showing up as a possible skill).
CONTACT_WORDS = {
    "phone", "mobile", "mobile number", "email", "email id", "e-mail",
    "address", "location", "linkedin", "linkedin profile", "github",
    "github profile", "portfolio", "website", "contact", "contact no",
    "contact number", "dob", "date of birth",
}

# Common false-positive traps the DEGREE-labeling model tends to fall into
DEGREE_BLOCKLIST_TOKENS = {"year", "years", "team", "engineers", "interns"}

# Section headers and generic nouns the model sometimes mislabels as
# SKILL on real (non-synthetic) resume text. These are generic categories
# that show up on most resumes, not words specific to any one file.
SKILL_BLOCKLIST = {
    # section headers / document metadata
    "india", "experience", "education", "skills", "projects", "summary",
    "objective", "career objective", "contact", "profile", "references",
    "certifications", "achievements", "internship", "internships",
    "resume", "linkedin", "portfolio", "leetcode", "github profile",
    "curriculum vitae", "cv", "biodata", "declaration", "personal details",
    # personality/CV adjectives
    "motivated", "passionate", "hardworking", "dedicated", "enthusiastic",
    "detail-oriented", "self-motivated", "team player", "quick learner",
    # education boilerplate
    "cgpa", "gpa", "secondary", "higher secondary", "higher", "hsc", "ssc",
    # proficiency-level words (appear next to spoken languages, not skills)
    "beginner", "intermediate", "advanced", "native", "fluent",
    "professional", "proficiency", "professional proficiency",
    "full professional proficiency", "working proficiency", "elementary",
    # commonly listed spoken languages (not programming languages)
    "english", "hindi", "marathi", "gujarati", "tamil", "telugu", "kannada",
    "bengali", "punjabi", "urdu", "french", "german", "spanish", "chinese",
    "japanese", "korean",
    # open-source boilerplate
    "contributed", "contribution", "contributions", "open", "source",
    "open source", "open source contributions", "girlscript",
    "summer of code", "gssoc",
    # generic verbs/nouns that show up in bullet points but aren't skills
    "developed", "designed", "built", "created", "implemented", "database",
    "languages", "tools", "technologies",
    # months (frequently misfire on date ranges)
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
} | SKILL_CATEGORY_LABELS | KNOWN_NON_SKILL_ORGS | CONTACT_WORDS

NAME_STOPWORDS = SKILL_BLOCKLIST | {
    "curriculum", "vitae", "resume", "cv", "biodata", "candidate",
    "phone", "email", "address", "mobile",
}

# ---------------------------------------------------------------------------
# Flexible section detection: alias phrase -> canonical section key.
# Longer/more specific aliases are matched before shorter ones so e.g.
# "work experience" wins over a bare "experience" alias when both are
# present in the list (handled by sorting in _all_aliases()).
# ---------------------------------------------------------------------------
SECTION_ALIASES = {
    "summary": [
        "professional summary", "career objective", "summary", "objective",
        "profile", "about me", "about",
    ],
    "skills": [
        "technical skills", "core skills", "key skills", "skill set",
        "skills & tools", "areas of expertise", "technical proficiencies",
        "competencies", "expertise", "skills",
    ],
    "experience": [
        "professional experience", "work experience", "employment history",
        "relevant experience", "internship experience", "internships",
        "internship", "work history", "employment", "experience",
    ],
    "education": [
        "educational qualifications", "academic qualifications",
        "academic background", "education", "qualifications",
    ],
    "projects": [
        "academic projects", "personal projects", "key projects",
        "project experience", "projects",
    ],
    "certifications": [
        "licenses and certifications", "licenses & certifications",
        "certifications", "certificates", "certification",
    ],
    "achievements": [
        "awards and honors", "awards & honors", "honors and awards",
        "achievements", "accomplishments", "awards",
    ],
    "research": [
        "research experience", "research papers", "publications", "research",
    ],
    "contact": [
        "contact information", "personal details", "contact",
    ],
}


def _all_aliases():
    pairs = []
    for canon, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            pairs.append((alias, canon))
    # longest alias first so "work experience" is tried before "experience"
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


_ALIASES_SORTED = _all_aliases()


def _clean_header_line(line: str) -> str:
    l = line.strip().lower()
    l = re.sub(r"^[\*\u2022\u25cf\u25aa\u2023\u25e6\u2219\->\s]+", "", l)
    l = re.sub(r"[:\-–—]+$", "", l).strip()
    l = re.sub(r"\s+", " ", l)
    return l


def _detect_section_headers(lines: list[str]) -> list[tuple[int, str]]:
    """Return [(line_index, canonical_section), ...] in document order."""
    headers = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > 60:
            continue
        cleaned = _clean_header_line(line)
        if not cleaned or len(cleaned.split()) > 6:
            continue
        for alias, canon in _ALIASES_SORTED:
            if cleaned == alias or (cleaned.startswith(alias) and len(cleaned) - len(alias) <= 3):
                headers.append((i, canon))
                break
    return headers


def split_sections(text: str) -> tuple[dict, str, list]:
    """Segment resume text into {canonical_section: text} plus the
    'preamble' (everything before the first detected header — normally the
    contact block: name, email, phone, links). Also returns a list of
    (canonical_section, start_char, end_char) spans over the *original*
    text, so callers can check whether a given NER entity's character
    offset falls inside e.g. the Skills section specifically."""
    lines = text.split("\n")
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1  # +1 for the "\n" removed by split()

    headers = _detect_section_headers(lines)
    sections: dict[str, str] = {}
    spans = []
    for idx, (line_no, canon) in enumerate(headers):
        start_line = line_no + 1
        end_line = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        chunk = "\n".join(lines[start_line:end_line]).strip()
        if not chunk:
            continue
        start_char = offsets[start_line] if start_line < len(offsets) else len(text)
        end_char = offsets[end_line] if end_line < len(offsets) else len(text)
        spans.append((canon, start_char, end_char))
        sections[canon] = (sections[canon] + "\n" + chunk) if canon in sections else chunk
    preamble_end = headers[0][0] if headers else min(len(lines), 10)
    preamble = "\n".join(lines[:preamble_end]).strip()
    return sections, preamble, spans


def _section_at(char_pos: int, spans: list) -> str:
    for canon, start, end in spans:
        if start <= char_pos < end:
            return canon
    return ""


def _text_excluding(text: str, chunk: str) -> str:
    if chunk and chunk in text:
        return text.replace(chunk, "")
    return text


# ---------------------------------------------------------------------------
# spaCy model loading
# ---------------------------------------------------------------------------

def _get_nlp():
    global _nlp
    if _nlp is None:
        if MODEL_DIR.exists():
            _nlp = spacy.load(MODEL_DIR)
        else:
            # fallback to the plain pretrained pipeline if the custom model
            # hasn't been trained yet — SKILL/DEGREE just won't be recognized
            _nlp = spacy.load("en_core_web_sm")
    return _nlp


def _get_base_nlp():
    global _base_nlp
    if _base_nlp is None:
        _base_nlp = spacy.load("en_core_web_sm")
    return _base_nlp


def _org_gpe_spans(text: str) -> list[tuple[int, int]]:
    """Company names, places, people, and dates according to the untouched
    base model — used to suppress the fine-tuned model's false-positive
    SKILL/DEGREE predictions on the same words (a known side effect of
    narrow fine-tuning on synthetic data)."""
    base_doc = _get_base_nlp()(text)
    return [(ent.start_char, ent.end_char) for ent in base_doc.ents if ent.label_ in ("ORG", "GPE", "PERSON", "DATE")]


def _overlaps(span, spans) -> bool:
    s0, e0 = span
    return any(s0 < e1 and s1 < e0 for s1, e1 in spans)


# ---------------------------------------------------------------------------
# 1. Text extraction
# ---------------------------------------------------------------------------

def _detect_column_boundary(words, page_width: float) -> float | None:
    """Finds a genuine two-column boundary by looking for a real gap in
    where words START (x0), rather than assuming an even 50/50 split --
    a narrow sidebar + wide main-content template (very common) does NOT
    split at the page's horizontal midpoint, so a fixed-midpoint split
    mis-classifies words from the wide column. Returns None when no
    convincing gap exists (ordinary single-column page)."""
    xs = sorted(w["x0"] for w in words)
    if len(xs) < 20:
        return None
    lo, hi = page_width * 0.15, page_width * 0.85
    best_gap, best_pos = 0.0, None
    for a, b in zip(xs, xs[1:]):
        if lo <= a <= hi and (b - a) > best_gap:
            best_gap, best_pos = (b - a), (a + b) / 2
    # Require a meaningfully large gap (not just normal inter-word
    # spacing) so ordinary single-column pages are never split.
    if best_gap < page_width * 0.05:
        return None
    return best_pos


def _reflow_two_column_page(page) -> str:
    """pdfplumber's default extract_text() reads a page roughly top-to-
    bottom, left-to-right by *y-position*, which on a genuine two-column
    resume template interleaves the sidebar (contact/skills/education)
    with the main column (summary/experience/projects) line by line --
    this is exactly what breaks section-header detection and produces
    text like "Python PROFESSIONAL EXPERIENCE" on one line (see
    problem statement, two-column Data Scientist resume).

    Detects a genuine two-column layout from a real gap in word x0
    START positions (not an assumed 50/50 split -- narrow-sidebar
    templates aren't split evenly) and, when found, extracts each
    column's text top-to-bottom on its own before concatenating them --
    instead of assuming PDF extraction order already equals visual
    reading order. Falls back to normal extraction for ordinary
    single-column pages, so this never risks corrupting the common
    case."""
    words = page.extract_words()
    if not words or len(words) < 20:
        return page.extract_text() or ""

    boundary = _detect_column_boundary(words, page.width)
    if boundary is None:
        return page.extract_text() or ""

    left_words = [w for w in words if w["x0"] < boundary]
    right_words = [w for w in words if w["x0"] >= boundary]

    # Only treat this as two columns when both sides carry a substantial,
    # roughly comparable amount of text -- guards against a stray footer/
    # header element being the only thing on one "side".
    if len(left_words) < 8 or len(right_words) < 8:
        return page.extract_text() or ""
    if min(len(left_words), len(right_words)) / max(len(left_words), len(right_words)) < 0.15:
        return page.extract_text() or ""

    def _column_text(col_words):
        lines: dict[int, list] = {}
        for w in col_words:
            key = round(w["top"] / 3)  # bucket words on (roughly) the same line
            lines.setdefault(key, []).append(w)
        ordered = []
        for key in sorted(lines.keys()):
            row = sorted(lines[key], key=lambda w: w["x0"])
            ordered.append(" ".join(w["text"] for w in row))
        return "\n".join(ordered)

    return _column_text(left_words) + "\n" + _column_text(right_words)


def extract_text_from_pdf(path: str) -> str:
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            try:
                page_text = _reflow_two_column_page(page)
            except Exception:
                page_text = page.extract_text() or ""
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def extract_text_from_docx(path: str) -> str:
    """Walks the document body in true reading order (paragraphs AND
    tables interleaved as they actually appear), not python-docx's default
    of iterating doc.paragraphs and doc.tables as two separate lists. A
    contact-info table at the top of the file would otherwise get appended
    at the very end of the extracted text, scrambling section detection
    and contact extraction."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    parts = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, doc).text
            if text.strip():
                parts.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _pdf_name_hint(path: str) -> str:
    """Best-effort only, and must never raise: the largest-font text near
    the top of a PDF resume's first page is very often the candidate's
    name, since plain text extraction otherwise treats a big bold header
    exactly like body text. This is just a hint fed into
    extract_candidate_name(); it still has to pass the normal validation
    there before being trusted."""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return ""
            page = pdf.pages[0]
            chars = [c for c in page.chars if c.get("top", page.height) < page.height * 0.35]
            if not chars:
                return ""
            max_size = max(c.get("size", 0) for c in chars)
            if max_size <= 0:
                return ""
            big = [c for c in chars if c.get("size", 0) >= max_size - 0.5]
            big.sort(key=lambda c: (round(c.get("top", 0), 1), c.get("x0", 0)))
            line = "".join(c.get("text", "") for c in big)
            return re.sub(r"\s+", " ", line).strip()[:60]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 2. Text cleaning / normalization
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\ufeff", "")
    # normalize assorted bullet glyphs at line-start to a plain "-"
    text = re.sub(r"^[ \t]*[\u2022\u25cf\u25aa\u2023\u25e6\u2219]\s*", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


# ---------------------------------------------------------------------------
# Contact info: name / email / phone
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_CANDIDATE_RE = re.compile(
    r"(?:\+\d{1,3}[\s\-.]?)?(?:\(\d{2,5}\)[\s\-.]?)?\d{2,5}[\s\-.]?\d{3,5}[\s\-.]?\d{0,5}"
)


def extract_email(text: str) -> str:
    m = EMAIL_RE.search(text)
    return m.group(0) if m else ""


def extract_phone(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()

        # Ignore lines that are obviously not phone/contact lines
        if not line:
            continue

        matches = re.findall(
            r'(?<!\d)(?:\+\d{1,3}[\s.-]?)?'
            r'(?:\d[\s.-]?){10,12}(?!\d)',
            line
        )

        for candidate in matches:
            digits = re.sub(r'\D', '', candidate)

            if 10 <= len(digits) <= 13:
                return candidate.strip()

    return ""


def extract_candidate_name(preamble: str, pdf_name_hint: str = "") -> str:
    def looks_like_name(cleaned: str) -> bool:
        words = cleaned.split()
        if not (1 <= len(words) <= 5):
            return False
        if any(ch.isdigit() for ch in cleaned):
            return False
        if cleaned.lower() in NAME_STOPWORDS:
            return False
        if any(w.lower().strip(".") in NAME_STOPWORDS for w in words):
            return False
        alpha_words = [w for w in words if re.fullmatch(r"[A-Za-z.'-]+", w)]
        if len(alpha_words) < len(words):
            return False
        return cleaned.isupper() or all(w[0].isupper() for w in words)

    # 1) font-size hint from the PDF, if present and plausible
    if pdf_name_hint:
        cleaned = re.sub(r"[|,•]+", " ", pdf_name_hint).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if looks_like_name(cleaned):
            return cleaned.title() if cleaned.isupper() else cleaned

    # 2) first plausible header line
    lines = [l.strip() for l in preamble.split("\n") if l.strip()]
    for line in lines[:8]:
        if EMAIL_RE.search(line) or re.search(r"http|www\.|linkedin|github\.com", line, re.IGNORECASE):
            continue
        cleaned = re.sub(r"[|,•\-–]+", " ", line).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if looks_like_name(cleaned):
            return cleaned.title() if cleaned.isupper() else cleaned

    # 3) fall back to the base model's PERSON entity near the top of the doc
    try:
        person_doc = _get_base_nlp()(preamble[:500] if preamble else "")
        for ent in person_doc.ents:
            if ent.label_ == "PERSON":
                return ent.text.strip()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def _is_plausible_skill(text: str) -> bool:
    lower = text.lower().strip()
    norm = _normalize_lookup_key(lower)
    if lower in SKILL_KEYWORDS or norm in SKILL_KEYWORDS:
        return True
    if lower in SKILL_BLOCKLIST or norm in SKILL_BLOCKLIST:
        return False
    if _looks_like_header_artifact(text):
        return False
    # Multi-word phrases the model predicts are only trusted if they exactly
    # match a known skill — otherwise things like "CAREER OBJECTIVE" or
    # "OPEN SOURCE CONTRIBUTIONS" get accepted just because they resemble a
    # skill phrase.
    if len(text.split()) > 1:
        return False
    if "\n" in text or len(text) > 20:
        return False
    if len(lower) < 2:
        return False
    if sum(c.isalpha() for c in text) < 2:
        return False
    if re.search(r"\b(university|institute|college|iit|nit|bombay|delhi|mumbai|engineer|engineering|intern|contributor)\b", lower):
        return False
    if lower.isdigit():
        return False
    return True


def _looks_like_header_artifact(tok: str) -> bool:
    """Catches two-column PDF merge artifacts where a section header got
    concatenated onto another (e.g. "TECH SKILLS SOFT SKILLS") — true when
    every word in the candidate is itself a header/category word."""
    words = [w.strip(".:").lower() for w in tok.split() if w.strip(".:")]
    if not words:
        return False
    return all(w in _HEADER_ARTIFACT_WORDS for w in words)


def _normalize_lookup_key(key: str) -> str:
    """A few resumes write soft skills as 'Communication Skills' /
    'Leadership Skills' where our dictionaries store the bare form
    ('communication', 'leadership'). Stripping a trailing 'skills'/'skill'
    before the dictionary lookup catches these without having to hand-add
    every '<skill> skills' variant to the dictionaries."""
    stripped = re.sub(r"\s+skills?$", "", key).strip()
    return stripped or key


def _skill_tokens_from_section(section_text: str, name_tokens: set, org_names: set | None = None) -> list[str]:
    org_names = org_names or set()
    found = []
    for line in section_text.split("\n"):
        line = re.sub(r"^[\-•*◦\s]+", "", line)
        if not line.strip():
            continue
        # "Languages: Python, Java" -> drop the category label before the colon
        if ":" in line:
            label, _, rest = line.partition(":")
            if label.strip().lower() in SKILL_CATEGORY_LABELS or len(label.split()) <= 3:
                line = rest
        # Split on the usual list delimiters PLUS "•" and "&" — a two-column
        # PDF can merge two adjacent columns onto one line with a bullet or
        # ampersand as the only visible separator (e.g.
        # "SQL • Leadership & Team Management", "MERN Stack • Time Management").
        tokens = re.split(r"[,;/|•]|\band\b|\s&\s", line)
        for tok in tokens:
            tok = tok.strip(" .\u2022-")
            if not tok:
                continue
            key = tok.lower()
            norm_key = _normalize_lookup_key(key)
            if key in SKILL_BLOCKLIST or key in SKILL_CATEGORY_LABELS:
                continue
            if norm_key in SKILL_BLOCKLIST or norm_key in SKILL_CATEGORY_LABELS:
                continue
            if _looks_like_header_artifact(tok):
                continue
            if key in name_tokens:
                continue
            # Known technical skills (incl. single-letter ones like "C"/"R")
            # always bypass the length filter below.
            is_known = key in SKILL_KEYWORDS or norm_key in SKILL_KEYWORDS \
                or key in SOFT_SKILL_KEYWORDS or norm_key in SOFT_SKILL_KEYWORDS
            if not is_known and (len(tok) > 40 or len(tok) < 2):
                continue
            if re.search(r"\b(university|institute|college|engineering|intern|internship|resume)\b", key):
                continue
            if tok.isdigit():
                continue
            # A multi-word candidate that CONTAINS a known non-skill
            # org/program name as one of its words (e.g. "FOSSEE Semester
            # Long Internship") is rejected even though the exact phrase
            # itself isn't in the blocklist — this is the direct fix for
            # the "FOSSEE problem" (problem statement §4) on multi-word
            # candidates, without blanket-rejecting every organization.
            if not is_known and (set(key.split()) & KNOWN_NON_SKILL_ORGS):
                continue
            # Reject a candidate that IS (or closely matches) a known
            # organization name in this section, unless it's also a
            # recognized skill (so e.g. "Oracle" the DB isn't dropped just
            # because "Oracle" the company was also NER-tagged as an ORG).
            if not is_known and any(key == o or key in o or o in key for o in org_names):
                continue
            found.append(tok)
    return found


def extract_skills(
    doc,
    text: str,
    sections: dict,
    section_spans: list,
    candidate_name: str = ""
) -> dict:
    """
    Extract skills using section-aware rules + custom NER + curated
    dictionary, then separate high-confidence technical/soft skills from
    ambiguous candidates.

    The ambiguous candidates are intentionally NOT sent to the LLM here.
    parse_resume() passes only those candidates to the Skill Discovery Agent.
    """
    found = []
    seen = set()

    suppress_spans = _org_gpe_spans(doc.text)

    name_tokens = {
        t.lower()
        for t in candidate_name.split()
        if len(t) > 1
    }

    has_skills_section = "skills" in sections

    # Organization names spaCy's base model finds within the Skills section
    # specifically — used to reject "remove obvious organization names when
    # confidently known" (problem statement §1) without blanket-rejecting
    # every ORG anywhere in the resume.
    skills_section_text = sections.get("skills", "")
    org_names_in_skills = set()
    if skills_section_text:
        try:
            org_names_in_skills = {
                ent.text.lower().strip()
                for ent in _get_base_nlp()(skills_section_text).ents
                if ent.label_ == "ORG"
            }
        except Exception:
            org_names_in_skills = set()

    # 1. Skills section
    for tok in _skill_tokens_from_section(
        sections.get("skills", ""),
        name_tokens,
        org_names=org_names_in_skills,
    ):
        key = tok.lower().strip()

        if key in SKILL_BLOCKLIST or key in SKILL_CATEGORY_LABELS:
            continue

        if key not in seen:
            seen.add(key)
            found.append(tok)

    # 2. Custom NER
    for ent in doc.ents:
        if ent.label_ != "SKILL":
            continue

        if (
            has_skills_section
            and _section_at(ent.start_char, section_spans) != "skills"
        ):
            continue

        if not _is_plausible_skill(ent.text):
            continue

        key = ent.text.lower().strip()

        if key in name_tokens or key in SKILL_BLOCKLIST:
            continue

        if _overlaps((ent.start_char, ent.end_char), suppress_spans):
            continue

        if key not in seen:
            seen.add(key)
            found.append(ent.text.strip())

    # 3. Known technical skill dictionary
    lower_text = text.lower()

    for skill in SKILL_KEYWORDS:
        pattern = (
            r"(?<![A-Za-z0-9_])"
            + re.escape(skill)
            + r"(?![A-Za-z0-9_+#])"
        )

        if re.search(pattern, lower_text):
            display = SKILL_DISPLAY.get(skill, skill)
            key = display.lower().strip()

            if key not in seen:
                seen.add(key)
                found.append(display)

    # 4. Known soft skill dictionary
    for skill in SOFT_SKILL_KEYWORDS:
        pattern = (
            r"(?<![A-Za-z0-9_])"
            + re.escape(skill)
            + r"(?![A-Za-z0-9_])"
        )

        if re.search(pattern, lower_text):
            display = SOFT_SKILL_DISPLAY[skill]
            key = display.lower().strip()

            if key not in seen:
                seen.add(key)
                found.append(display)

    # 5. Classify locally
    technical = []
    soft = []
    review_required = []

    for skill in found:
        key = skill.lower().strip()
        norm_key = _normalize_lookup_key(key)

        if key in SKILL_BLOCKLIST or key in SKILL_CATEGORY_LABELS:
            continue
        if norm_key in SKILL_BLOCKLIST or norm_key in SKILL_CATEGORY_LABELS:
            continue
        if _looks_like_header_artifact(skill):
            continue

        # Exact known soft skill (checked against both the raw key and the
        # "skills"/"skill"-suffix-stripped form, e.g. "Communication Skills")
        if key in SOFT_SKILL_DISPLAY:
            soft.append(SOFT_SKILL_DISPLAY[key])
        elif norm_key in SOFT_SKILL_DISPLAY:
            soft.append(SOFT_SKILL_DISPLAY[norm_key])

        # Exact known technical skill
        elif key in SKILL_DISPLAY:
            technical.append(SKILL_DISPLAY[key])
        elif norm_key in SKILL_DISPLAY:
            technical.append(SKILL_DISPLAY[norm_key])

        # NER/section candidate not known locally -> LLM review
        else:
            review_required.append(skill)

    return {
        "technical_skills": _unique_list(technical),
        "soft_skills": _unique_list(soft),
        "review_required_skills": _unique_list(review_required),
    }

# ---------------------------------------------------------------------------
# LLM-assisted Education / Experience extraction
# ---------------------------------------------------------------------------

LLM_MODEL_NAME = "openai/gpt-oss-120b"


def _get_groq_client():
    """Create Groq client only when LLM-assisted extraction is needed."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception:
        return None


def _llm_json_response(prompt: str):
    """Ask Groq for structured JSON. Returns parsed JSON or None."""
    client = _get_groq_client()
    if client is None:
        return None
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a precise resume information extraction component. Return valid JSON only. Never invent information."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as exc:
        print(f"LLM extraction failed: {exc}")
        return None

def _llm_extract_education(section_text: str) -> list[dict]:
    """
    LLM fallback for education extraction.

    The LLM receives ONLY the education section.
    It must extract information actually present in the text.
    """
    if not section_text or len(section_text.strip()) < 10:
        return []

    prompt = f"""
You are an information extraction component inside a resume parsing system.

Extract ONLY education entries from the text below.

IMPORTANT RULES:
1. Use ONLY information explicitly present in the supplied text.
2. Do NOT invent university names, degrees, years, CGPA, or fields.
3. Do NOT treat project names, technologies, algorithms, companies,
   certifications, skills, job titles, section headings, or random nouns
   as education, even if they appear right next to real education text.
4. Separate degree and field when possible.
5. Return JSON only.
6. If a value is not present, use null.
7. Do not include explanations.

Return exactly:

{{
  "education": [
    {{
      "degree": "string or null",
      "field": "string or null",
      "institution": "string or null",
      "start_year": "integer or null",
      "end_year": "integer or null",
      "status": "completed/ongoing/unknown",
      "cgpa": "number or null",
      "percentage": "number or null"
    }}
  ]
}}

EDUCATION TEXT:
{section_text}
"""

    data = _llm_json_response(prompt)

    if not isinstance(data, dict):
        return []

    entries = data.get("education", [])

    if not isinstance(entries, list):
        return []

    cleaned = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        degree = str(entry.get("degree") or "").strip()
        field = str(entry.get("field") or "").strip()
        institution = str(entry.get("institution") or "").strip()

        if not degree:
            continue

        # General hallucination/contamination guard -- model-driven (our
        # fine-tuned SKILL/DEGREE labels + the existing degree-phrase
        # regex + the existing section-heading table), not a hard-coded
        # word list, so it generalizes to unseen resumes.
        if _degree_is_suspicious(degree):
            continue
        if field and _education_field_is_suspicious(field):
            field = ""
        institution = _clean_contaminated_institution(institution)

        def safe_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def safe_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        start_year = safe_int(entry.get("start_year"))
        end_year = safe_int(entry.get("end_year"))
        cgpa = safe_float(entry.get("cgpa"))
        percentage = safe_float(entry.get("percentage"))

        status = str(entry.get("status") or "unknown").lower()
        if status not in {"completed", "ongoing", "unknown"}:
            status = "unknown"

        cleaned.append({
            "degree": degree,
            "field": field,
            "institution": institution,
            "start_year": start_year,
            "end_year": end_year,
            "status": status,
            "cgpa": cgpa,
            "percentage": percentage,
            "year": str(end_year) if end_year else (
                str(start_year) if start_year else ""
            ),
        })

    return cleaned


def _extract_explicit_experience_headers(text: str) -> list[dict]:
    """Extract high-confidence role/organization pairs explicitly shown in
    experience headers, including layouts where the date range is on the
    following line."""
    if not text:
        return []

    lines = [x.strip() for x in text.splitlines()]
    results = []
    date_pat = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}-\d{2}|\d{4}"
    range_re = re.compile(
        rf"(?P<start>{date_pat})\s*(?:-|–|—|to)\s*(?P<end>{date_pat}|Present|Current|Ongoing)",
        re.I,
    )
    split_re = re.compile(r"\s*(?:\||—|–|\s+-\s+)\s*")

    def credible(x: str) -> bool:
        return bool(
            x and not _looks_like_location_text(x)
            and not _looks_like_section_heading_text(x)
            and not _looks_like_skill_or_degree_fragment(x)
            and not _looks_like_weak_fragment(x)
        )

    def add(role: str, org: str, start_raw=None, end_raw=None):
        role, org = role.strip(), org.strip()
        # An explicit Experience header is stronger evidence than generic
        # NER/skill heuristics. Do not reject legitimate job titles or
        # company names merely because a model labels them as SKILL/DEGREE.
        if (
            role and org
            and not _looks_like_location_text(role)
            and not _looks_like_location_text(org)
            and not _looks_like_section_heading_text(role)
            and not _looks_like_section_heading_text(org)
            and not _looks_like_weak_fragment(role)
            and not _looks_like_weak_fragment(org)
        ):
            results.append({
                "role": role,
                "organization": org,
                "start_date_raw": start_raw,
                "end_date_raw": end_raw,
            })

    for i, line in enumerate(lines):
        if not line:
            continue

        # Form 1: Role | Org | Location | Dates OR Role — Org | Location | Dates
        m = range_re.search(line)
        if m:
            before = line[:m.start()].strip(" |–—-:")
            parts = [x.strip() for x in split_re.split(before) if x.strip()]
            if len(parts) >= 2:
                add(parts[0], parts[1], m.group("start"), m.group("end"))
                continue

        # Form 2: Role — Organization, with date on this or the next 1–2 lines.
        parts = [x.strip() for x in split_re.split(line) if x.strip()]
        if len(parts) >= 2:
            # Avoid treating a sentence/bullet as a header.
            if not line.startswith(("•", "-", "–", "—", "*")):
                start_raw = end_raw = None
                for j in range(i, min(i + 3, len(lines))):
                    dm = range_re.search(lines[j])
                    if dm:
                        start_raw, end_raw = dm.group("start"), dm.group("end")
                        break
                add(parts[0], parts[1], start_raw, end_raw)

    return results


def _normalize_experience_evidence_date(raw: str | None, is_end: bool = False) -> str | None:
    if not raw:
        return None
    raw = str(raw).strip()
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        return raw
    if re.fullmatch(r"\d{4}", raw):
        return f"{raw}-12" if is_end else f"{raw}-01"
    m = re.fullmatch(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
        raw, re.I
    )
    if not m:
        return None
    return f"{m.group(2)}-{_month_num(m.group(1)):02d}"


def _apply_explicit_experience_evidence(
    entries: list[dict], explicit_headers: list[dict]
) -> list[dict]:
    """Use explicit role/company headers as high-confidence evidence.

    When a resume explicitly writes role and organization together in the
    Experience section, that relationship is stronger than an LLM guess.
    For entries sharing the same start/end dates, correct missing OR
    conflicting role/org fields from that explicit header.  This remains
    generalized because it uses only structure and dates from the resume.
    """
    if not entries or not explicit_headers:
        return entries

    for ev in explicit_headers:
        ev_role = (ev.get("role") or "").strip()
        ev_org = (ev.get("organization") or "").strip()
        if not ev_role or not ev_org:
            continue

        ev_start = _normalize_experience_evidence_date(ev.get("start_date_raw"))
        ev_end = _normalize_experience_evidence_date(ev.get("end_date_raw"), True)

        candidates = []
        for idx, entry in enumerate(entries):
            start = entry.get("start_date")
            end = entry.get("end_date")
            if ev_start and start != ev_start:
                continue
            if ev_end and end != ev_end:
                continue
            candidates.append((idx, entry))

        # Exact date-range evidence is authoritative. If the header has no
        # dates, only attach it when the role or organization already matches.
        if len(candidates) != 1:
            candidates = []
            for idx, entry in enumerate(entries):
                role = (entry.get("role") or entry.get("title_or_role") or "").strip().lower()
                org = (entry.get("organization") or "").strip().lower()
                if role == ev_role.lower() or org == ev_org.lower():
                    candidates.append((idx, entry))

        if len(candidates) != 1:
            continue

        _, entry = candidates[0]

        # Explicit resume header evidence wins over an empty or contradictory
        # LLM value. It is not a fabricated value and is tied to the same
        # experience date range.
        current_role = (entry.get("role") or entry.get("title_or_role") or "").strip()
        current_org = (entry.get("organization") or "").strip()

        if not current_role or _looks_like_skill_or_degree_fragment(current_role) or _looks_like_location_text(current_role):
            entry["role"] = ev_role
            entry["title_or_role"] = ev_role
        elif current_role.lower() != ev_role.lower() and ev_start:
            entry["role"] = ev_role
            entry["title_or_role"] = ev_role

        if not current_org or _looks_like_skill_or_degree_fragment(current_org) or _looks_like_location_text(current_org):
            entry["organization"] = ev_org
        elif current_org.lower() != ev_org.lower() and ev_start:
            entry["organization"] = ev_org

    return entries

def _llm_extract_experience(section_text: str) -> list[dict]:
    """
    LLM fallback for experience extraction.

    The LLM receives ONLY the experience section.
    Duration is calculated separately by Python.
    """
    if not section_text or len(section_text.strip()) < 10:
        return []

    explicit_headers = _extract_explicit_experience_headers(section_text)
    explicit_evidence = "\n".join(
        f"- ROLE: {x['role']} | ORGANIZATION: {x['organization']} | DATES: {x['start_date_raw']} - {x['end_date_raw']}"
        for x in explicit_headers
    ) or "(No explicit role-organization header pairs were detected by the parser.)"

    prompt = f"""
You are the EXPERIENCE extraction component of a resume parser.

Your task is NOT to summarize the resume. Your task is to copy and structure
the employment history that is explicitly written in the supplied text.

CRITICAL: The supplied text contains the COMPLETE extracted resume text.
Some PDF layouts (especially two-column resumes) may scramble the visual
reading order. Therefore you must reconstruct the original experience
records from the textual evidence.

========================
HIGHEST PRIORITY RULE
========================

FIRST identify the EXPERIENCE section and its individual experience records.

For every experience record, find the strongest explicit combination of:

ROLE + ORGANIZATION + DATE RANGE

Treat these three pieces as belonging together when the resume formatting
clearly indicates that they form one heading, even if extraction placed them
on separate lines.

DO NOT use projects, certifications, education, skills, summary/profile text,
or achievements to fill an experience role or organization.

If an explicit role and organization appear together in a heading, COPY THEM.
Do NOT replace the role with a project name or another nearby phrase.

Examples:

"Data Scientist | InsightEdge Analytics — Bengaluru | Aug 2024 – Present"

MUST become:

role = "Data Scientist"
organization = "InsightEdge Analytics"
location = "Bengaluru"
start_date = "2024-08"
end_date = null

"Senior Product Manager — CloudAxis"
" Mumbai | Jan 2024 – Present"

MUST become:

role = "Senior Product Manager"
organization = "CloudAxis"
location = "Mumbai"
start_date = "2024-01"
end_date = null

"Product Manager — FinServe Technologies"
"Pune | Jul 2021 – Dec 2023"

MUST become:

role = "Product Manager"
organization = "FinServe Technologies"
location = "Pune"
start_date = "2021-07"
end_date = "2023-12"

"UX Designer — PixelCraft Studio | Chennai | Mar 2022 – Present"

MUST become:

role = "UX Designer"
organization = "PixelCraft Studio"
location = "Chennai"
start_date = "2022-03"
end_date = null

"UI/UX Intern — DesignWorks | Chennai | Jun 2021 – Feb 2022"

MUST become:

role = "UI/UX Intern"
organization = "DesignWorks"
location = "Chennai"
start_date = "2021-06"
end_date = "2022-02"

These examples demonstrate the RULE, not resume-specific data to memorize.
Apply exactly the same reasoning to unseen resumes.

========================
DO NOT CONFUSE FIELDS
========================

A role is a job title such as:
Software Engineer, Data Scientist, Product Manager, UX Designer,
Data Analyst Intern, Research Assistant, etc.

An organization is the employer/company/institution.

A location is a city, state, country, remote location, or address.
A location is NEVER a role or organization.

A project name is NEVER a role.
A technology/skill is NEVER a role.
A certification is NEVER a role.
A section heading is NEVER a role.

For example, if you see:

Data Scientist | InsightEdge Analytics
...
Loan Default Prediction
...

the role is Data Scientist, NOT Loan Default Prediction.

========================
HOW TO RECONSTRUCT EACH ENTRY
========================

For EACH date range in the EXPERIENCE section:

1. Look for an explicit role + organization heading associated with it.
2. If role and organization occur on the same line, treat that as the
   strongest possible evidence.
3. If the role and organization are on adjacent lines or separated by a
   location line, combine them when the date range and surrounding bullets
   clearly indicate one employment record.
4. Attach the bullet points immediately describing that employment to the
   same record.
5. Then move to the next distinct date range / employment heading.
6. NEVER borrow a role, organization, or project name from another
   experience record.
7. NEVER leave role or organization blank when both are explicitly present
   for that record.
8. If only one field is explicitly available, preserve that field and leave
   the other null. Do not invent it.

IMPORTANT: The order in extracted PDF text may be imperfect, but explicit
heading patterns are more reliable than generic semantic guesses.

========================
DO NOT GUESS
========================

Use ONLY information contained in the supplied text.

Do not invent:
- companies
- job titles
- dates
- locations
- responsibilities

Do not infer an organization merely because a company-like word appears
somewhere in the resume.

Do not infer a role from the candidate's summary/profile if that role is not
the actual title of an experience record.

Do not infer a role from a project.

========================
OUTPUT REQUIREMENTS
========================

Return EVERY distinct employment/internship/research experience explicitly
present in the EXPERIENCE section.

If there are two date ranges, return two records.
If there are three date ranges, return three records.

Preserve the actual role and organization from the resume.

Return JSON ONLY:

{{
  "experience": [
    {{
      "role": "string or null",
      "organization": "string or null",
      "location": "string or null",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null",
      "status": "completed/ongoing/unknown",
      "experience_type": "full-time/part-time/internship/research/unknown",
      "details": ["string"]
    }}
  ]
}}

Do NOT calculate duration_months.

HIGH-CONFIDENCE ROLE/ORGANIZATION EVIDENCE DETECTED FROM THE EXPERIENCE TEXT:
{explicit_evidence}

Treat the high-confidence evidence above as direct evidence from the resume.
When it corresponds to a date range, preserve BOTH role and organization.
Do not replace an explicitly detected role with a project, skill, location,
or other nearby text.

========================
EXPERIENCE TEXT START
========================
{section_text}
========================
EXPERIENCE TEXT END
========================

Before producing JSON, internally verify for EVERY returned record:

- Is this actually an employment/internship/research record?
- Is the role an actual job title?
- Is the organization an employer/institution?
- Are role and organization associated with the SAME date range?
- Did I accidentally use a project, skill, certification, or location?
- Did I omit another distinct experience record?

Return ONLY the JSON object. No explanation.
"""


    data = _llm_json_response(prompt)

    if not isinstance(data, dict):
        return []

    entries = data.get("experience", [])

    if not isinstance(entries, list):
        return []

    cleaned = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        role = str(entry.get("role") or "").strip()
        organization = str(entry.get("organization") or "").strip()
        location = str(entry.get("location") or "").strip()

        if not role and not organization:
            continue

        # Location must never become the role.
        if role.lower() == location.lower():
            role = ""

        # Reject non-role/non-org artifacts using general, model-driven
        # signals (GPE/LOC + our fine-tuned SKILL/DEGREE labels + the
        # existing section-heading table) instead of a fixed word list --
        # this is what lets it generalize to any unseen resume.
        if _looks_like_location_text(role) or _looks_like_section_heading_text(role) \
                or _looks_like_skill_or_degree_fragment(role) or _looks_like_weak_fragment(role):
            role = ""

        if organization and (
            organization.lower() == location.lower()
            or _looks_like_location_text(organization)
            or _looks_like_section_heading_text(organization)
            or _looks_like_skill_or_degree_fragment(organization)
            or _looks_like_weak_fragment(organization)
        ):
            organization = ""

        # Keep partial but credible LLM entries. The role may be missing
        # while the organization/dates are correct (or vice versa); later
        # validation and deterministic backfill can safely recover the
        # missing field without throwing away the whole experience record.

        start_date = entry.get("start_date")
        end_date = entry.get("end_date")

        if start_date:
            start_date = str(start_date).strip()
            if not re.fullmatch(r"\d{4}-\d{2}", start_date):
                start_date = None

        if end_date:
            end_date = str(end_date).strip()
            if not re.fullmatch(r"\d{4}-\d{2}", end_date):
                end_date = None

        status = str(entry.get("status") or "unknown").lower()
        if status not in {"completed", "ongoing", "unknown"}:
            status = "unknown"

        experience_type = str(
            entry.get("experience_type") or "unknown"
        ).lower()

        if experience_type not in {
            "full-time",
            "part-time",
            "internship",
            "research",
            "unknown",
        }:
            experience_type = "unknown"

        details = entry.get("details", [])
        if not isinstance(details, list):
            details = []

        details = [
            str(d).strip()
            for d in details
            if str(d).strip()
        ][:4]

        cleaned.append({
            "title_or_role": role,
            "organization": organization,
            "duration": (
                f"{start_date} – "
                f"{end_date or 'Present'}"
                if start_date else ""
            ),
            "details": details,
            "role": role,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "experience_type": experience_type,
            "duration_months": None,
        })

    cleaned = _apply_explicit_experience_evidence(cleaned, explicit_headers)
    return cleaned
# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

# Matches ONLY the degree keyword/phrase itself — deliberately does NOT try
# to swallow a trailing "in <field>" the way the previous version's
# open-ended "bachelor of [a-z& ]+" did. That greedy pattern is exactly what
# caused "Bachelor of Engineering in Information Technology" to be captured
# as a single indivisible `degree` string with no way to separate out
# `field`. Field extraction is now a dedicated second step (see
# FIELD_AFTER_DEGREE_RE below) applied to whatever follows this match.
DEGREE_CORE_RE = re.compile(
    r"\b("
    r"bachelor of engineering|bachelor of technology|bachelor of science|"
    r"bachelor of computer applications?|bachelor of commerce|bachelor of arts|"
    r"master of engineering|master of technology|master of science|"
    r"master of computer applications?|master of commerce|master of arts|"
    r"master of business administration|"
    r"b\.?\s?tech\.?|m\.?\s?tech\.?|b\.?\s?e\.?\b|m\.?\s?e\.?\b|"
    r"b\.?\s?c\.?a\.?\b|m\.?\s?c\.?a\.?\b|mba\b|"
    r"b\.?\s?sc\.?\b|m\.?\s?sc\.?\b|ph\.?\s?d\.?\b|"
    r"b\.?\s?com\.?\b|m\.?\s?com\.?\b|"
    r"associate degree\b|diploma\b|"
    r"higher secondary(?:\s+certificate|\s+education)?|"
    r"secondary school(?:\s+certificate)?|"
    r"hsc\b|ssc\b|10th\b|12th\b"
    r")",
    re.IGNORECASE,
)
# "<degree> in/of <field>" — stops at a comma/newline/opening paren or a
# run of 2+ spaces (a common column-alignment artifact), so it never eats
# into an institution name or a date range that happens to follow.
FIELD_AFTER_DEGREE_RE = re.compile(
    r"^\s*(?:in|of)\s+([A-Za-z][A-Za-z &/\-]{2,60}?)(?=[,\n(]|\s{2,}|$)",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"(19|20)\d{2}")
# A full year range, e.g. "2023 - 2027", "2022 – Present". Matched as its
# own pattern (not just "any two numbers") specifically so it can be
# recognized and EXCLUDED when guessing the institution from leftover text
# — this is the direct fix for the "institution": "2023 – 2027" bug.
YEAR_RANGE_RE = re.compile(
    r"\(?\s*((?:19|20)\d{2})\s*(?:-|–|—|to)\s*((?:19|20)\d{2}|present|current|ongoing)\s*\)?",
    re.IGNORECASE,
)
CGPA_RE = re.compile(r"\b(?:cgpa|gpa)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)(?:\s*/\s*(?:10|4))?", re.IGNORECASE)
PERCENT_RE = re.compile(r"\b(\d{2,3}(?:\.\d{1,2})?)\s*%")


def _looks_like_date_range_text(frag: str) -> bool:
    """True if `frag` is essentially just a date/date-range and therefore
    must never be used as an institution name."""
    frag = frag.strip()
    if not frag:
        return False
    if YEAR_RANGE_RE.fullmatch(frag):
        return True
    if re.fullmatch(r"(19|20)\d{2}", frag):
        return True
    # a bare run of digits/dashes/"present"/"current" with nothing else
    if re.fullmatch(r"[\d\s\-–—/]+", frag):
        return True
    if re.fullmatch(r"(present|current|ongoing)", frag, re.IGNORECASE):
        return True
    return False


# ---------------------------------------------------------------------------
# General, model-driven validation helpers (Experience + Education)
#
# None of these hard-code a resume name, city, company, or skill. Each
# signal comes from a model or table that already exists in this file for
# an unrelated purpose:
#   - _get_base_nlp()  -> pretrained GPE/LOC labels (detects ANY place name)
#   - _get_nlp()       -> our own fine-tuned SKILL/DEGREE labels
#   - SECTION_ALIASES  -> the existing section-header table
#   - plain structural checks (length/punctuation), no word lists at all
# so the same logic applies unchanged to any unseen resume.
# ---------------------------------------------------------------------------

def _fragment_matches_ner_label(frag: str, get_model, labels: tuple, threshold: float = 0.6) -> bool:
    """True when `frag` is, character-for-character, mostly covered by an
    entity carrying one of `labels` from the given spaCy pipeline. This is
    the shared primitive behind the location/skill/degree checks below --
    the signal always comes from a model, never from a hard-coded list."""
    frag = frag.strip()
    if not frag:
        return False
    try:
        doc = get_model()(frag)
    except Exception:
        return False
    covered = sum(len(ent.text) for ent in doc.ents if ent.label_ in labels)
    denom = len(frag.replace(" ", "")) or 1
    return (covered / denom) >= threshold


def _looks_like_location_text(frag: str) -> bool:
    """True when `frag` is essentially just a place name and must never be
    accepted as a job title or organization. Uses the pretrained model's
    GPE/LOC label, which generalizes to any city/place -- no fixed list of
    place names."""
    if not frag or len(frag.split()) > 4:
        return False
    return _fragment_matches_ner_label(frag, _get_base_nlp, ("GPE", "LOC"))


def _looks_like_skill_or_degree_fragment(frag: str) -> bool:
    """True when `frag` is mostly a SKILL or DEGREE entity per our own
    fine-tuned NER model -- i.e. it is a technology/skill/certification/
    degree term, not a real job title, organization, or institution name.
    Model-driven, not a hard-coded skill list."""
    if not frag or len(frag.split()) > 6:
        return False
    return _fragment_matches_ner_label(frag, _get_nlp, ("SKILL", "DEGREE"))


def _fragment_tagged_as(frag: str, label: str, threshold: float = 0.6) -> bool:
    """Like _fragment_matches_ner_label but for a single fine-tuned label
    (SKILL or DEGREE individually), used where the two need to be told
    apart -- e.g. an Education degree string SHOULD be tagged DEGREE, and
    it's suspicious specifically when it's tagged SKILL instead."""
    return _fragment_matches_ner_label(frag, _get_nlp, (label,), threshold)


def _looks_like_section_heading_text(frag: str) -> bool:
    """True when `frag` is itself a resume section heading (e.g. "Skills",
    "Projects") rather than a job title/organization/degree/institution.
    Driven entirely by the existing SECTION_ALIASES table, so it
    generalizes across templates instead of listing specific headings."""
    if not frag:
        return False
    cleaned = _clean_header_line(frag)
    if not cleaned:
        return False
    return any(cleaned == alias for alias, _canon in _ALIASES_SORTED)


def _looks_like_weak_fragment(frag: str) -> bool:
    """True when `frag` is too thin -- mostly punctuation/digits or fewer
    than two letters -- to be a credible job title, organization, degree,
    or institution, independent of what the actual words are (purely
    structural, no word list)."""
    stripped = (frag or "").strip()
    if not stripped:
        return True
    if sum(c.isalpha() for c in stripped) < 2:
        return True
    if re.fullmatch(r"[\W\d_]+", stripped):
        return True
    return False


def _experience_entry_is_suspicious(entry: dict) -> bool:
    """General trigger for the Experience LLM fallback: true when a
    deterministically-extracted entry shows any sign of the scrambled/
    two-column failure mode -- a missing role, a missing organization
    alongside a missing date, a role/organization that is actually a
    location, a skill/degree term, a section heading, an implausible
    duplicate of each other, or too weak a fragment to be credible."""
    role = (entry.get("title_or_role") or "").strip()
    org = (entry.get("organization") or "").strip()

    if not role:
        return True
    if not org and not entry.get("start_date"):
        return True
    if role and org and role.lower() == org.lower():
        return True
    for frag in (role, org):
        if not frag:
            continue
        if _looks_like_location_text(frag):
            return True
        if _looks_like_section_heading_text(frag):
            return True
        if _looks_like_skill_or_degree_fragment(frag):
            return True
        if _looks_like_weak_fragment(frag):
            return True
    return False


def _merge_context_blocks(*blocks: str) -> str:
    """Combine multiple text blocks into ONE context string, dropping
    exact-duplicate lines while preserving order. Used so the Experience
    LLM fallback always gets a single, combined context (the detected
    section text plus a date-anchored window over the whole resume) and
    is always called once for the whole resume -- never once per entry.

    Blank lines are preserved rather than stripped, and a separator is
    inserted between each source block. They mark the boundaries between
    distinct job entries (and between the different source blocks being
    merged), which is exactly the grouping signal the Experience prompt
    now relies on -- collapsing every line into one flat stream is what
    let a role from one entry get paired with a nearby entry's
    organization or date."""
    seen = set()
    merged_lines = []
    for block in blocks:
        if not block:
            continue
        if merged_lines and merged_lines[-1] != "":
            merged_lines.append("")
        for line in block.split("\n"):
            clean = line.strip()
            if not clean:
                if merged_lines and merged_lines[-1] != "":
                    merged_lines.append("")
                continue
            if clean not in seen:
                seen.add(clean)
                merged_lines.append(clean)
    return "\n".join(merged_lines).strip("\n")


def _education_field_is_suspicious(text: str) -> bool:
    """General 'does this look wrong for an academic field' check for a
    single degree/field/institution string (or one comma/newline-joined
    part of one): suspicious when empty, when it's itself a section
    heading, or when our fine-tuned model tags it predominantly SKILL
    (i.e. it looks like a technology/skill/certification/project term
    that leaked in) rather than an academic credential."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    if _looks_like_section_heading_text(stripped):
        return True
    if _fragment_tagged_as(stripped, "SKILL"):
        return True
    return False


def _degree_is_suspicious(degree: str) -> bool:
    """True when a degree string doesn't look like a genuine academic
    qualification: empty, a section heading, tagged SKILL by our model,
    or matching neither the existing general degree-phrase regex nor our
    model's own DEGREE label."""
    stripped = (degree or "").strip()
    if _education_field_is_suspicious(stripped):
        return True
    if DEGREE_CORE_RE.search(stripped):
        return False
    if _fragment_tagged_as(stripped, "DEGREE"):
        return False
    return True


def _institution_is_suspicious(institution: str) -> bool:
    """True when an institution string is missing, or contaminated with a
    skill/heading fragment -- checked part-by-part on comma/newline splits
    so PARTIAL contamination (a stray term merged in front of/after a
    genuine institution name) is still caught."""
    stripped = (institution or "").strip()
    if not stripped:
        return True
    parts = [p.strip() for p in re.split(r"[\n,]", stripped) if p.strip()]
    if len(parts) > 1:
        return any(_education_field_is_suspicious(p) for p in parts)
    return _education_field_is_suspicious(stripped)


def _education_entry_is_suspicious(entry: dict) -> bool:
    """General trigger for the Education LLM fallback: true when the
    degree or institution doesn't look genuine -- not just when a field is
    outright empty."""
    return (
        _degree_is_suspicious(entry.get("degree", ""))
        or _institution_is_suspicious(entry.get("institution", ""))
    )


def _clean_contaminated_institution(institution: str) -> str:
    """Strip any comma/newline-joined part of an institution string that
    looks suspicious (per _education_field_is_suspicious), keeping only
    the parts that look like genuine institution text. Returns an empty
    string if nothing credible remains, rather than inventing a value."""
    stripped = (institution or "").strip()
    if not stripped:
        return ""
    parts = [p.strip() for p in re.split(r"[\n,]", stripped) if p.strip()]
    if len(parts) <= 1:
        return "" if _education_field_is_suspicious(stripped) else stripped
    kept = [p for p in parts if not _education_field_is_suspicious(p)]
    return ", ".join(kept) if kept else ""


def _split_education_blocks(section_text: str) -> list[str]:
    """One block per education entry. Blank-line-separated entries are the
    common case; falls back to starting a new block at each line containing
    a degree keyword when the section has no blank-line separation (a
    common compact layout: one degree per line, sometimes with the
    institution/year wrapped onto the very next line)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", section_text) if b.strip()]
    if len(blocks) > 1:
        return blocks

    lines = [l for l in section_text.split("\n") if l.strip()]
    out: list[str] = []
    current: list[str] = []
    for line in lines:
        if DEGREE_CORE_RE.search(line) and current:
            out.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        out.append("\n".join(current))
    return out or ([section_text.strip()] if section_text.strip() else [])


# Generic, template-independent positive evidence that a text fragment
# names an educational institution. Deliberately NOT a list of specific
# institution names (that would be per-resume hardcoding) — just the
# common English institution-type nouns that show up across essentially
# any school/college/university name, in any resume template.
INSTITUTION_INDICATOR_RE = re.compile(
    r"\b(universit(?:y|ies)|colleges?|institutes?|academ(?:y|ies)|schools?|polytechnics?)\b",
    re.IGNORECASE,
)


def _org_entity_is_standalone_in_block(entity_text: str, block: str) -> bool:
    """True when `entity_text` accounts for essentially the whole line it
    appears on, once a trailing date/CGPA/percent/separator is stripped —
    as opposed to being a small fragment embedded inside a much longer,
    unrelated sentence. This is the general signal that separates a
    genuine "Institution, Year" education line (e.g. "IIT Hyderabad,
    2022-2024") from a term that merely happens to get NER-tagged ORG
    inside a project/skill sentence (e.g. "Random Forest" inside
    "Compared Logistic Regression, Random Forest, and XGBoost")."""
    entity_text = entity_text.strip()
    if not entity_text:
        return False
    for line in block.split("\n"):
        line = line.strip()
        if entity_text not in line:
            continue
        remainder = YEAR_RANGE_RE.sub("", line)
        remainder = YEAR_RE.sub("", remainder)
        remainder = CGPA_RE.sub("", remainder)
        remainder = PERCENT_RE.sub("", remainder)
        remainder = remainder.strip(" ,.;|-\u2013\u2014")
        if not remainder:
            continue
        if len(entity_text) >= 0.6 * len(remainder):
            return True
    return False


def _looks_like_institution(frag: str, org_ents: list[str], block: str = "") -> bool:
    """Positive-evidence gate. A fragment/entity is only trusted as an
    institution when there is reasonable evidence it names one. A base
    model ORG tag ALONE is deliberately not sufficient (small NER models
    routinely mistag ML/domain terms as ORG) — an ORG match is only
    accepted alongside a common institution-type noun (University/
    College/Institute/Academy/School/Polytechnic), or when the entity
    stands essentially alone on its own line rather than being a
    fragment inside a longer, unrelated sentence. Fragments that merely
    survive the negative checks upstream (not a date, not the
    degree/field, not a CGPA/percent) are NOT sufficient evidence on
    their own."""
    frag = frag.strip()
    if not frag:
        return False
    if INSTITUTION_INDICATOR_RE.search(frag):
        return True
    if block and any(frag.lower() == o.lower() for o in org_ents) \
            and _org_entity_is_standalone_in_block(frag, block):
        return True
    return False


def _parse_education_block(block: str, org_ents: list[str]) -> dict | None:
    m = DEGREE_CORE_RE.search(block)
    if not m:
        return None
    degree_text = m.group(0).strip(" .,-")
    if not degree_text:
        return None

    tail = block[m.end():]
    field = ""
    consumed_end = 0
    fm = FIELD_AFTER_DEGREE_RE.match(tail)
    if fm:
        candidate_field = fm.group(1).strip(" .,-")
        if candidate_field and not _looks_like_date_range_text(candidate_field) \
                and not re.search(r"\b(university|institute|college)\b", candidate_field, re.IGNORECASE):
            field = candidate_field
            consumed_end = fm.end()
    remainder = tail[consumed_end:].strip(" ,.-")

    # Year range / graduation year — search the WHOLE block (not just the
    # degree line), since "Degree\nInstitution\nYear" layouts put the year
    # on its own line.
    start_year = None
    end_year = None
    status = ""
    yr = YEAR_RANGE_RE.search(block)
    if yr:
        start_year = int(yr.group(1))
        end_token = yr.group(2)
        if end_token.lower() in ("present", "current", "ongoing"):
            status = "ongoing"
        else:
            end_year = int(end_token)
    else:
        ym = YEAR_RE.search(block)
        if ym:
            end_year = int(ym.group(0))

    if status != "ongoing":
        ref_year = end_year or start_year
        if ref_year:
            status = "ongoing" if ref_year > date.today().year else "completed"

    # Institution: prefer a base-model ORG entity found anywhere in the
    # block that isn't just the degree phrase or field itself.
    institution = next(
        (o for o in org_ents
         if o in block
         and o.lower() not in degree_text.lower()
         and degree_text.lower() not in o.lower()
         and (not field or o.lower() != field.lower())
         and not _looks_like_date_range_text(o)
         and _looks_like_institution(o, org_ents, block)),
        "",
    )
    if not institution:
        # Fallback across every remaining line/fragment of the block —
        # take the first piece of text that isn't the degree/field, isn't
        # empty, and critically ISN'T a date or date range (this is the
        # direct fix for "institution" being assigned "2023 – 2027": a
        # bare year range now fails `_looks_like_date_range_text` and is
        # skipped instead of accepted).
        candidates = []
        if remainder:
            candidates.extend(remainder.split(","))
        for line in block.split("\n"):
            if line.strip() and line.strip() not in (degree_text, field):
                candidates.append(line)
        for frag in candidates:
            frag = frag.strip(" |-\t")
            if not frag or frag == degree_text or frag == field:
                continue
            if degree_text.lower() in frag.lower() and len(frag) < len(degree_text) + 5:
                continue
            if _looks_like_date_range_text(frag):
                continue
            if CGPA_RE.fullmatch(frag) or PERCENT_RE.fullmatch(frag):
                continue
            if not _looks_like_institution(frag, org_ents,block):
                continue
            institution = frag
            break

    cgpa = None
    cgpa_m = CGPA_RE.search(block)
    if cgpa_m:
        try:
            cgpa = float(cgpa_m.group(1))
        except ValueError:
            cgpa = None

    percentage = None
    pct_m = PERCENT_RE.search(block)
    if pct_m:
        try:
            percentage = float(pct_m.group(1))
        except ValueError:
            percentage = None

    return {
        "degree": degree_text,
        "field": field,
        "institution": institution,
        "start_year": start_year,
        "end_year": end_year,
        "status": status,
        "cgpa": cgpa,
        "percentage": percentage,
        # Backward-compatible single "year" field (older code/templates
        # may still read this) — the graduation/end year, or start year
        # if that's all we have.
        "year": str(end_year) if end_year else (str(start_year) if start_year else ""),
    }


def extract_education_entries(section_text: str) -> list[dict]:
    if not section_text:
        return []
    try:
        org_ents = [ent.text for ent in _get_base_nlp()(section_text).ents if ent.label_ == "ORG"]
    except Exception:
        org_ents = []

    entries = []
    seen = set()
    for block in _split_education_blocks(section_text):
        parsed = _parse_education_block(block, org_ents)
        if not parsed:
            continue
        key = (parsed["degree"].lower(), parsed["field"].lower(), parsed["institution"].lower())
        if key in seen:
            continue
        seen.add(key)
        entries.append(parsed)
    return entries


def _extract_education_ner_fallback(doc) -> list[dict]:
    """Last-resort path for resumes with no detectable Education section
    and no text matching a known degree keyword: fall back to the
    fine-tuned model's DEGREE entity label, filtered the same way the
    original parser did. Emits the same field shape as
    extract_education_entries() so downstream code doesn't need to special
    case which path produced an entry."""
    suppress_spans = _org_gpe_spans(doc.text)
    entries = []
    seen = set()
    for ent in doc.ents:
        if ent.label_ != "DEGREE":
            continue
        cleaned = ent.text.strip()
        lower = cleaned.lower()
        tokens = lower.split()
        if any(t in DEGREE_BLOCKLIST_TOKENS for t in tokens):
            continue
        if lower in SKILL_BLOCKLIST:
            continue
        deg_tokens = set(re.split(r"[\s\-]+", lower)) - {""}
        if deg_tokens & SKILL_BLOCKLIST:
            continue
        if len(cleaned) < 2 or "\n" in cleaned or len(cleaned) > 45:
            continue
        if re.fullmatch(r"[\d.%\s]+", cleaned):
            continue
        if _overlaps((ent.start_char, ent.end_char), suppress_spans):
            continue
        if lower not in seen:
            seen.add(lower)
            entries.append({
                "degree": cleaned, "field": "", "institution": "",
                "start_year": None, "end_year": None, "status": "",
                "cgpa": None, "percentage": None, "year": "",
            })
    return entries


def format_education(entries: list[dict]) -> str:
    if not entries:
        return "Not detected"
    parts = []
    for e in entries:
        p = e.get("degree", "").strip()
        if not p:
            continue
        if e.get("field"):
            p += f" in {e['field']}"
        if e.get("institution"):
            p += f" - {e['institution']}"
        years = ""
        if e.get("start_year") and e.get("end_year"):
            years = f" ({e['start_year']}-{e['end_year']})"
        elif e.get("end_year"):
            years = f" ({e['end_year']})"
        elif e.get("year"):
            years = f" ({e['year']})"
        p += years
        if e.get("cgpa") is not None:
            p += f", CGPA {e['cgpa']}"
        elif e.get("percentage") is not None:
            p += f", {e['percentage']}%"
        if p not in parts:
            parts.append(p)
    return "; ".join(parts) if parts else "Not detected"


# ---------------------------------------------------------------------------
# Experience: date-range parsing, overlap-safe duration, structured entries
# ---------------------------------------------------------------------------

EXPERIENCE_YEAR_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", re.IGNORECASE)

MONTH_PAT = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
MONTHS_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
DATE_RANGE_RE = re.compile(
    r"(?P<m1>" + MONTH_PAT + r")?\.?\s*(?P<y1>\d{4})\s*"
    r"(?:-|–|—|to)\s*"
    r"(?P<m2>" + MONTH_PAT + r")?\.?\s*(?P<y2>\d{4}|present|current|ongoing|now|till\s*date|to\s*date)",
    re.IGNORECASE,
)


def _month_num(m: str) -> int:
    if not m:
        return 1
    return MONTHS_MAP.get(m.lower().rstrip("."), 1)


def find_date_ranges(text: str) -> list[tuple[date, date]]:
    if not text:
        return []
    today = date.today()
    ranges = []
    for m in DATE_RANGE_RE.finditer(text):
        y1, y2 = m.group("y1"), m.group("y2")
        if not y1:
            continue
        try:
            start = date(int(y1), _month_num(m.group("m1")), 1)
        except ValueError:
            continue
        if re.match(r"present|current|ongoing|now|till|to\s*date", y2, re.IGNORECASE):
            end = date(today.year, today.month, 1)
        else:
            try:
                end = date(int(y2), _month_num(m.group("m2")), 1)
            except ValueError:
                continue
        if end < start:
            continue
        ranges.append((start, end))
    return ranges


def merge_and_sum_years(ranges: list[tuple[date, date]]) -> float:
    """Sums total duration across date ranges, merging any that overlap so
    concurrent/overlapping roles aren't double-counted."""
    if not ranges:
        return 0.0
    ranges = sorted(ranges, key=lambda r: r[0])
    merged = [list(ranges[0])]
    for s, e in ranges[1:]:
        last = merged[-1]
        if s <= last[1]:
            if e > last[1]:
                last[1] = e
        else:
            merged.append([s, e])
    total_days = sum((e - s).days for s, e in merged)
    return round(total_days / 365.25, 1)


def merge_and_sum_months(ranges: list[tuple[date, date]]) -> int:
    """Same overlap-safe merge as merge_and_sum_years(), but returns whole
    months using month-index arithmetic (year*12 + month) instead of a
    365.25-day approximation — this is what problem statement §7's
    `experience_months` is meant to be precise about."""
    if not ranges:
        return 0
    intervals = sorted(
        (s.year * 12 + s.month, e.year * 12 + e.month) for s, e in ranges
    )
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        last = merged[-1]
        if s <= last[1] + 1:  # overlapping or contiguous
            if e > last[1]:
                last[1] = e
        else:
            merged.append([s, e])
    return sum(e - s + 1 for s, e in merged)


def extract_experience_years_keyword(text: str) -> float:
    matches = EXPERIENCE_YEAR_PATTERN.findall(text)
    return max((float(m) for m in matches), default=0.0)


_RESEARCH_TYPE_RE = re.compile(r"\bresearch\b", re.IGNORECASE)
_INTERNSHIP_TYPE_RE = re.compile(r"\b(?:intern(?:ship)?|trainee)\b", re.IGNORECASE)
_PART_TIME_TYPE_RE = re.compile(r"\bpart[\s\-]?time\b", re.IGNORECASE)
_FULL_TIME_TYPE_RE = re.compile(r"\bfull[\s\-]?time\b", re.IGNORECASE)
_ROLE_WORD_RE = re.compile(
    r"\b(engineer|developer|analyst|manager|consultant|associate|designer|"
    r"architect|lead|scientist|specialist|administrator|programmer)\b",
    re.IGNORECASE,
)


def _infer_experience_type(role: str, org: str, details_text: str) -> str:
    """internship|full-time|part-time|research|unknown — a per-entry
    classification (problem statement §6/§7: internships and research
    roles must not silently be counted as ordinary full-time experience)."""
    combined = f"{role} {org} {details_text}"
    if _RESEARCH_TYPE_RE.search(role) or _RESEARCH_TYPE_RE.search(org):
        return "research"
    if _INTERNSHIP_TYPE_RE.search(role) or _INTERNSHIP_TYPE_RE.search(org):
        return "internship"
    if _PART_TIME_TYPE_RE.search(combined):
        return "part-time"
    if _FULL_TIME_TYPE_RE.search(combined) or _ROLE_WORD_RE.search(role):
        return "full-time"
    return "unknown"


def _split_role_and_org(header: str, org_ents: list[str]) -> tuple[str, str]:
    """Resumes overwhelmingly format a job header as 'Role, Company',
    'Role | Company', 'Role at Company', or 'Role — Company'. That
    delimiter split is a far more reliable way to tell role from
    organization than trusting spaCy's ORG label -- the base model
    quite often mistags a short/ambiguous word (e.g. "UI" inside
    "UI/UX Intern") as ORG. NER is therefore only used as a FALLBACK
    when the delimiter split doesn't find an organization at all, never
    as an override of a split that already worked -- and even then,
    a candidate that's just a substring of the role, or too short to be
    a credible name, is rejected."""
    header = header.strip(" -|,–—\t")
    parts = re.split(r"\s*(?:\||,|–|—| at )\s*", header)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) >= 2:
        role, org = parts[0], parts[1]
    else:
        # No delimiter present, so this is a single, undivided header
        # fragment. It defaults to being the role (the historically
        # common case: the line right next to a date is usually the job
        # title), UNLESS it carries a clear organization-type signal (an
        # "Analytics"/"Solutions"/"Technologies"-style suffix) and no
        # role-type word at all -- otherwise a company name that happens
        # to be the ONLY header line available (its own role sitting on a
        # separate, non-adjacent line) would silently get written into
        # the role slot instead of the organization slot.
        if header and _ORG_SUFFIX_HINT_RE.search(header) and not _ROLE_WORD_RE.search(header):
            role, org = "", header
        else:
            role, org = header, ""

    if not org:
        for cand in org_ents:
            cand = cand.strip()
            if len(cand) < 3:
                continue
            if role and cand.lower() in role.lower():
                continue  # substring of the role, not a real org guess
            if cand in header:
                org = cand
                break
    return role, org


def _build_experience_context(
    text: str,
    lines_before: int = 5,
    lines_after: int = 5,
    max_lines_before: int = 20,
    max_lines_after: int = 20,
) -> str:
    """Build a context window around each detected experience date range.

    The window is no longer bounded ONLY by a fixed line count in each
    direction -- it also stops at genuine structural boundaries, so it
    reliably captures a full job entry (role, organization, location,
    date, description) without bleeding into an unrelated section or
    into the NEXT job:
      - a detected section heading (Education, Projects, Skills, ...),
        via the existing _detect_section_headers()
      - the start of another date range (the next/previous job's own
        header line)
      - two or more consecutive blank lines (a paragraph/entry break)
    `lines_before`/`lines_after` are still honored as a minimum before any
    of those stop conditions kick in, and `max_lines_before`/
    `max_lines_after` remain a hard ceiling so a resume with no headings
    or blank lines at all still can't pull in the whole document.

    Each date-anchored window is kept as its own block, separated from
    the next by a blank line, rather than flattened into one
    undifferentiated stream of lines. When a resume has more than one
    job, that blank line is the single strongest cue available for
    "these lines are one entry, those lines are another" -- collapsing it
    away is what let one entry's role/organization get associated with a
    neighboring entry's date."""
    if not text:
        return ""

    lines = text.split("\n")
    heading_lines = {i for i, _ in _detect_section_headers(lines)}
    date_lines = {i for i, line in enumerate(lines) if DATE_RANGE_RE.search(line)}

    windows = []
    for idx in sorted(date_lines):
        # Expand backward from the date line.
        start = idx
        blanks = 0
        while start > 0 and (idx - start) < max_lines_before:
            prev = start - 1
            if prev in heading_lines:
                break
            if (idx - start) >= lines_before:
                if prev in date_lines:
                    break
                if not lines[prev].strip():
                    blanks += 1
                    if blanks >= 2:
                        break
                else:
                    blanks = 0
            start = prev

        # Expand forward from the date line.
        end = idx + 1
        blanks = 0
        while end < len(lines) and (end - idx) <= max_lines_after:
            if end in heading_lines:
                break
            if (end - idx) > lines_after:
                if end in date_lines:
                    break
                if not lines[end].strip():
                    blanks += 1
                    if blanks >= 2:
                        break
                else:
                    blanks = 0
            end += 1

        windows.append(lines[start:end])

    if not windows:
        return ""

    seen = set()
    blocks = []
    for window in windows:
        block_lines = []
        for line in window:
            clean = line.strip()
            if clean and clean not in seen:
                seen.add(clean)
                block_lines.append(clean)
        if block_lines:
            blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks)


def _validate_experience_entries(entries: list[dict]) -> list[dict]:
    """Shared semantic validation gate for EVERY experience entry,
    regardless of whether it came from the LLM or the deterministic
    fallback (problem statement §C/§D: deterministic output must pass
    through the same validation as the LLM's, never straight into the
    final result).

    Per §E, a legitimate entry does not need every field -- role,
    organization, AND dates are each individually optional -- so this
    clears (rather than outright drops) a field that fails a quality
    check, and only rejects the whole entry when NEITHER role nor
    organization survives (a bare date with no credible identity signal
    is not experience on its own)."""
    valid = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or entry.get("title_or_role") or "").strip()
        org = str(entry.get("organization") or "").strip()
        start_date = entry.get("start_date")
        end_date = entry.get("end_date")

        if role and org and role.lower() == org.lower():
            org = ""  # can't both be the same string; keep the one, drop the dup

        def _bad(frag: str) -> bool:
            return (
                _looks_like_location_text(frag)
                or _looks_like_section_heading_text(frag)
                or _looks_like_skill_or_degree_fragment(frag)
                or _looks_like_institution(frag, [], block=frag)
                or _looks_like_weak_fragment(frag)
            )

        if role and _bad(role):
            role = ""
        if org and _bad(org):
            org = ""

        # Need at least one credible identity signal to be genuine
        # employment/research experience -- a date range alone is not
        # enough (problem statement: "Projects / 2023" must not become
        # an experience entry just because a year appears).
        if not role and not org:
            continue

        if start_date and not re.fullmatch(r"\d{4}-\d{2}", str(start_date)):
            start_date = None
        if end_date and not re.fullmatch(r"\d{4}-\d{2}", str(end_date)):
            end_date = None

        status = entry.get("status")
        if status not in {"completed", "ongoing", "unknown"}:
            status = "unknown"
        experience_type = entry.get("experience_type")
        if experience_type not in {"full-time", "part-time", "internship", "research", "unknown"}:
            experience_type = _infer_experience_type(role, org, " ".join(entry.get("details") or []))

        cleaned = dict(entry)
        cleaned["role"] = role
        cleaned["organization"] = org
        cleaned["title_or_role"] = role or entry.get("title_or_role", "") or org
        cleaned["start_date"] = start_date
        cleaned["end_date"] = end_date
        cleaned["status"] = status
        cleaned["experience_type"] = experience_type
        valid.append(cleaned)
    return valid


def _experience_date_key(entry: dict) -> tuple[int, int] | None:
    """Parse an entry's start_date (YYYY-MM, as produced by both the LLM
    and deterministic paths after validation) into a sortable (year,
    month) tuple, or None if missing/unparseable. Used only to judge date
    PROXIMITY between two already-extracted entries -- never to invent or
    guess a date."""
    start = (entry.get("start_date") or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})", start)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _experience_fields_conflict(entry: dict, candidate: dict) -> bool:
    """True when `entry` and `candidate` already disagree on a field both
    have filled in -- a strong signal they describe two DIFFERENT jobs.
    A candidate that conflicts this way must never be used to backfill
    `entry`, even if some weaker signal (e.g. a coincidentally close
    date) would otherwise suggest a match. This is the safeguard against
    ever merging two distinct jobs into one."""
    for field in ("role", "organization"):
        a = (entry.get(field) or "").strip().lower()
        b = (candidate.get(field) or "").strip().lower()
        if a and b and a != b:
            return True
    return False


def _match_deterministic_experience_entry(
    entry: dict, deterministic_entries: list[dict], used: set
) -> tuple[int | None, dict | None]:
    """Find the deterministic-parser entry that most likely describes the
    SAME job as `entry`, so a missing field can be recovered from it.

    Tried in order of how strong the identity evidence is -- start_date
    alone is not always reliable (two different resumes, or even two
    entries in the same resume, can share a start_date, and a scrambled
    layout can shift which date line an entry gets anchored to), so this
    now falls through a small hierarchy instead of relying on start_date
    exclusively:

      1. exact start_date match
      2. exact end_date match
      3. an exact, already-shared role string
      4. an exact, already-shared organization string
      5. last resort -- the single closest start_date within the same
         month, but ONLY when exactly one unclaimed candidate is that
         close; with more than one equally-close candidate there is no
         reliable way to tell which job it belongs to, so nothing is
         returned rather than guessing.

    At every tier, any candidate that already disagrees with `entry` on a
    field both have filled in is excluded up front -- that is what stops
    two different jobs from ever being merged, regardless of which tier
    produced the match."""
    candidates = [
        (idx, det) for idx, det in enumerate(deterministic_entries)
        if idx not in used and not _experience_fields_conflict(entry, det)
    ]
    if not candidates:
        return None, None

    target_start = (entry.get("start_date") or "").strip()
    if target_start:
        for idx, det in candidates:
            if (det.get("start_date") or "").strip() == target_start:
                return idx, det

    target_end = (entry.get("end_date") or "").strip()
    if target_end:
        for idx, det in candidates:
            if (det.get("end_date") or "").strip() == target_end:
                return idx, det

    entry_role = (entry.get("role") or "").strip().lower()
    if entry_role:
        for idx, det in candidates:
            if (det.get("role") or "").strip().lower() == entry_role:
                return idx, det

    entry_org = (entry.get("organization") or "").strip().lower()
    if entry_org:
        for idx, det in candidates:
            if (det.get("organization") or "").strip().lower() == entry_org:
                return idx, det

    entry_key = _experience_date_key(entry)
    if entry_key is not None:
        close = []
        for idx, det in candidates:
            det_key = _experience_date_key(det)
            if det_key is None:
                continue
            months_apart = abs((entry_key[0] - det_key[0]) * 12 + (entry_key[1] - det_key[1]))
            if months_apart <= 1:
                close.append((idx, det))
        if len(close) == 1:
            return close[0]

    return None, None


def _backfill_missing_experience_fields(
    entries: list[dict], deterministic_entries: list[dict]
) -> list[dict]:
    """Recover a missing role or organization on an otherwise-credible
    entry from the deterministic parser's output for the same job, when
    one is available. This targets the specific generalized failure mode
    reported for this parser: the LLM extraction correctly identifies
    SOME of an entry's fields but leaves role or organization empty
    because the two were not adjacent in the scrambled PDF text, while
    the deterministic parser's line-proximity heuristics happened to
    recover the missing one (or vice versa).

    This only ever fills a field that is currently empty -- it never
    overwrites a value the primary extraction already produced, and it
    never invents a value: the recovered text must already have survived
    the exact same semantic validation (_validate_experience_entries)
    that gates every other entry, so a location/skill/degree fragment
    still cannot enter through this path."""
    if not entries or not deterministic_entries:
        return entries

    used: set = set()
    for entry in entries:
        role = (entry.get("role") or "").strip()
        org = (entry.get("organization") or "").strip()
        if role and org:
            continue  # nothing missing to recover

        idx, match = _match_deterministic_experience_entry(entry, deterministic_entries, used)
        if match is None:
            continue
        used.add(idx)

        # The deterministic parser can itself mix up role and organization
        # on the very same scrambled layouts this backfill targets (e.g.
        # reading the line just above a date as the role when it was
        # actually the organization). Guard against propagating that: a
        # recovered value is only trusted when it does NOT collide with
        # the field already established on this entry -- otherwise the
        # backfill would just duplicate the known organization into the
        # role slot (or vice versa), reintroducing the exact "location/
        # wrong-field became the role" failure mode the parser exists to
        # prevent.
        if not role:
            recovered_role = (match.get("role") or "").strip()
            if recovered_role and recovered_role.lower() != org.lower():
                entry["role"] = recovered_role
                entry["title_or_role"] = recovered_role

        if not org:
            recovered_org = (match.get("organization") or "").strip()
            if recovered_org and recovered_org.lower() != role.lower():
                entry["organization"] = recovered_org

    return entries


_HEADER_DELIMITER_RE = re.compile(r"\s*(?:\||,|–|—| at )\s*")
_ORG_SUFFIX_HINT_RE = re.compile(
    r"\b(inc|llc|ltd|limited|technologies|solutions|systems|labs|corp|"
    r"group|studio|analytics|consulting|industries|enterprises)\b",
    re.IGNORECASE,
)


def _line_looks_like_strong_header(line: str) -> bool:
    """True when `line` has real structural evidence of being a role/org
    header -- a role-type word, an org-type suffix, or a 'Role — Org'/
    'Role | Org' style two-part split -- as opposed to a bare one- or
    two-word fragment that merely survived the (imperfect, especially on
    short/context-free strings) NER location check."""
    if not line:
        return False
    if _ROLE_WORD_RE.search(line):
        return True
    if _ORG_SUFFIX_HINT_RE.search(line):
        return True
    parts = [p for p in _HEADER_DELIMITER_RE.split(line) if p.strip()]
    return len(parts) >= 2 and all(len(p.strip()) >= 3 for p in parts)


def _is_thin_fragment(frag: str) -> bool:
    """True for a bare one/two-word fragment with no internal structure
    (e.g. a lone city or 'Remote') -- exactly the shape that both a real
    short organization name AND a location squeezed onto the date line
    can take, so it's treated as weak evidence either way and a strong
    nearby header line is preferred over it when one exists."""
    frag = (frag or "").strip()
    if not frag:
        return True
    return len(frag.split()) <= 2 and not _HEADER_DELIMITER_RE.search(frag)


def _usable_header_fragment(cand: str) -> bool:
    """True when `cand` is plausible as a role/organization header
    fragment -- i.e. NOT empty, NOT just a location, and NOT too weak/
    thin a fragment to be credible. Used to decide whether inline text
    next to a date is trustworthy, or whether the real header must be
    recovered from a nearby line instead."""
    cand = (cand or "").strip()
    if not cand:
        return False
    if _looks_like_date_range_text(cand):
        return False
    if _looks_like_location_text(cand):
        return False
    if _looks_like_weak_fragment(cand):
        return False
    return True


def _trustworthy_header_fragment(cand: str) -> bool:
    """Stricter than _usable_header_fragment: true only when `cand` is
    both usable AND either not a bare one/two-word fragment, or has real
    structural evidence of being a role/org header. This exists because
    the location check inside _usable_header_fragment is NER-based and
    therefore unreliable on short, obscure, or otherwise-uncommon place
    names (a small pretrained model may recognize "Mumbai" but miss
    "Pune" or "Bangalore" entirely, purely as a function of its training
    data). A thin fragment that survives the location check only because
    the model happened to miss it is NOT enough evidence to trust as a
    role or organization -- it takes either more content, or an actual
    role-word/org-suffix/delimiter signal, before it's used as a header."""
    if not _usable_header_fragment(cand):
        return False
    return not _is_thin_fragment(cand) or _line_looks_like_strong_header(cand)


def extract_experience_entries(section_text: str) -> list[dict]:
    if not section_text:
        return []
    try:
        org_ents = [ent.text for ent in _get_base_nlp()(section_text).ents if ent.label_ == "ORG"]
    except Exception:
        org_ents = []

    today = date.today()
    entries = []
    current = None
    lines = section_text.split("\n")
    # Lines consumed by the forward lookahead below (used to fill a role
    # or organization that sits AFTER the date line) so they are not also
    # re-read as a bullet detail, or re-claimed as the NEXT entry's
    # candidate_prev header.
    consumed_indices: set[int] = set()

    for line_idx, raw_line in enumerate(lines):
        if line_idx in consumed_indices:
            continue
        stripped = raw_line.strip()
        if not stripped:
            continue

        date_match = DATE_RANGE_RE.search(stripped)
        if date_match:
            prefix = stripped[:date_match.start()].strip(" -|,–—\t")
            suffix = stripped[date_match.end():].strip(" -|,–—\t")
            inline = prefix or suffix

            # Peek at the nearest candidate "previous header line" WITHOUT
            # consuming it yet, so it can be compared against the inline
            # text before deciding which one to actually use.
            candidate_prev = None
            if current is not None and current.get("details"):
                p = current["details"][-1].strip()
                if p and not DATE_RANGE_RE.fullmatch(p):
                    candidate_prev = p
            if candidate_prev is None:
                for pidx in range(line_idx - 1, -1, -1):
                    if pidx in consumed_indices:
                        continue
                    previous = lines[pidx].strip()
                    if not previous or DATE_RANGE_RE.fullmatch(previous):
                        continue
                    candidate_prev = previous
                    break

            # The text next to the date on THIS line is only trustworthy
            # as the role/org header when it's more than a bare, thin
            # fragment (a single short word like "Mumbai"/"Pune"/"Remote"
            # has no internal structure to tell a location apart from a
            # short org name -- spaCy's location tagger is also
            # unreliable on such short, context-free strings, and misses
            # many real place names entirely depending on its training
            # data). Whenever a nearby line has REAL structural evidence
            # of being the actual role/org header (a role word, an
            # org-type suffix, or a 'Role — Org' split), prefer that over
            # a thin inline fragment.
            #
            # When NEITHER side clears that stricter bar -- e.g. the date
            # sits alone on its own line (no usable inline text at all)
            # and the nearest previous line is itself just a short,
            # unrecognized fragment -- neither is trusted as the header.
            # Guessing here is exactly how a city like "Pune" (which this
            # small NER model, unlike "Mumbai", does not tag as a
            # location) would end up written into the role field. The
            # header is left empty instead, and the forward lookahead
            # below (which looks past the date for a role/org-shaped
            # line) plus downstream validation/backfill are what recover
            # the real value.
            trustworthy_prev = candidate_prev is not None and _trustworthy_header_fragment(candidate_prev)
            trustworthy_inline = _trustworthy_header_fragment(inline)

            use_prev = False
            if trustworthy_prev and _is_thin_fragment(inline):
                use_prev = True
            elif trustworthy_prev and not trustworthy_inline:
                use_prev = True

            if use_prev:
                header = candidate_prev
                if current is not None and current.get("details") and current["details"][-1].strip() == candidate_prev:
                    current["details"].pop()
            elif trustworthy_inline:
                header = inline
            else:
                # Neither side is trustworthy enough on its own -- leave
                # the header empty rather than guess with a weak or
                # unrecognized fragment. The forward lookahead below and
                # downstream validation/backfill recover the real
                # role/organization from elsewhere in the text instead.
                header = ""

            if current:
                entries.append(current)

            role, org = _split_role_and_org(header, org_ents)

            # Date/date-ranges must never become role, title, or organization.
            if _looks_like_date_range_text(role):
                role = ""
            if _looks_like_date_range_text(org):
                org = ""

            # Forward lookahead: the header only captured what was BEFORE
            # (or inline with) the date. Many resumes put the
            # complementary field -- whichever of role/organization is
            # still missing -- on one of the next few lines instead, e.g.
            # "Company\nAug 2024 - Present\nRole" or "Role\nDate\nCompany".
            # Mirrors the candidate_prev search above but looks forward,
            # and only ever fills a field the header genuinely didn't
            # supply -- it never overrides role/org already found above.
            if not role or not org:
                budget = 3
                fidx = line_idx + 1
                while fidx < len(lines) and budget > 0 and (not role or not org):
                    fwd_raw = lines[fidx]
                    fwd = fwd_raw.strip()
                    if not fwd:
                        fidx += 1
                        continue
                    if DATE_RANGE_RE.search(fwd):
                        break  # next entry has already started
                    if fwd_raw.strip().startswith(("-", "•", "*")):
                        break  # unambiguous bullet/detail content
                    budget -= 1
                    if _usable_header_fragment(fwd):
                        is_role_like = bool(_ROLE_WORD_RE.search(fwd))
                        is_org_like = bool(
                            _ORG_SUFFIX_HINT_RE.search(fwd) or fwd in org_ents
                        )
                        if not role and is_role_like and not is_org_like:
                            role = fwd
                            consumed_indices.add(fidx)
                        elif not org and is_org_like and not is_role_like:
                            org = fwd
                            consumed_indices.add(fidx)
                    fidx += 1

            y1, y2 = date_match.group("y1"), date_match.group("y2")
            start_date = end_date = None
            status = "unknown"
            duration_months = None
            if y1:
                try:
                    start_dt = date(int(y1), _month_num(date_match.group("m1")), 1)
                    start_date = f"{start_dt.year:04d}-{start_dt.month:02d}"
                except ValueError:
                    start_dt = None
                if start_dt:
                    if re.match(r"present|current|ongoing|now|till\s*date|to\s*date", y2, re.IGNORECASE):
                        status = "ongoing"
                        end_date = None
                        duration_months = merge_and_sum_months(
                            [(start_dt, date(today.year, today.month, 1))]
                        )
                    else:
                        try:
                            end_dt = date(int(y2), _month_num(date_match.group("m2")), 1)
                            if end_dt >= start_dt:
                                end_date = f"{end_dt.year:04d}-{end_dt.month:02d}"
                                status = "completed"
                                duration_months = merge_and_sum_months([(start_dt, end_dt)])
                        except ValueError:
                            pass

            current = {
                # -- backward-compatible fields --
                "title_or_role": role,
                "organization": org,
                "duration": date_match.group(0).strip(),
                "details": [],
                # -- new structured fields --
                "role": role,
                "start_date": start_date,
                "end_date": end_date,
                "status": status,
                "experience_type": "unknown",  # filled in once details are known
                "duration_months": duration_months,
            }
        else:
            clean = stripped.strip("-•*\t ")
            if current is not None and clean and clean.lower() not in SKILL_BLOCKLIST:
                current["details"].append(clean)

    if current:
        entries.append(current)
    for e in entries:
        e["details"] = e["details"][:4]
        e["experience_type"] = _infer_experience_type(
            e["title_or_role"], e["organization"], " ".join(e["details"])
        )
    return entries[:10]


def build_experience_summary(experience_years: float, has_date_ranges: bool,
                              has_keyword_years: bool, entries: list[dict], orgs: list[str]) -> str:
    if has_date_ranges:
        header = f"{experience_years} years of experience (calculated from listed date ranges)."
    elif has_keyword_years:
        header = f"{experience_years} years of experience mentioned."
    else:
        header = "No explicit years of experience found; inferred from listed roles."

    if entries:
        parts = []
        for e in entries[:4]:
            role = e["title_or_role"]
            org = f" at {e['organization']}" if e["organization"] else ""
            dur = f" ({e['duration']})" if e["duration"] else ""
            parts.append(f"{role}{org}{dur}")
        return header + " " + " / ".join(parts)

    if orgs:
        return header + f" Organizations mentioned: {', '.join(orgs[:4])}."
    return header


# ---------------------------------------------------------------------------
# Projects / certifications / achievements / research
# ---------------------------------------------------------------------------

def _looks_like_title_line(clean: str) -> bool:
    """Heuristic for whether a non-bulleted line starts a NEW
    project/certification/achievement entry, versus being a wrapped
    continuation line of the previous one's description. Continuation
    text produced by line-wrapping overwhelmingly (a) starts with a
    lowercase letter, (b) ends with sentence-ending punctuation, or
    (c) runs on like a full sentence — real titles very rarely do any of
    these (problem statement §8/§9/§10: "details.", "automated",
    "attendance marking." wrongly becoming their own entries)."""
    if not clean:
        return False
    first_alpha = next((c for c in clean if c.isalpha()), "")
    if first_alpha and first_alpha.islower():
        return False
    if clean[-1] in ".!?":
        return False
    if len(clean) > 100 or len(clean.split()) > 12:
        return False
    return True


def _split_blocks_with_continuations(section_text: str) -> list[dict]:
    """Groups a section's lines into blocks of
    {"title": str, "lines": [continuation str, ...]} so wrapped
    continuation lines stay attached to the entry they belong to instead
    of becoming spurious separate entries.

    Rule: a bulleted/numbered line is a detail of the current block (or
    starts the first block if none exists yet). A non-bulleted line
    starts a NEW block only when it looks title-shaped
    (_looks_like_title_line); otherwise it's a continuation of the
    current block's description."""
    if not section_text:
        return []
    lines = [l.strip() for l in section_text.split("\n") if l.strip()]
    blocks: list[dict] = []
    current = None
    for line in lines:
        is_bullet = bool(re.match(r"^[\-•*◦]\s", line)) or bool(re.match(r"^\d+[.)]\s", line))
        clean = re.sub(r"^[\-•*◦]\s*", "", line)
        clean = re.sub(r"^\d+[.)]\s*", "", clean).strip()
        if not clean:
            continue
        if is_bullet:
            if current is None:
                current = {"title": clean, "lines": []}
            else:
                current["lines"].append(clean)
        else:
            if current is None or _looks_like_title_line(clean):
                if current:
                    blocks.append(current)
                current = {"title": clean, "lines": []}
            else:
                current["lines"].append(clean)
    if current:
        blocks.append(current)
    return blocks


_TRAILING_YEAR_RE = re.compile(r"[\(\-,]?\s*((?:19|20)\d{2})\s*\)?\s*$")


_PROJECT_DESCRIPTION_START_RE = re.compile(
    r"^\s*(?:built|developed|created|implemented|designed|this\s+project|the\s+project|"
    r"used|handled|worked|developing|working)\b",
    re.IGNORECASE,
)
_PROJECT_TITLE_HINT_RE = re.compile(
    r"\b(?:system|predictor|application|platform|website|app|detection|attendance|chatbot)\b",
    re.IGNORECASE,
)


def _looks_like_project_title_line(clean: str) -> bool:
    """Project-specific title heuristic; description/sentence lines win over
    generic title-shape checks so wrapped descriptions stay with their project."""
    if not clean:
        return False
    if _PROJECT_DESCRIPTION_START_RE.match(clean):
        return False
    if clean[-1] in ".!?":
        return False
    words = clean.split()
    if len(clean) > 100 or len(words) > 12:
        return False
    # Short title-case/noun phrases remain valid project titles; common
    # project-domain nouns provide an additional signal for less title-cased text.
    first_alpha = next((c for c in clean if c.isalpha()), "")
    if first_alpha and first_alpha.islower():
        return False
    return True


def _split_project_blocks(section_text: str) -> list[dict]:
    """Project-only variant of the shared block splitter."""
    if not section_text:
        return []
    lines = [l.strip() for l in section_text.split("\n") if l.strip()]
    blocks = []
    current = None
    for line in lines:
        is_bullet = bool(re.match(r"^[\-•*◦]\s", line)) or bool(re.match(r"^\d+[.)]\s", line))
        clean = re.sub(r"^[\-•*◦]\s*", "", line)
        clean = re.sub(r"^\d+[.)]\s*", "", clean).strip()
        if not clean:
            continue
        if is_bullet:
            if current is None:
                current = {"title": clean, "lines": []}
            else:
                current["lines"].append(clean)
        elif current is None or _looks_like_project_title_line(clean):
            if current:
                blocks.append(current)
            current = {"title": clean, "lines": []}
        else:
            current["lines"].append(clean)
    if current:
        blocks.append(current)
    return blocks


def extract_projects(section_text: str) -> list[dict]:
    blocks = _split_project_blocks(section_text)
    out = []
    for b in blocks[:8]:
        title = b["title"]
        year = None
        ym = _TRAILING_YEAR_RE.search(title)
        if ym:
            year = int(ym.group(1))
            title = _TRAILING_YEAR_RE.sub("", title).strip(" -|:")
        if not title:
            continue
        desc = " ".join(b["lines"])[:220]
        out.append({"title": title[:100], "description": desc, "year": year})
    return out


_ISSUER_PAREN_RE = re.compile(r"\(([^)]{2,40})\)\s*$")
_ISSUER_SEP_RE = re.compile(r"\s*(?:-|–|—|\|)\s*")


def extract_certifications(section_text: str) -> list[dict]:
    """Structured {"name", "issuer", "description"} entries — replaces the
    old flat comma-split list, which was treating each wrapped
    continuation line of a certification's description as its own
    certification (problem statement §9)."""
    blocks = _split_blocks_with_continuations(section_text)
    out = []
    seen = set()
    for b in blocks[:10]:
        title = b["title"]
        issuer = ""
        pm = _ISSUER_PAREN_RE.search(title)
        if pm:
            issuer = pm.group(1).strip()
            title = _ISSUER_PAREN_RE.sub("", title).strip(" -|:")
        elif _ISSUER_SEP_RE.search(title):
            parts = _ISSUER_SEP_RE.split(title, maxsplit=1)
            if len(parts) == 2 and parts[1].strip() and len(parts[1].strip()) < 40:
                title, issuer = parts[0].strip(), parts[1].strip()
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        description = " ".join(b["lines"])[:300]
        out.append({"name": title[:120], "issuer": issuer[:60], "description": description})
    return out


def extract_list_section(section_text: str, max_items: int = 10, split_commas: bool = False) -> list[str]:
    """Turns a section's raw text into a flat list of items. Continuation
    lines (wrapped text with no new bullet/title) are merged back into the
    item they belong to, rather than becoming separate entries (problem
    statement §10). `split_commas` is only used for legacy callers that
    want several short comma-separated items on one line split apart —
    it's off by default because achievements/research entries are usually
    full sentences that happen to contain a comma."""
    if not section_text:
        return []
    if split_commas:
        items = []
        for raw in section_text.split("\n"):
            line = raw.strip().strip("-•*◦\t ")
            if not line:
                continue
            if "," in line and len(line) < 120 and not re.search(r"\d{4}", line):
                items.extend(p.strip() for p in line.split(",") if p.strip())
            else:
                items.append(line)
    else:
        items = []
        for b in _split_blocks_with_continuations(section_text):
            merged = b["title"]
            if b["lines"]:
                merged += " " + " ".join(b["lines"])
            items.append(merged.strip())
    seen = set()
    out = []
    for it in items:
        key = it.lower()
        if key not in seen and len(it) > 1:
            seen.add(key)
            out.append(it)
    return out[:max_items]


# ---------------------------------------------------------------------------
# Confidence heuristic
# ---------------------------------------------------------------------------

def _compute_confidence(
    name: str,
    email: str,
    phone: str,
    technical_skills: list,
    soft_skills: list,
    education_entries: list,
    experience_entries: list,
    has_experience_signal: bool,
    review_required_count: int,
    rejected_count: int,
) -> float:
    """Evidence-based confidence, 0.0-1.0. Previously this was
    `sum(6 booleans) / 6`, which reached 1.0 as soon as *something* was
    present in each bucket regardless of quality — a resume with garbage
    skill candidates and an education entry with no institution could
    still score 1.0. This version weighs how COMPLETE/CLEAN each part of
    the extraction is, not just whether it's non-empty (problem statement
    §12)."""
    contact_score = (
        (0.4 if name else 0.0)
        + (0.4 if email else 0.0)
        + (0.2 if phone else 0.0)
    )

    accepted = len(technical_skills) + len(soft_skills)
    if accepted == 0:
        skills_score = 0.0
    else:
        base = 0.3 + 0.7 * min(accepted / 8, 1.0)
        noisy_total = review_required_count + rejected_count
        # Extraction consistency: a large share of ambiguous/rejected
        # candidates relative to accepted ones signals messy extraction
        # (e.g. two-column PDF artifacts), so it caps how high skills_score
        # can go even when several real skills were also found.
        penalty = min(noisy_total / (accepted + noisy_total + 1), 0.3)
        skills_score = max(base - penalty, 0.0)

    if not education_entries:
        education_score = 0.0
    else:
        complete = sum(1 for e in education_entries if e.get("degree") and e.get("institution"))
        education_score = 0.5 + 0.5 * (complete / len(education_entries))

    if experience_entries and any(e.get("start_date") for e in experience_entries):
        experience_score = 1.0
    elif has_experience_signal:
        experience_score = 0.6
    elif experience_entries:
        experience_score = 0.3
    else:
        experience_score = 0.0

    overall = (
        contact_score * 0.15
        + skills_score * 0.35
        + education_score * 0.20
        + experience_score * 0.30
    )
    # Keep confidence evidence-based without allowing a perfect-looking
    # extraction to imply certainty. The small quality adjustment is derived
    # from actual extraction signals and is deterministic for the same input.
    quality_penalty = 0.02 if overall >= 0.98 else 0.0
    return round(min(max(overall - quality_penalty, 0.0), 1.0), 2)


# ---------------------------------------------------------------------------
# 8. Structured output
# ---------------------------------------------------------------------------

def parse_resume(file_path: str, candidate_name: str = "") -> dict:
    nlp = _get_nlp()

    raw_text = extract_text(file_path)
    text = normalize_text(raw_text)
    sections, preamble, section_spans = split_sections(text)

    doc = nlp(text)

    # --- contact / identity ---
    pdf_hint = (
        _pdf_name_hint(file_path)
        if file_path.lower().endswith(".pdf")
        else ""
    )
    extracted_name = extract_candidate_name(
        preamble,
        pdf_name_hint=pdf_hint
    )
    email = extract_email(text)
    phone = extract_phone(preamble) or extract_phone(text)

    # --- skills ---
    skill_result = extract_skills(
        doc,
        text,
        sections,
        section_spans,
        candidate_name=candidate_name or extracted_name
    )

    # ---------------------------------------------------------
    # Skill Discovery Agent
    #
    # Only ambiguous candidates go to the LLM.
    # Known technical/soft skills are handled locally.
    # ---------------------------------------------------------
    discovery_result = discover_skills(
        skill_result.get("review_required_skills", [])
    )
    skill_discovery_error = discovery_result.get(
    "error",
    ""
    )
    technical_skills = _unique_list(
        skill_result.get("technical_skills", [])
        + discovery_result.get("technical_skills", [])
    )

    soft_skills = _unique_list(
        skill_result.get("soft_skills", [])
        + discovery_result.get("soft_skills", [])
    )

    rejected_skills = _unique_list(
        discovery_result.get("rejected_skills", [])
    )

    # Keep candidates that still need review if the LLM was unavailable.
    llm_error = discovery_result.get("error", "")
    review_required_skills = (
        skill_result.get("review_required_skills", [])
        if llm_error
        else []
    )

    education_section = sections.get("education", "")

    education_entries = extract_education_entries(
        education_section
    )

    # Use Gemini when the rule/NER extraction is missing OR semantically
    # suspicious -- not just when a field is outright empty. A degree that
    # looks like a skill/project/certification/generic noun, or an
    # institution contaminated with unrelated text, is "suspicious" per
    # _education_entry_is_suspicious (model-driven, no hard-coded words).
    suspicious_education_entries = [
        e for e in education_entries if _education_entry_is_suspicious(e)
    ]
    education_needs_llm = (
        not education_entries or bool(suspicious_education_entries)
    )

    if education_needs_llm and education_section:
        llm_education = _llm_extract_education(education_section)

        if llm_education:
            # Preserve the deterministic entries that already look valid;
            # only bring in the LLM result for what was missing/suspicious
            # instead of unconditionally discarding everything.
            good_entries = [
                e for e in education_entries if e not in suspicious_education_entries
            ]
            if good_entries:
                existing_keys = {
                    (
                        str(e.get("degree", "")).strip().lower(),
                        str(e.get("institution", "")).strip().lower(),
                    )
                    for e in good_entries
                }
                merged = list(good_entries)
                for llm_entry in llm_education:
                    key = (
                        str(llm_entry.get("degree") or "").strip().lower(),
                        str(llm_entry.get("institution") or "").strip().lower(),
                    )
                    if key in existing_keys:
                        continue
                    merged.append(llm_entry)
                education_entries = merged
            else:
                education_entries = llm_education

    if not education_entries:
        education_entries = extract_education_entries(text)

    if not education_entries:
        education_entries = _extract_education_ner_fallback(doc)

    education_str = format_education(education_entries)

    
    # ---------------------------------------------------------
    # Experience extraction setup
    # ---------------------------------------------------------

    exp_section_text = sections.get("experience", "")
    experience_years = 0.0
    experience_months = 0

    # Give the LLM the complete non-education resume text. This is more
    # robust than date-anchored windows for multi-column PDFs because role,
    # organization and date lines can be separated by the PDF reading order.
    # The LLM prompt explicitly restricts extraction to employment/research
    # experience, while the existing validator prevents unrelated fragments
    # from reaching the final result.
    experience_context = _text_excluding(
        text,
        sections.get("education", "")
    )

    if not experience_context:
        experience_context = exp_section_text or text

    date_search_space = (
        exp_section_text
        if exp_section_text
        else _text_excluding(
            text,
            sections.get("education", "")
        )
    )

    date_ranges = find_date_ranges(date_search_space)
    years_from_dates = merge_and_sum_years(date_ranges)
    months_from_dates = merge_and_sum_months(date_ranges)
    years_from_keyword = extract_experience_years_keyword(text)

    # ---------------------------------------------------------
    # PRIMARY EXPERIENCE EXTRACTION — Groq LLM
    # ---------------------------------------------------------

    experience_entries = []

    if experience_context:
        llm_experience = _llm_extract_experience(
            experience_context
        )

        if llm_experience:
            experience_entries = _validate_experience_entries(
                llm_experience
            )

            # High-confidence evidence from explicit Experience headers is
            # applied AFTER validation so missing role/organization fields
            # can be safely recovered without weakening the validator.
            explicit_headers = _extract_explicit_experience_headers(
                experience_context
            )
            experience_entries = _apply_explicit_experience_evidence(
                experience_entries,
                explicit_headers
            )

    # ---------------------------------------------------------
    # DETERMINISTIC PASS — always computed (single pass, no extra LLM
    # call), used two ways:
    #
    #  1. FULL FALLBACK when the LLM produced nothing at all. Runs on
    #     the merged experience_context (not just exp_section_text) when
    #     no "Experience" heading was detected -- common on two-column
    #     layouts before reflow, or unusual headings -- so the
    #     deterministic parser still has something to work with instead
    #     of unconditionally producing nothing (problem statement §2/§A).
    #
    #  2. GAP BACKFILL when the LLM DID produce entries but left role or
    #     organization empty on one of them -- the reported failure mode
    #     where the two pieces of information exist in the text but
    #     weren't close enough together for the LLM to confidently pair
    #     them. The deterministic parser's line-proximity heuristics
    #     (candidate_prev / _line_looks_like_strong_header) sometimes
    #     succeed exactly where that association is missed, so a missing
    #     field is recovered from it rather than the whole entry (and its
    #     already-correct fields) being discarded.
    #
    # Either way, deterministic output is passed through the SAME
    # validation gate as the LLM's output (§C/§D) before it can
    # contribute to the final result -- it never goes in directly.
    # ---------------------------------------------------------

    deterministic_entries = _validate_experience_entries(
        extract_experience_entries(exp_section_text or experience_context)
    )

    if experience_entries:
        experience_entries = _backfill_missing_experience_fields(
            experience_entries, deterministic_entries
        )

        # Preserve valid deterministic records that the LLM completely
        # missed. Match by exact start/end date first so two nearby jobs
        # cannot be accidentally merged.
        existing_ranges = {
            (e.get("start_date"), e.get("end_date"))
            for e in experience_entries
            if e.get("start_date")
        }
        for det in deterministic_entries:
            det_range = (det.get("start_date"), det.get("end_date"))
            if not det_range[0]:
                continue
            if det_range not in existing_ranges:
                experience_entries.append(det)
                existing_ranges.add(det_range)
    else:
        experience_entries = deterministic_entries

    # Apply explicit header evidence once more after deterministic
    # backfilling/fallback. This only fills missing fields and never
    # overwrites an already populated role or organization.
    explicit_headers = _extract_explicit_experience_headers(
        experience_context
    )
    experience_entries = _apply_explicit_experience_evidence(
        experience_entries,
        explicit_headers
    )

    experience_date_ranges = []
    for entry in experience_entries:
        start = entry.get("start_date")
        end = entry.get("end_date")

        if not start:
            entry["duration_months"] = None
            continue

        try:
            sy, sm = map(int, start.split("-"))
            start_dt = date(sy, sm, 1)

            if end:
                ey, em = map(int, end.split("-"))
                end_dt = date(ey, em, 1)
            else:
                end_dt = date.today().replace(day=1)

            if end_dt < start_dt:
                entry["duration_months"] = None
                continue

            experience_date_ranges.append((start_dt, end_dt))
            entry["duration_months"] = merge_and_sum_months(
                [(start_dt, end_dt)]
            )

        except (ValueError, TypeError):
            entry["duration_months"] = None

    if experience_date_ranges:
        experience_years = merge_and_sum_years(experience_date_ranges)
        experience_months = merge_and_sum_months(experience_date_ranges)
        date_ranges = experience_date_ranges
    else:
        experience_years = 0.0
        experience_months = 0
        date_ranges = []

    try:
        orgs = list(dict.fromkeys(
            ent.text
            for ent in (
                _get_base_nlp()(exp_section_text).ents
                if exp_section_text
                else []
            )
            if ent.label_ == "ORG"
        ))
    except Exception:
        orgs = []

    experience_summary = build_experience_summary(
        experience_years,
        bool(date_ranges),
        bool(years_from_keyword),
        experience_entries,
        orgs
    )

    # --- other sections ---
    projects = extract_projects(
        sections.get("projects", "")
    )

    certifications = extract_certifications(
        sections.get("certifications", "")
    )

    achievements = extract_list_section(
        sections.get("achievements", "")
    )

    research = extract_list_section(
        sections.get("research", "")
    )

    # --- confidence ---
    confidence = _compute_confidence(
        name=extracted_name or candidate_name,
        email=email,
        phone=phone,
        technical_skills=technical_skills,
        soft_skills=soft_skills,
        education_entries=education_entries,
        experience_entries=experience_entries,
        has_experience_signal=bool(
            exp_section_text
            or date_ranges
            or years_from_keyword
        ),
        review_required_count=len(skill_result.get("review_required_skills", [])),
        rejected_count=len(rejected_skills),
    )

    # ---------------------------------------------------------
    # Final structured output
    # ---------------------------------------------------------
    all_skills = _unique_list(
        technical_skills + soft_skills
    )

    result = {
        # Existing fields kept for DB/API compatibility
        "skills": ", ".join(all_skills) if all_skills else "None detected",
        "education": education_str,
        "experience": experience_summary,
        "experience_years": experience_years,
        "raw_text_length": len(text),
        # Contact / identity
        "candidate_name": extracted_name or candidate_name,
        "email": email,
        "phone": phone,

        # Other extracted sections
        "projects": projects,
        "certifications": certifications,
        "achievements": achievements,
        "research": research,

        # New structured skill fields
        "technical_skills": technical_skills,
        "soft_skills": soft_skills,
        "review_required_skills": review_required_skills,
        "llm_rejected_skills": rejected_skills,
        "skill_discovery_error": skill_discovery_error,

        # Structured education / experience
        "education_entries": education_entries,
        "experience_entries": experience_entries,
        "experience_months": experience_months,

        "confidence": confidence,
    }

    # Helpful during development/demo: tells us if Gemini could not run.
    if llm_error:
        result["skill_discovery_error"] = llm_error

    return result