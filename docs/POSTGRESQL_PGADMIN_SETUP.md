# Hirelune on PostgreSQL + pgAdmin — step-by-step

Hirelune now uses **PostgreSQL** by default. This guide takes you from a fresh machine to a running
app whose data you can browse in **pgAdmin 4**. Allow about 15 minutes.

---

## 1. Install PostgreSQL and pgAdmin

| OS | What to do |
| --- | --- |
| **Windows** | Download the installer from <https://www.postgresql.org/download/windows/> (EDB). Keep the components **PostgreSQL Server**, **pgAdmin 4** and **Command Line Tools** ticked. Choose a password for the `postgres` superuser and **write it down**. Keep port **5432**. |
| **macOS** | Install [Postgres.app](https://postgresapp.com/) (or `brew install postgresql@16 && brew services start postgresql@16`) and pgAdmin 4 from <https://www.pgadmin.org/download/>. |
| **Ubuntu/Debian** | `sudo apt install postgresql` then install pgAdmin 4 from <https://www.pgadmin.org/download/pgadmin-4-apt/>. Set a password: `sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"` |

Any PostgreSQL version from 13 upwards works (16 recommended).

---

## 2. Connect pgAdmin to your server

1. Open **pgAdmin 4**. The first time it asks for a *master password* (this only protects pgAdmin's saved passwords).
2. In the left tree, expand **Servers**. On Windows the local server (*PostgreSQL 16*) is already listed — click it and enter the `postgres` password.
3. If nothing is listed: right-click **Servers → Register → Server…**
   - **General → Name:** `Local PostgreSQL`
   - **Connection → Host name/address:** `localhost` · **Port:** `5432` · **Maintenance database:** `postgres`
   - **Username:** `postgres` · **Password:** your password · tick **Save password** → **Save**.

---

## 3. Create a database user and the `hirelune` database

Using a dedicated user (not the superuser) is safer. Do it **either** with clicks **or** with SQL.

### Option A — with pgAdmin clicks
1. Right-click **Login/Group Roles → Create → Login/Group Role…**
   - **General → Name:** `hirelune`
   - **Definition → Password:** e.g. `hirelune_pw` (use your own)
   - **Privileges:** turn on **Can login?** (and **Create databases?** if you want the app to create the database itself) → **Save**.
2. Right-click **Databases → Create → Database…**
   - **Database:** `hirelune` · **Owner:** `hirelune` → **Save**.

### Option B — with SQL
Select the server, open **Tools → Query Tool**, paste and press **F5 / ▶ Execute**:

```sql
CREATE ROLE hirelune WITH LOGIN PASSWORD 'hirelune_pw';
CREATE DATABASE hirelune OWNER hirelune ENCODING 'UTF8';
-- PostgreSQL 15+ only lets the owner create tables in "public"; the owner here is hirelune, so this is enough.
```

> Because `hirelune` **owns** the database it can create all tables. If you instead give the
> database to `postgres`, also run (connected to the `hirelune` database):
> `GRANT ALL ON SCHEMA public TO hirelune;`

---

## 4. Point Hirelune at the database

Copy `backend/.env.example` to `backend/.env` and set:

```env
DATABASE_URL=postgresql+psycopg2://hirelune:hirelune_pw@localhost:5432/hirelune
```

Format: `postgresql+psycopg2://<user>:<password>@<host>:<port>/<database>`.
If the password contains `@ : / #` or spaces, URL-encode it (e.g. `p@ss` → `p%40ss`).

Install the backend packages (this includes the PostgreSQL driver **psycopg2-binary**):

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

---

## 5. Start the backend — tables are created automatically

```bash
uvicorn app.main:app --reload
```

The log shows:

```
INFO hirelune: Database: postgresql+psycopg2://hirelune:***@localhost:5432/hirelune (0 candidate / 0 HR accounts) — data persists across restarts
```

On every start Hirelune creates missing tables and adds new columns (it never drops data). If the
database itself does not exist yet and the user may create databases, it is created for you
(`DB_AUTO_CREATE=false` turns that off).

Start the frontend as usual: `cd frontend && npm install && npm run dev` → <http://localhost:5173>.

---

## 6. See your data in pgAdmin

In the tree: **Servers → Local PostgreSQL → Databases → hirelune → Schemas → public → Tables**
(right-click **Tables → Refresh** after the first start).

- Right-click any table → **View/Edit Data → All Rows** to browse it.
- **Tools → Query Tool** to run SQL. Useful queries:

```sql
-- Accounts
SELECT account_id, name, email, created_at FROM hr_accounts ORDER BY account_id;
SELECT account_id, name, email, created_at FROM candidate_accounts ORDER BY account_id;

-- Companies and verification status
SELECT c.name, c.verification_status, h.email
FROM companies c JOIN hr_accounts h ON h.account_id = c.hr_account_id;

-- Jobs with the number of applications
SELECT j.job_id, j.title, j.location, j.status, COUNT(a.application_id) AS applications
FROM job_roles j LEFT JOIN applications a ON a.job_id = j.job_id
GROUP BY j.job_id ORDER BY j.job_id;

-- Ranking for one job (NULL score = not calculated yet)
SELECT c.name, a.status, f.skill_score, f.experience_score, f.test_score, f.final_score
FROM applications a JOIN candidates c ON c.candidate_id = a.candidate_id
LEFT JOIN final_scores f ON f.application_id = a.application_id
WHERE a.job_id = 1 ORDER BY f.final_score DESC NULLS LAST;

-- Offer letters
SELECT offer_id, status, sent_at, expires_at FROM offer_letters ORDER BY offer_id DESC;

-- Credits ledger for an HR account
SELECT created_at, type, amount, balance_after, description FROM credit_transactions
WHERE account_role = 'hr' AND account_id = 1 ORDER BY transaction_id DESC;
```

Passwords are stored as salted PBKDF2 hashes and login tokens only as SHA-256 hashes, so nothing
secret is readable in these tables. Uploaded files (resumes, documents, logos, offer PDFs) are
stored on disk in `backend/storage/` and `backend/uploads/`; the tables keep their paths.

---

## 7. Load the 5 demo companies, their HRs, jobs and candidates

```bash
cd backend
python -m app.seed_demo            # once
python -m app.seed_demo --reset    # wipe and recreate only the demo rows
python -m app.seed_demo --remove   # delete only the demo rows
```

Or set `SEED_DEMO_DATA=true` in `.env` and the server loads them on its first start.

| Company (demo) | HR login | Jobs |
| --- | --- | --- |
| Nimbus Analytics | `priya.hr@demo.hirelune.test` | Machine Learning Engineer, Data Analyst |
| Orbitware Labs | `arjun.hr@demo.hirelune.test` | Full Stack Developer, Android Developer |
| Finvera Payments | `kavya.hr@demo.hirelune.test` | Backend Engineer (Python), DevOps Engineer |
| Medisphere Health | `rohit.hr@demo.hirelune.test` | Data Scientist, QA Automation Engineer |
| Kalpa Retail Tech | `isha.hr@demo.hirelune.test` | Frontend Developer (React), Product Analyst |

Every HR profile is 100 % complete (photo, company details, logo, ID proof, visiting card,
registration proof) and **verified**, and every job has a published assessment.
Six demo candidates (`aarav@`, `kabir@`, `sneha@`, `meera@`, `rohan@`, `ananya@demo.hirelune.test`)
have applied; four have finished assessments. **Password for every demo account: `Demo@1234`.**
All demo rows are marked "(Demo)" and use the `@demo.hirelune.test` domain.

---

## 8. Moving existing data from SQLite (`backend/hiring.db`)

If you used Hirelune before, copy everything across once:

```bash
cd backend
python -m app.migrate_sqlite_to_postgres                 # reads backend/hiring.db
python -m app.migrate_sqlite_to_postgres --source D:\old\hiring.db
python -m app.migrate_sqlite_to_postgres --force         # target already has rows: replace them
```

It copies every table in foreign-key order and moves the id sequences forward. Keep
`backend/storage/` and `backend/uploads/` in place — the copied rows point at those files.

---

## 9. Run the tests against PostgreSQL (optional)

The tests use a throw-away SQLite file by default. To run them on PostgreSQL, create an **empty**
scratch database (every table in it is dropped and recreated):

```sql
CREATE DATABASE hirelune_test OWNER hirelune;
```

```bash
# macOS/Linux
TEST_DATABASE_URL=postgresql+psycopg2://hirelune:hirelune_pw@localhost:5432/hirelune_test pytest -q
# Windows PowerShell
$env:TEST_DATABASE_URL="postgresql+psycopg2://hirelune:hirelune_pw@localhost:5432/hirelune_test"; pytest -q
```

---

## 10. Troubleshooting

| Message | Fix |
| --- | --- |
| `password authentication failed for user "hirelune"` | Wrong password in `DATABASE_URL`. Reset it in pgAdmin: **Login/Group Roles → hirelune → Properties → Definition**. |
| `connection refused` / `could not connect to server` | PostgreSQL isn't running. Windows: *Services → postgresql-x64-16 → Start*. macOS: open Postgres.app / `brew services start postgresql@16`. Linux: `sudo systemctl start postgresql`. Check the port (5432). |
| `database "hirelune" does not exist` | Create it (step 3) or give the user **Create databases?** so the app can create it. |
| `permission denied for schema public` | PostgreSQL 15+: make `hirelune` the database owner, or run `GRANT ALL ON SCHEMA public TO hirelune;` in the `hirelune` database. |
| `ModuleNotFoundError: No module named 'psycopg2'` | `pip install -r requirements.txt` inside the activated virtual environment. |
| pgAdmin shows no tables | Start the backend once, then right-click **Tables → Refresh**. Make sure you are looking in database **hirelune**, schema **public**. |
| `The database is temporarily unavailable` in the app | The backend can't reach PostgreSQL — see the server log for the exact reason. |

Pool settings (optional, in `.env`): `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=20`.
