"""Tests for fleet_scribe.core — DeltaDetection."""

import pytest
import numpy as np
from fleet_scribe.core import DeltaDetection


class TestDeltaDetection:
    def setup_method(self):
        self.detector = DeltaDetection(threshold=0.0)

    # ── Basic delta ────────────────────────────────────────────────────────

    def test_identical_states_return_empty_delta(self):
        state = {"a": 1, "b": 2, "c": "hello"}
        baseline = {"a": 1, "b": 2, "c": "hello"}
        result = self.detector.delta(state, baseline)
        assert result["added"] == {}
        assert result["removed"] == {}
        assert result["added"] == {}
        assert result["magnitude"] == 0.0

    def test_added_keys_detected(self):
        state = {"a": 1, "b": 2, "c": 3}
        baseline = {"a": 1, "b": 2}
        result = self.detector.delta(state, baseline)
        assert "c" in result["added"]
        assert "c" not in result["changed"]

    def test_removed_keys_detected(self):
        state = {"a": 1}
        baseline = {"a": 1, "b": 2, "c": 3}
        result = self.detector.delta(state, baseline)
        assert "b" in result["removed"]
        assert "c" in result["removed"]

    def test_changed_values_detected(self):
        state = {"a": 10, "b": 2}
        baseline = {"a": 1, "b": 2}
        result = self.detector.delta(state, baseline)
        assert "a" in result["changed"]
        assert result["changed"]["a"]["before"] == self.detector._repr(1)
        assert result["changed"]["a"]["after"] == self.detector._repr(10)

    def test_threshold_suppresses_small_changes(self):
        # threshold=0.1 means values must change by at least 0.1
        d = DeltaDetection(threshold=0.1)
        state = {"x": 1.05, "y": 2}
        baseline = {"x": 1.0, "y": 2}
        result = d.delta(state, baseline)
        # 0.05 relative change is below threshold
        assert "x" not in result["changed"]

    def test_magnitude_accumulates(self):
        state = {"a": 10, "b": 20}
        baseline = {"a": 1, "b": 2}
        result = self.detector.delta(state, baseline)
        # |10-1| + |20-2| = 9 + 18 = 27
        assert result["magnitude"] == 27.0

    def test_nested_dict_delta(self):
        state = {"top": {"nested": 99}}
        baseline = {"top": {"nested": 1}}
        result = self.detector.delta(state, baseline)
        assert "top" in result["changed"]

    # ── Array delta ─────────────────────────────────────────────────────────

    def test_delta_array_identical(self):
        current = np.array([1.0, 2.0, 3.0])
        baseline = np.array([1.0, 2.0, 3.0])
        changed, mag = self.detector.delta_array(current, baseline)
        assert not changed.any()
        assert mag == 0.0

    def test_delta_array_changes_detected(self):
        current = np.array([10.0, 2.0, 3.0])
        baseline = np.array([1.0, 2.0, 3.0])
        changed, mag = self.detector.delta_array(current, baseline)
        assert changed[0]
        assert not changed[1]
        assert not changed[2]
        assert mag == pytest.approx(9.0)  # |10-1|/|1| = 9

    def test_delta_array_shape_mismatch_raises(self):
        current = np.array([1.0, 2.0])
        baseline = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError):
            self.detector.delta_array(current, baseline)

    # ── Text delta ──────────────────────────────────────────────────────────

    def test_delta_text_identical(self):
        text = "line1\nline2\nline3"
        result = self.detector.delta_text(text, text)
        assert not result["changed"]
        assert result["edit_distance"] == 0

    def test_delta_text_lines_added(self):
        current = "line1\nline2\nline3"
        baseline = "line1\nline2"
        result = self.detector.delta_text(current, baseline)
        assert result["changed"]
        assert result["lines_added"] >= 1

    def test_delta_text_lines_removed(self):
        current = "line1"
        baseline = "line1\nline2\nline3"
        result = self.detector.delta_text(current, baseline)
        assert result["changed"]
        assert result["lines_removed"] >= 1

    # ── Cache key ───────────────────────────────────────────────────────────

    def test_cache_key_deterministic(self):
        state = {"a": 1, "b": 2}
        key1 = self.detector.cache_key(state)
        key2 = self.detector.cache_key(state)
        assert key1 == key2

    def test_cache_key_order_independent(self):
        # Two dicts with same keys/values in different order
        state1 = {"a": 1, "b": 2}
        state2 = {"b": 2, "a": 1}
        assert self.detector.cache_key(state1) == self.detector.cache_key(state2)

    def test_cache_key_string(self):
        key1 = self.detector.cache_key("hello world")
        key2 = self.detector.cache_key("hello world")
        assert key1 == key2
        assert len(key1) == 16

    def test_cache_key_array(self):
        arr1 = np.array([1.0, 2.0, 3.0])
        arr2 = np.array([1.0, 2.0, 3.0])
        assert self.detector.cache_key(arr1) == self.detector.cache_key(arr2)

    # ── Threshold edge cases ─────────────────────────────────────────────────

    def test_threshold_zero_reports_all(self):
        d = DeltaDetection(threshold=0.0)
        state = {"x": 1.001, "y": 2}
        baseline = {"x": 1.0, "y": 2}
        result = d.delta(state, baseline)
        assert "x" in result["changed"]

    def test_threshold_high_suppresses_all(self):
        d = DeltaDetection(threshold=100.0)
        state = {"x": 200}
        baseline = {"x": 1}
        result = d.delta(state, baseline)
        assert result["magnitude"] == 199.0

    # ── Repr safety ──────────────────────────────────────────────────────────

    def test_repr_truncates_long_strings(self):
        long_str = "x" * 500
        r = self.detector._repr(long_str)
        assert len(r) <= 200

    def test_repr_handles_ndarray(self):
        arr = np.array([1, 2, 3])
        r = self.detector._repr(arr)
        assert "ndarray" in r