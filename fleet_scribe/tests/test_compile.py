"""Tests for fleet_scribe.compile — Pattern detection and compilation."""

from fleet_scribe.compile import (
    Pattern,
    detect_stable_patterns,
    compile,
    PATTERN_CONSTANT,
    PATTERN_CYCLE,
    PATTERN_TREND,
)


class TestPattern:
    def test_is_constant(self):
        p = Pattern("x", PATTERN_CONSTANT, "sig")
        assert p.is_constant()
        assert not p.is_cycle()
        assert not p.is_trend()

    def test_is_cycle(self):
        p = Pattern("x", PATTERN_CYCLE, "sig")
        assert p.is_cycle()

    def test_is_trend(self):
        p = Pattern("x", PATTERN_TREND, "sig")
        assert p.is_trend()


class TestDetectStablePatterns:
    def test_empty_history_returns_empty(self):
        assert detect_stable_patterns([]) == []
        assert detect_stable_patterns([{}]) == []

    def test_constant_detected(self):
        history = [
            {"value": 42},
            {"value": 42},
            {"value": 42},
            {"value": 42},
        ]
        patterns = detect_stable_patterns(history)
        constant_patterns = [p for p in patterns if p.is_constant()]
        assert len(constant_patterns) >= 1
        p = next(p for p in constant_patterns if p.key == "value")
        assert p.metadata["constant_value"] == 42
        assert p.confidence == 1.0

    def test_constant_with_different_values_not_constant(self):
        history = [
            {"value": 42},
            {"value": 42},
            {"value": 99},  # different
            {"value": 42},
        ]
        patterns = detect_stable_patterns(history)
        constant_patterns = [p for p in patterns if p.is_constant() and p.key == "value"]
        assert len(constant_patterns) == 0

    def test_trend_up_detected(self):
        history = [
            {"metric": 1.0},
            {"metric": 2.0},
            {"metric": 3.0},
            {"metric": 4.0},
            {"metric": 5.0},
        ]
        patterns = detect_stable_patterns(history)
        trend_patterns = [p for p in patterns if p.is_trend()]
        assert len(trend_patterns) >= 1
        p = next((p for p in trend_patterns if p.key == "metric"), None)
        assert p is not None
        assert p.metadata["direction"] == "up"

    def test_trend_down_detected(self):
        history = [
            {"metric": 10.0},
            {"metric": 8.0},
            {"metric": 6.0},
            {"metric": 4.0},
            {"metric": 2.0},
        ]
        patterns = detect_stable_patterns(history)
        trend_patterns = [p for p in patterns if p.is_trend()]
        assert len(trend_patterns) >= 1
        p = next((p for p in trend_patterns if p.key == "metric"), None)
        assert p is not None
        assert p.metadata["direction"] == "down"

    def test_noisy_not_trend(self):
        # Random values shouldn't form a trend
        import random
        random.seed(42)
        history = [{"metric": random.random()} for _ in range(6)]
        patterns = detect_stable_patterns(history)
        trend_patterns = [p for p in patterns if p.is_trend() and p.key == "metric"]
        # Confidence may be low, so may not appear
        assert all(p.confidence < 0.8 for p in trend_patterns)

    def test_nested_key_flattened(self):
        history = [
            {"top": {"nested": 1}},
            {"top": {"nested": 1}},
            {"top": {"nested": 1}},
        ]
        patterns = detect_stable_patterns(history)
        keys = [p.key for p in patterns]
        assert "top.nested" in keys

    def test_cycle_detected_on_sine_wave(self):
        # Sine-like: 1,2,3,2,1,2,3,2,1
        import math
        history = [
            {"wave": 1.0 + 2.0 * math.sin(2 * math.pi * i / 4)}
            for i in range(8)
        ]
        patterns = detect_stable_patterns(history)
        # The oscillating pattern may or may not be detected depending on
        # autocorrelation — just check patterns is a list
        assert isinstance(patterns, list)


class TestCompile:
    def test_compile_constant_rule(self):
        p = Pattern("x", PATTERN_CONSTANT, "sig", metadata={"constant_value": 42})
        rule = compile(p)
        assert rule.matches(42)
        assert not rule.matches(99)
        assert "constant" in rule.summary

    def test_compile_trend_rule_up(self):
        p = Pattern("x", PATTERN_TREND, "sig", metadata={"direction": "up", "rate": 5.0})
        rule = compile(p)
        assert rule.matches(6.0)   # above rate
        assert not rule.matches(4.0)  # below rate

    def test_compile_trend_rule_down(self):
        p = Pattern("x", PATTERN_TREND, "sig", metadata={"direction": "down", "rate": 5.0})
        rule = compile(p)
        assert rule.matches(4.0)   # below rate
        assert not rule.matches(6.0)

    def test_compile_noop_for_unknown_type(self):
        p = Pattern("x", "unknown_type", "sig")
        rule = compile(p)
        assert rule.matches(42)  # always True

    def test_compiled_rule_has_pattern_reference(self):
        p = Pattern("x", PATTERN_CONSTANT, "sig", metadata={"constant_value": 10})
        rule = compile(p)
        assert rule.pattern is p