"""Copy an existing SQLite database (backend/hiring.db) into PostgreSQL.

    cd backend
    # .env must point DATABASE_URL at the (empty) PostgreSQL database
    python -m app.migrate_sqlite_to_postgres                      # source: backend/hiring.db
    python -m app.migrate_sqlite_to_postgres --source path/to.db  # another SQLite file
    python -m app.migrate_sqlite_to_postgres --force              # target already has rows: wipe & copy

What it does:
1. creates/updates every table in PostgreSQL (same startup migration the server runs);
2. copies every table in foreign-key order, in batches, converting SQLite 0/1 to booleans;
3. moves each table's id sequence past the copied ids so new rows don't collide.
Files in backend/storage and backend/uploads are untouched (paths stay valid).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import Boolean, String, create_engine, inspect, select, text

from .database import BASE_DIR, SQLALCHEMY_DATABASE_URL, safe_url


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(BASE_DIR / "hiring.db"), help="SQLite file to copy from")
    ap.add_argument("--force", action="store_true", help="delete existing rows in PostgreSQL first")
    args = ap.parse_args()

    if not SQLALCHEMY_DATABASE_URL.startswith("postgresql"):
        print("DATABASE_URL must point at PostgreSQL (postgresql+psycopg2://user:pass@host:5432/dbname).")
        return 2
    source = create_engine(f"sqlite:///{args.source}")
    if not inspect(source).get_table_names():
        print(f"No tables found in {args.source}.")
        return 2

    from . import main as app_main          # creates/migrates the PostgreSQL schema
    from .database import Base, engine as target
    src_tables = set(inspect(source).get_table_names())
    tables = [t for t in Base.metadata.sorted_tables if t.name in src_tables]

    with target.begin() as conn:
        existing = sum(conn.execute(select(text("count(*)")).select_from(t)).scalar() for t in tables
                       if t.name not in ("admin_accounts", "coding_problems", "offer_templates"))
        if existing and not args.force:
            print(f"{safe_url()} already contains {existing} rows. Re-run with --force to replace them.")
            return 1
        for t in reversed(tables):
            conn.execute(t.delete())

    total = 0
    with source.connect() as s, target.begin() as conn:
        for t in tables:
            src_cols = {c["name"] for c in inspect(source).get_columns(t.name)}
            cols = [c for c in t.columns if c.name in src_cols]
            bools = {c.name for c in cols if isinstance(c.type, Boolean)}
            limits = {c.name: c.type.length for c in cols if isinstance(c.type, String) and getattr(c.type, "length", None)}
            result = s.execute(text(f'SELECT {", ".join(chr(34) + c.name + chr(34) for c in cols)} FROM "{t.name}"'))
            n = 0
            while True:
                batch = result.fetchmany(500)
                if not batch:
                    break
                rows = []
                for r in batch:
                    row = dict(zip([c.name for c in cols], r))
                    for b in bools:
                        if row.get(b) is not None:
                            row[b] = bool(row[b])
                    for name, limit in limits.items():      # PostgreSQL enforces VARCHAR(n); SQLite didn't
                        if isinstance(row.get(name), str) and len(row[name]) > limit:
                            row[name] = row[name][:limit]
                    rows.append(row)
                conn.execute(t.insert(), rows)
                n += len(rows)
            total += n
            pk = [c for c in t.primary_key.columns if c.autoincrement is not False and str(c.type).upper().startswith("INT")]
            if n and len(pk) == 1:
                conn.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{t.name}\"', '{pk[0].name}'), "
                                  f"COALESCE((SELECT MAX(\"{pk[0].name}\") FROM \"{t.name}\"), 1))"))
            print(f"  {t.name:28s} {n:6d} rows")
    print(f"Copied {total} rows from {args.source} to {safe_url()}.")
    _ = app_main
    return 0


if __name__ == "__main__":
    sys.exit(main())
