"""Measure policy retrieval against eval/retrieval_questions.yaml.

Checks every label against the database first — a label that matches no
chunk is a labeling error, not a retrieval miss, and would silently cap
recall. Then embeds each question once and runs every mode on the same
query vector.

Run:  python -m eval.run_retrieval_eval [--mode vector|hybrid|both] [-k 5] [--save PATH]
"""

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv
from psycopg.rows import DictRow, dict_row

from core.embeddings import MODEL, embed_queries
from core.retrieval import search_policy

load_dotenv()
QUESTIONS = Path(__file__).parent / "retrieval_questions.yaml"
DEPTH = 10   # how far down we look for the rank used by MRR


# ------------------------------------------------------------------ scoring (pure)

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def matches(source_url: str, section_path: str, content: str, exp: dict) -> bool:
    if not source_url.rstrip("/").endswith("/" + exp["page"]):
        return False
    if exp.get("section") and _norm(exp["section"]) not in _norm(section_path):
        return False
    return not exp.get("contains") or _norm(exp["contains"]) in _norm(content)


def first_rank(hits, expects: list[dict]) -> int | None:
    """1-based rank of the first correct hit, or None."""
    for rank, h in enumerate(hits, start=1):
        if any(matches(h.source_url, h.section_path, h.content, e) for e in expects):
            return rank
    return None


def summarize(ranks: list[int | None], k: int) -> dict:
    n = len(ranks) or 1
    return {
        "recall@1": sum(r == 1 for r in ranks) / n,
        f"recall@{k}": sum(r is not None and r <= k for r in ranks) / n,
        f"mrr@{DEPTH}": sum(1 / r for r in ranks if r is not None) / n,
    }


# ------------------------------------------------------------------ main

def check_labels(conn, questions: list[dict]) -> list[str]:
    chunks = conn.execute(
        "SELECT source_url, section_path, content FROM policy_chunks"
    ).fetchall()
    bad = []
    for q in questions:
        for exp in q["expect"]:
            if not any(matches(c["source_url"], c["section_path"] or "", c["content"], exp)
                       for c in chunks):
                bad.append(f"{q['id']}: no chunk matches {exp}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["vector", "hybrid", "both"], default="both")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--save", type=Path, help="write per-question results as JSON")
    args = ap.parse_args()

    questions = yaml.safe_load(QUESTIONS.read_text())
    modes = ["vector", "hybrid"] if args.mode == "both" else [args.mode]

    with psycopg.Connection[DictRow].connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        bad = check_labels(conn, questions)
        if bad:
            print("LABEL ERRORS — fix these before trusting any number:\n")
            print("\n".join(f"  {b}" for b in bad))
            return 2

        print(f"{len(questions)} questions · model {MODEL} · k={args.k}\n")
        vectors = embed_queries([q["question"] for q in questions])
        qvecs = {q["id"]: v for q, v in zip(questions, vectors, strict=True)}

        results = {m: {} for m in modes}
        for mode in modes:
            for q in questions:
                hits = search_policy(q["question"], DEPTH, mode, conn=conn, qvec=qvecs[q["id"]])
                results[mode][q["id"]] = {
                    "rank": first_rank(hits, q["expect"]),
                    "top3": [h.section_path for h in hits[:3]],
                }

    # per-question table
    header = f"{'question':<24} {'kind':<11}" + "".join(f"{m:>8}" for m in modes)
    print(header)
    print("-" * len(header))
    for q in questions:
        cells = ""
        for m in modes:
            r = results[m][q["id"]]["rank"]
            mark = "—" if r is None else str(r)
            cells += f"{mark + (' ✗' if r is None or r > args.k else ''):>8}"
        print(f"{q['id']:<24} {q['kind']:<11}{cells}")

    # summary
    print()
    for m in modes:
        ranks = [results[m][q["id"]]["rank"] for q in questions]
        s = summarize(ranks, args.k)
        by_kind = {}
        for kind in sorted({q["kind"] for q in questions}):
            kr = [results[m][q["id"]]["rank"] for q in questions if q["kind"] == kind]
            by_kind[kind] = summarize(kr, args.k)[f"recall@{args.k}"]
        kinds = "  ".join(f"{kind} {v:.0%}" for kind, v in by_kind.items())
        print(f"{m:<7} " + "  ".join(f"{name} {v:.2f}" for name, v in s.items()) + f"   ({kinds})")

    # misses, with what came back instead
    for m in modes:
        misses = [q for q in questions
                  if (results[m][q["id"]]["rank"] or 99) > args.k]
        if misses:
            print(f"\nmisses ({m}):")
            for q in misses:
                print(f"  {q['id']}")
                for path in results[m][q["id"]]["top3"]:
                    print(f"      got: {path}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps({
            "model": MODEL, "k": args.k,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "results": results,
        }, indent=2))
        print(f"\nsaved {args.save}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
