"""T2 — eval harness. Runs every row in eval/dataset.jsonl through the real
pipeline (classify -> grounding -> seam.generate -> verifier, same path
/copilot/query takes) and reports the metrics ai-onboarding-teman.md §T2
asks for: intent accuracy, filter accuracy, hallucination-rate (target 0%),
thin-sample hedge compliance, out_of_scope handling.

Usage:
    AI_BACKEND=stub  python -m eval.runner   # offline, no key needed
    AI_BACKEND=gemini python -m eval.runner  # exercises the real model too

Writes eval/report.json (machine-readable) and prints the markdown table.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.pipeline import run
from app.verifier import verify

DATASET_PATH = Path(__file__).resolve().parent / "dataset.jsonl"
REPORT_JSON_PATH = Path(__file__).resolve().parent / "report.json"
REPORT_MD_PATH = Path(__file__).resolve().parent / "report.md"

_HEDGE_MARKERS = ("tidak diestimasi", "tipis", "belum ada data")


def _load_dataset() -> list[dict]:
    rows = []
    with DATASET_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _evaluate_row(row: dict) -> dict:
    result = run(row["query"], row["station_id"] or "")
    analysis = result["analysis"]
    answer_text = result["answer"]["answer_text"]

    final_verify = verify(result["answer"], result["context"])
    hallucinated = not final_verify.ok

    intent_correct = analysis.intent == row["expected_intent"]
    filter_correct = analysis.spatial_filter() == row["expected_filter"]

    hedge_correct = None
    if row["expect_behavior"] == "thin_sample":
        hedge_correct = any(marker in answer_text.lower() for marker in _HEDGE_MARKERS)

    out_of_scope_correct = None
    if row["expect_behavior"] == "out_of_scope":
        out_of_scope_correct = analysis.intent == "unknown"

    return {
        "query": row["query"],
        "expect_behavior": row["expect_behavior"],
        "intent": analysis.intent,
        "intent_correct": intent_correct,
        "filter_correct": filter_correct,
        "hallucinated": hallucinated,
        "verify": final_verify.to_dict(),
        "used_fallback": result["used_fallback"],
        "hedge_correct": hedge_correct,
        "out_of_scope_correct": out_of_scope_correct,
        "answer_text": answer_text,
    }


def main() -> None:
    rows = _load_dataset()
    results = [_evaluate_row(r) for r in rows]

    n = len(results)
    intent_acc = sum(r["intent_correct"] for r in results) / n
    filter_acc = sum(r["filter_correct"] for r in results) / n
    hallucination_rate = sum(r["hallucinated"] for r in results) / n

    thin_rows = [r for r in results if r["hedge_correct"] is not None]
    hedge_compliance = sum(r["hedge_correct"] for r in thin_rows) / len(thin_rows) if thin_rows else None

    oos_rows = [r for r in results if r["out_of_scope_correct"] is not None]
    oos_handling = sum(r["out_of_scope_correct"] for r in oos_rows) / len(oos_rows) if oos_rows else None

    summary = {
        "n": n,
        "intent_accuracy": intent_acc,
        "filter_accuracy": filter_acc,
        "hallucination_rate": hallucination_rate,
        "hedge_compliance": hedge_compliance,
        "out_of_scope_handling": oos_handling,
    }

    REPORT_JSON_PATH.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = _render_markdown(summary, results)
    REPORT_MD_PATH.write_text(md, encoding="utf-8")
    print(md)


def _render_markdown(summary: dict, results: list[dict]) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.0f}%"

    lines = [
        "# Eval report (T2)",
        "",
        f"n = {summary['n']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Intent accuracy | {pct(summary['intent_accuracy'])} |",
        f"| Filter accuracy | {pct(summary['filter_accuracy'])} |",
        f"| Hallucination rate (target 0%) | {pct(summary['hallucination_rate'])} |",
        f"| Thin-sample hedge compliance | {pct(summary['hedge_compliance'])} |",
        f"| Out-of-scope handling | {pct(summary['out_of_scope_handling'])} |",
        "",
        "| Query | Behavior | Intent | Hallucinated | Fallback used |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['query']} | {r['expect_behavior']} | {r['intent']} | "
            f"{'yes' if r['hallucinated'] else 'no'} | {'yes' if r['used_fallback'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
