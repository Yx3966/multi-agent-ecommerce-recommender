"""A/B测试引擎单元测试"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ab_test import ABTestEngine, Experiment, ExperimentGroup


def test_consistent_assignment():
    """Same user always gets the same group."""
    engine = ABTestEngine()
    group1 = engine.assign("user_001")
    group2 = engine.assign("user_001")
    assert group1["group"] == group2["group"]


def test_distribution():
    """Check rough distribution balance across many users."""
    engine = ABTestEngine()
    counts: dict[str, int] = {}
    for i in range(1000):
        result = engine.assign(f"user_{i}")
        grp = result["group"]
        counts[grp] = counts.get(grp, 0) + 1

    for grp, count in counts.items():
        assert 300 < count < 700, f"Group {grp} has {count} users — too skewed"


def test_thompson_sampling():
    """Thompson sampling updates posterior correctly."""
    engine = ABTestEngine()
    for _ in range(100):
        engine.record_outcome("rec_strategy", "treatment_llm", True)
    for _ in range(100):
        engine.record_outcome("rec_strategy", "control", False)

    exp = engine.experiments["rec_strategy"]
    treatment = next(g for g in exp.groups if g.name == "treatment_llm")
    control = next(g for g in exp.groups if g.name == "control")
    assert treatment.successes > control.successes


def test_custom_experiment():
    engine = ABTestEngine()
    engine.register_experiment(
        Experiment(
            id="prompt_test",
            name="Prompt模板实验",
            groups=[
                ExperimentGroup(name="template_a", weight=30),
                ExperimentGroup(name="template_b", weight=70),
            ],
        )
    )
    result = engine.assign("user_999", "prompt_test")
    assert result["group"] in ("template_a", "template_b")


def test_metrics_recording():
    engine = ABTestEngine()
    engine.record_metric("rec_strategy", "control", "ctr", 0.05, "user_001")
    engine.record_metric("rec_strategy", "control", "ctr", 0.08, "user_002")
    engine.record_metric("rec_strategy", "treatment_llm", "ctr", 0.12, "user_003")

    stats = engine.get_stats("rec_strategy")
    assert "control" in stats
    assert stats["control"]["ctr"]["count"] == 2


if __name__ == "__main__":
    test_consistent_assignment()
    test_distribution()
    test_thompson_sampling()
    test_custom_experiment()
    test_metrics_recording()
    print("All A/B test engine tests passed!")
