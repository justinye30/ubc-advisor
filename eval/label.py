"""Print prerequisite text for hand-labeling. Shows NO extractor output.

Run:  python -m eval.label CPSC 221
      python -m eval.label --sample 10
"""
import os, sys, textwrap
import psycopg
from dotenv import load_dotenv

load_dotenv()

def show(rows):
    for code, text in rows:
        print(f"\n{'='*70}\n{code}\n{'='*70}")
        print(textwrap.fill(text or "(no prerequisite)", 68))
        print(f"\n- code: \"{code}\"\n  tree:\n    # write it here")

def main():
    args = sys.argv[1:]
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        if args and args[0] == "--sample":
            cur.execute(
                "SELECT code, prereq_text FROM courses WHERE prereq_text IS NOT NULL "
                "ORDER BY random() LIMIT %s", (int(args[1]),))
        else:
            cur.execute(
                "SELECT code, prereq_text FROM courses WHERE code = %s", (" ".join(args),))
        show(cur.fetchall())

if __name__ == "__main__":
    main()
