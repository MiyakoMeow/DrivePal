"""测试个性化组指标."""

from experiments.ablation.personalization_group import _compute_stability


def test_stability_no_oscillation():
    """Given weights stable after switch, stability should be near 0."""
    wh = [
        {"weights": {"meeting": 0.9, "travel": 0.5}},
        {"weights": {"meeting": 0.9, "travel": 0.5}},
        {"weights": {"meeting": 0.3, "travel": 0.5}},
        {"weights": {"meeting": 0.3, "travel": 0.5}},
        {"weights": {"meeting": 0.3, "travel": 0.5}},
        {"weights": {"meeting": 0.3, "travel": 0.5}},
        {"weights": {"meeting": 0.3, "travel": 0.5}},
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 7)]
    result = _compute_stability(wh, stages)
    assert result == 0.0


def test_stability_with_oscillation():
    """Given weights oscillate after switch, stability should be > 0."""
    wh = [
        {"weights": {"meeting": 0.9, "travel": 0.5}},
        {"weights": {"meeting": 0.9, "travel": 0.5}},
        {"weights": {"meeting": 0.3, "travel": 0.5}},
        {"weights": {"meeting": 0.7, "travel": 0.5}},
        {"weights": {"meeting": 0.2, "travel": 0.5}},
        {"weights": {"meeting": 0.6, "travel": 0.5}},
        {"weights": {"meeting": 0.4, "travel": 0.5}},
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 7)]
    result = _compute_stability(wh, stages)
    assert result > 0.0


def test_stability_initial_state_skipped():
    """Given all weights at 0.5 (initial), switch point should be skipped."""
    wh = [
        {"weights": {"meeting": 0.5, "travel": 0.5}},
        {"weights": {"meeting": 0.5, "travel": 0.5}},
        {"weights": {"meeting": 0.5, "travel": 0.5}},
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 3)]
    result = _compute_stability(wh, stages)
    assert result == 0.0
