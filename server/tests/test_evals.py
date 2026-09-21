from __future__ import annotations

from evals.harness import run_eval
from server.triage.demo import DemoClassifier


def test_demo_eval_runs_and_reports():
    report, cost = run_eval(DemoClassifier(), "general", price_per_billion=1.0)
    assert report.total == 64
    # sanity: every email produced a lane decision
    assert report.lane_correct <= report.total
    # cost is derived from tokens and price
    assert cost >= 0.0
    assert report.total_tokens > 0


def test_demo_lane_accuracy_reasonable():
    report, _ = run_eval(DemoClassifier(), "general")
    accuracy = report.lane_correct / report.total
    assert accuracy >= 0.6, f"demo lane accuracy too low: {accuracy:.2%}"
