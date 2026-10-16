# Hirelune — Agentic Hiring System

React (Vite) frontend + FastAPI / SQLAlchemy / LangGraph backend.

## Run locally

### Backend

First create the PostgreSQL database and put its URL in `backend/.env` — see **[docs/POSTGRESQL_PGADMIN_SETUP.md](docs/POSTGRESQL_PGADMIN_SETUP.md)** (5 minutes with pgAdmin).

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm   # required by the resume parser; without it resume upload fails
uvicorn app.main:app --reload
```

On startup the log prints the database in use, whether `GROQ_API_KEY` is configured, whether the spaCy NER model loaded and `semantic model available: true/false`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend calls `http://localhost:8000` by default. Override it with `frontend/.env`: `VITE_API_URL=http://localhost:8000`.

### Tests

```bash
cd backend
pytest -q
```

## Design

The whole frontend follows the home page: dark ground, Syne headings, Instrument Sans body text, JetBrains Mono labels, pill buttons and one colour per hiring agent.

- `frontend/src/styles/tokens.css` holds every colour, font and radius. Dark is the default. The sun/moon button in the top bar switches to a cream "paper" variant, and the choice is saved on the account.
- `frontend/src/styles/components.css` holds the shared classes (`.btn`, `.card`, `.pill-*`, `.stat`, `.table`, the sidebar and top bar). Pages use these classes, so a change here reaches every page.
- `frontend/src/styles/landing.css` and `pages/candidate/landingMotion.js` belong to the home page only. Every rule in `landing.css` starts with `.lp`, so nothing leaks into the app pages.
- `frontend/src/components/Logo.jsx` is the animated logo. `<Logo />` follows the page theme, `<Logo tone="light" />` is for surfaces that are always dark (the sidebar), `mode="loop"` is a loading indicator.
- `frontend/src/components/AgentTrail.jsx` shows the eight agents as coloured steps, using `--a1` to `--a8` from the tokens.

New accounts start in dark mode. Existing accounts keep the theme they saved.

## Configuration

Copy `.env.example` to `backend/.env`.

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Needed for resume skill discovery, assessment question generation and short-answer grading. Never returned by the API. |
| `DATABASE_URL` | PostgreSQL connection, e.g. `postgresql+psycopg2://hirelune:secret@localhost:5432/hirelune`. Default: `postgres:postgres@localhost:5432/hirelune`. |
| `SEED_DEMO_DATA` | `true` loads the 5 demo companies, HRs, jobs and candidates on first start. |
| `SESSION_DAYS`, `FRONTEND_ORIGINS`, `CODE_RUNNER`, `DB_POOL_SIZE` | See `backend/.env.example`. |

### Database: PostgreSQL (+ pgAdmin)

**Full tutorial: [`docs/POSTGRESQL_PGADMIN_SETUP.md`](docs/POSTGRESQL_PGADMIN_SETUP.md)** — install PostgreSQL and pgAdmin, create the user and database, connect, browse tables, useful SQL, moving data from SQLite, troubleshooting.

Short version:

```sql
CREATE ROLE hirelune WITH LOGIN PASSWORD 'hirelune_pw';
CREATE DATABASE hirelune OWNER hirelune;
```
```env
# backend/.env
DATABASE_URL=postgresql+psycopg2://hirelune:hirelune_pw@localhost:5432/hirelune
```

Start the backend: every table is created automatically, and on later releases new columns are added with `ALTER TABLE` (no data is ever dropped). Several uvicorn workers can start together — a PostgreSQL advisory lock makes only one of them migrate/seed at a time. Generated text that would exceed a `VARCHAR(n)` column is trimmed instead of failing, credit balances are changed under a per-account lock, and a manual submit and the auto-submit job can't grade the same assessment twice.

SQLite still works (`DATABASE_URL=sqlite:///hiring.db`) and is what the tests use by default. To move an existing `backend/hiring.db` into PostgreSQL: `python -m app.migrate_sqlite_to_postgres`.

### Your data persists

Accounts, jobs and applications live in PostgreSQL (plus uploaded files in `backend/storage/` and `backend/uploads/`). Restarting the server never resets them, and updating the code from a new zip doesn't touch the database. Keep `backend/storage/` and `backend/uploads/` when you update. The startup log prints the database (password hidden) and how many candidate/HR accounts it contains.

Logins: each login gets its own session token (only a SHA-256 hash is stored in `auth_sessions`), valid for `SESSION_DAYS` (30, sliding). Candidate, HR and admin portals keep separate sessions in the browser, so logging into one never logs you out of another. Passwords are PBKDF2-SHA256 hashed.

### Demo companies, HRs, jobs and candidates

```bash
cd backend
python -m app.seed_demo            # 5 companies + verified HRs, 11 jobs, 6 candidates, assessments, results
python -m app.seed_demo --reset    # recreate demo data
python -m app.seed_demo --remove   # delete only demo data
```

| Company (demo) | HR login | Jobs |
| --- | --- | --- |
| Nimbus Analytics | `priya.hr@demo.hirelune.test` | Machine Learning Engineer, Data Analyst |
| Orbitware Labs | `arjun.hr@demo.hirelune.test` | Full Stack Developer, Android Developer |
| Finvera Payments | `kavya.hr@demo.hirelune.test` | Backend Engineer (Python), DevOps Engineer |
| Medisphere Health | `rohit.hr@demo.hirelune.test` | Data Scientist, QA Automation Engineer |
| Kalpa Retail Tech | `isha.hr@demo.hirelune.test` | Frontend Developer (React), Product Analyst |

Every HR profile is complete (photo, company details, logo, ID proof, visiting card, registration proof) and verified, and every job has a published assessment. Candidates: `aarav@`, `kabir@`, `sneha@`, `meera@`, `rohan@`, `ananya@demo.hirelune.test` — Kabir and Ananya have not taken their assessment yet, so you can try it live. **Password for every demo account: `Demo@1234`.** Every demo row is marked "(Demo)" and uses the `@demo.hirelune.test` domain. Scores come from the real parser, screening graph and grader — nothing is hardcoded.

### Smart search (filters + NLP)

The candidate job board and the HR Applications page have a search box that understands plain language (`backend/app/services/search_service.py`):

- **Job search** — `remote python ml jobs in pune 2+ years`, `fresher data analyst`, `react developer bangalore`. Skills (with aliases such as *js → JavaScript*, *ml → Machine Learning*), cities (*Bangalore → Bengaluru*), work mode, experience ranges and seniority words are recognised; typos are corrected (*pyhton → Python*); role words expand (*frontend* finds React/JavaScript jobs). Combine it with the location / work-mode / experience / sort filters.
- **Applicant search (HR)** — `shortlisted python developers 3+ years score above 70`.
- What was understood is shown as chips; removing a chip removes those words. Each result shows a match score and *why* it matched. API: `GET /jobs/search?q=…` and `GET /candidates/search?q=…`.

### Offer letters

HR → Offer letters: create an offer for an assessed/shortlisted/interviewed candidate (unlock their contact first), then fill the grouped form (role, compensation, joining & terms, signature, custom fields) next to a live, formatted preview. Missing fields are highlighted in the preview — click one to jump to its input. The letter text has a toolbar (heading, bold, bullet, divider, insert field at cursor), drafts save automatically, *Preview PDF* shows the exact letterhead PDF, the response window is adjustable (1–60 days), and any letter can be saved as a template. Sent offers are frozen; changes go through a revision.

### Agentic AI orchestration (LangGraph)

Two LangGraph `StateGraph` orchestrators coordinate the agents; both run on the live request path:

| Orchestrator | Graph | Runs when |
| --- | --- | --- |
| `agents/recruitment_graph.py` | resume parser → skill agent → experience agent → bias agent → *(conditional route)* → ranking agent → final result | `run_screening_graph` right after a resume is uploaded (`routes/resumes.py` → `scoring_service`), and `run_final_ranking_graph` after the assessment is submitted (`assessment_service.submit`) to blend skill, experience and test scores with the job's weights. |
| `agents/assessment_graph.py` | plan → generate MCQs (LLM) → generate coding problems (LLM) → validate by executing the reference solution in the sandbox → *(retry once or fall back to the verified bank)* → assemble | HR clicks *Create with AI* (`POST /hr/assessments/generate`). |

Supporting agents: resume parser (spaCy NER + optional Groq LLM for education/experience), skill discovery, skill matcher, experience agent (optional sentence-transformers), bias agent, ranking agent, assessment question generator and short-answer grader (Groq).

### AI assessment builder (LangGraph)

HR → Assessments → **AI assessments** → *Create with AI*: pick job, skills, difficulty, number of questions, type (MCQ / coding / mixed) and time limit. `agents/assessment_graph.py` runs `plan → generate_mcq → generate_coding → validate_coding (retry once) → assemble`; each AI coding problem's reference solution is executed in the sandbox and expected outputs come from that run, otherwise a verified problem-bank problem is used. HR reviews, edits/deletes/adds questions and publishes; the published version is what candidates of that job receive (one published per job).

### Practice zone: AI mock interview + mock assessment (candidates)

Private to the candidate — HR never sees practice results. Sidebar → **Practice**.

**Mock interview** (`/mock-interview`): pick a job (or type a target role + skills), type (technical / behavioural / mixed), difficulty, 3–8 questions, an overall limit and a mode — *Practice* (overruns are only noted) or *Interview* (the answer auto-submits when its clock hits zero). Every question has its own limit by type and difficulty (concept 1–2 min, explain 2–4, behavioural 2–3, scenario 4–8, coding 8–15), 15 s of reading time, then a server-timed answer clock. Answer by **speaking** (browser speech-to-text; filler words and pace are measured), **typing**, or in the **code editor** for the coding slot (sample tests run in the same sandbox as real assessments).

`agents/mock_interview_graph.py` is a LangGraph `StateGraph` that acts as the interviewer: `plan` (skill gaps first, warm-up, one coding slot) → `ask_question` → `evaluate` → *(decide)* → `follow_up` when an answer misses a key point (max 2) / `next_slot` / `report`. The report gives an overall score, competency bars (incl. communication and problem solving), per-question feedback with key points covered/missed, STAR detection for behavioural answers, time management and a study plan. With `GROQ_API_KEY` set the questions/evaluation/report use the LLM; otherwise (or with `MOCK_INTERVIEW_ENGINE=offline`) a rule-based engine runs, so it always works.

**Mock assessment** (`/mock-assessment`): role-based practice test — 3–25 MCQs (AI-generated, falling back to the built-in bank in `agents/practice_bank.py`) plus 0–2 coding problems matched to the role's skills, a timer sized to the test, question navigator with flags, autosave every 5 s, auto-submit at zero, then a reviewed result with explanations, per-skill scores and recommendations.

### Code editor (real assessment, mock assessment, mock interview)

One shared editor (`components/CodeEditor.jsx`) in Python 3, Java and C++17: line numbers with the current line highlighted, Tab / Shift+Tab (also on a multi-line selection), auto-indent after `:` `{` `(` `[`, `{|}` + Enter opens an indented block, bracket/quote pairs with step-over, smart Backspace, Ctrl+/ comment toggle, **Ctrl+Enter = Run**, Esc then Tab leaves the editor (no keyboard trap), and native undo/redo after automatic edits. Switching language asks before replacing your code; *Reset* restores the starter template.

In the real assessment the code is **autosaved as a draft** with the other answers, so it survives moving between questions, a page reload or leaving and coming back. *Run Code* checks the sample tests; *Submit Code* also runs the hidden tests. If the candidate finishes (or the timer auto-submits) with code that was never submitted — or was edited after the last submission — the latest draft is run against all tests and graded (`assessment_service.parse_code_draft`). An untouched starter template is never graded.

## Workflow

**Candidate:** Apply → upload resume → parsing → screening (skill, experience, bias) → screening result → **Take Assessment** (explicit click) → answer (progress is saved; can leave and continue) → submit → test score → final ranking.

Uploading a resume never generates, starts or completes an assessment. If screening fails the upload still succeeds (`screening_result.status == "failed"`) and the candidate can still take the assessment; screening is retried automatically on submit.

**HR:** Dashboard → Applications → **View Candidate** → one page with candidate/application info, pipeline, score cards, original resume (view/download), the exact job requirements used for scoring, matched/missing skills, extracted profile, assessment status, questions with candidate and correct answers, ranking explanation and recommendation. Shortlist / Reject persist through the API.

## Scores

- All scores are floats 0–100 in the API. Formatting to `NN%` happens only in the frontend (`src/utils/score.js`).
- `null` = not calculated (shown as `—`); `0` = a real calculated zero (shown as `0%`).
- Skill score = matched requirements / total requirements × 100 (1 decimal). Requirements are split on `,` `;` and new lines (and short `A and B` / `A/B` pairs). Matching uses normalization, aliases (see `ALIASES` in `app/agents/skill_agent.py`) and whole-word phrase containment for skills of 4+ characters; C, R, Go, ML etc. match exactly only.
- Final score = the job's weights applied by the Ranking Agent, e.g. 40/20/40 with skill 66.7, experience 70, test 100 → `80.68` (shown as 81%).
- Education is displayed but never used in scoring.

## Main API endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /jobs` | Create job (422 if weights aren't integers ≥ 0 summing to 100, `min_experience < 0`, or requirements empty) |
| `POST /candidates`, `GET /candidates?job_id=&email=` | Apply / list applications |
| `GET /candidates/{id}` | Candidate + resume profile + applications |
| `GET /candidates/{id}/scores` | Main score source: scores, matched/missing skills, explanation, recommendation, job requirements and weights |
| `GET /candidates/{id}/resume[?download=true]` | Original uploaded file (PDF/DOC/DOCX) |
| `GET /candidates/{id}/assessment` | HR view: questions, candidate answers, correct answers, feedback (answer keys only once completed) |
| `PATCH /candidates/applications/{id}/status` | Persist HR decisions |
| `POST /resumes/{candidate_id}` | Upload/replace resume, parse, screen |
| `POST /assessments/start/{application_id}` | Start or continue (idempotent; `/generate` is an alias) |
| `GET /assessments/status/{application_id}` | `not_started` / `in_progress` / `completed` |
| `GET /assessments/{application_id}`, `PUT /assessments/progress/{application_id}` | Questions / save draft answers |
| `POST /assessments/submit/{application_id}` | Grade, persist test score + `completed_at`, final ranking |
| `POST /coding/run`, `POST /coding/submit` | Run sample tests / submit against hidden tests for a coding question |
| `/practice/roles`, `/practice/interviews…`, `/practice/assessments…` | Practice zone (candidate only): mock interview (`begin`, `answer`, `run-code`, `finish`) and mock assessment (`progress`, `run-code`, `submit`) |
| `GET /health` | `groq_api_key_configured`, `spacy_ner_loaded`, `semantic_model_available`, `database_ok` |

## Troubleshooting

### Scores are 0 or —

1. Check the backend logs — screening and ranking failures are logged with a full traceback.
2. Open `http://localhost:8000/health`: is `groq_api_key_configured` true? Did spaCy and the semantic model load?
3. Look at `screening_result` in the resume upload response (`status: failed` includes the error).
4. Check the application/job association: `GET /candidates/{id}/scores` returns `job.requirements_list` — the exact requirements that were scored. A 0% with all requirements listed under `missing_skills` is a valid result.
5. Inspect `final_scores` in the database (`skill_score`, `experience_score`, `test_score`, `final_score`, `skill_matched`, `skill_missing`, `screening_status`, `screening_error`).
6. `—` means the value was never calculated (e.g. test/final before the assessment). Re-uploading the resume re-runs screening.

## v7 — proctored assessments, explained decisions, new pipeline, new sign-in

**Proctored assessments.** Before an assessment starts the candidate reads the rules, then passes a camera, microphone and face check (`ProctorGate`). During the test a HUD shows live status and strikes. Tab switches, leaving full screen, window blur, no face, several faces, looking away, sustained noise, a second display and lost devices are reported to `POST /assessments/{id}/proctor/events`. The server (`services/proctor_service.py`) decides what counts: it de-duplicates one incident, counts strikes, and after `PROCTOR_MAX_STRIKES` (default 3) auto-submits the saved answers. HR sees the integrity report with snapshot evidence on the candidate page. Set `PROCTORING_ENABLED=false` to turn it off. Browser proctoring deters and documents; it cannot see a second device.
Face detection uses MediaPipe BlazeFace: `npm install` fetches the model through `scripts/setup-proctoring.mjs` (falls back to a CDN, then to the browser's FaceDetector).

**Explained decisions.** HR confirms every shortlist/reject in a dialog with an optional note. The candidate gets an email and an in-app explanation (`GET /candidates/applications/{id}/feedback`) built from the stored scores, matched/missing skills, topic results, coding results, integrity and next steps.

**Pipeline.** Applied → Skill evaluation → Experience evaluation → Assessment → Interview → Offer letter. A rejected application shows the process stopping at the step where it ended, animated.

**Dashboard search.** NLP search with filters on the candidate dashboard (jobs via the server NLP, applications via `utils/appSearch.js`).

**Sign-in.** One illustrated page for `/login`, `/signup`, `/hr/login`, `/hr/signup` (`pages/auth/`). Google sign-in and password reset are not built yet.

Tests: `cd backend && pytest` (`test_pipeline_feedback.py`, `test_proctoring.py`).
