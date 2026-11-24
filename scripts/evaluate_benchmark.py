"""Evaluate CiteGuard output against pre-committed gold labels in sample_manuscript.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    base = Path(__file__).resolve().parent.parent
    bench = json.loads((base / "benchmarks" / "sample_manuscript.json").read_text(encoding="utf-8"))
    results_path = base / "artifacts" / "results.json"
    if not results_path.exists():
        print(f"Missing {results_path}", file=sys.stderr)
        return 1
    results = json.loads(results_path.read_text(encoding="utf-8"))

    gold_map = {it["ref_id"]: it for it in bench["items"]}
    status_ok = 0
    align_ok = 0
    quote_ok = 0
    quote_checked = 0
    latencies = []

    print("ID | Status (Pred vs Gold) | Alignment (Pred vs Gold) | QuoteOK | Time(s)")
    print("-" * 86)
    for row in results["items"]:
        rid = row["citation"]["ref_id"]
        gold = gold_map[rid]
        v = row["verdict"]
        sp = row["spark"]
        lat = sp.get("elapsed_sec", 0.0)
        latencies.append(lat)

        s_match = v["status"] == gold["expected_status"]
        a_match = v["claim_alignment"] == gold["expected_alignment"]
        if s_match:
            status_ok += 1
        if a_match:
            align_ok += 1
        qv = v.get("evidence_quote_verified")
        if qv is not None:
            quote_checked += 1
            if qv:
                quote_ok += 1
        print(
            f"{rid} | {v['status']} ({'OK' if s_match else 'DIFF: ' + gold['expected_status']}) | "
            f"{v['claim_alignment']} ({'OK' if a_match else 'DIFF: ' + gold['expected_alignment']}) | "
            f"{qv} | {lat:.2f}"
        )

    n = len(results["items"])
    avg_lat = sum(latencies) / n if n else 0.0
    print("-" * 86)
    print(
        f"Status Accuracy: {status_ok}/{n} ({status_ok/n*100:.1f}%) | "
        f"Claim-Alignment Accuracy: {align_ok}/{n} ({align_ok/n*100:.1f}%) | "
        f"Verbatim Quotes Verified: {quote_ok}/{quote_checked} | "
        f"Mean Spark Latency: {avg_lat:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
