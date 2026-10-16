"""Deprecated.

The old version of this script DELETED all jobs, candidates and scores before
inserting sample rows, which wiped real data. Use the safe demo seed instead:

    python -m app.seed_demo            # add clearly-marked DEMO data
    python -m app.seed_demo --remove   # remove only the DEMO data
"""

if __name__ == "__main__":
    raise SystemExit("app.seed is retired because it wiped real data. Run: python -m app.seed_demo")
