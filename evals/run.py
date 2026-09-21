"""Eval runner. Usage:

    python -m evals.run --classifier demo|jev|llm [--template general]

Prints per-question accuracy, a sender_type confusion matrix, lane accuracy, the
check-manually rate, average latency, and estimated cost.
"""

from __future__ import annotations

import argparse

from server.app.config import get_settings
from server.triage.demo import DemoClassifier
from server.triage.factory import get_classifier

from .harness import EvalReport, run_eval


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):5.1f}%" if d else "   n/a"


def _sender_types(report: EvalReport) -> list[str]:
    labels: set[str] = set()
    for (want, got) in report.confusion:
        labels.add(want)
        labels.add(got)
    return sorted(labels)


def print_report(report: EvalReport, cost: float) -> None:
    print(f"\n=== Eval report: template={report.template} classifier={report.classifier} ===")
    print(f"emails: {report.total}\n")

    print("Per-question accuracy:")
    for key in sorted(report.question_total):
        c, t = report.question_correct[key], report.question_total[key]
        print(f"  {key:24s} {_pct(c, t)}  ({c}/{t})")

    types = _sender_types(report)
    if types:
        print("\nsender_type confusion (rows = expected, cols = predicted):")
        header = " " * 16 + "".join(f"{t[:12]:>13s}" for t in types)
        print(header)
        for want in types:
            row = "".join(f"{report.confusion.get((want, got), 0):>13d}" for got in types)
            print(f"  {want:14s}{row}")

    print(f"\nlane accuracy:      {_pct(report.lane_correct, report.total)}  ({report.lane_correct}/{report.total})")
    print(f"check-manually:     {_pct(report.check_manually, report.total)}  ({report.check_manually}/{report.total})")
    avg_latency = report.total_latency_ms / report.total if report.total else 0.0
    print(f"avg latency:        {avg_latency:.2f} ms/email")
    print(f"input tokens:       {report.total_tokens} total")
    print(f"estimated cost:     ${cost:.6f}  (price/1e9 tokens = {get_settings().price_per_billion_tokens})")
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classifier", default="demo", choices=["demo", "jev", "llm"])
    parser.add_argument("--template", default="general")
    args = parser.parse_args()

    settings = get_settings()
    if args.classifier == "demo":
        classifier = DemoClassifier()  # always available, no config needed
    else:
        # Re-select via the factory so jev/llm honor their env configuration.
        settings.classifier = args.classifier
        classifier = get_classifier(settings)

    report, cost = run_eval(classifier, args.template, settings.price_per_billion_tokens)
    print_report(report, cost)


if __name__ == "__main__":
    main()
