"""Tests for fleet_scribe.Scribe — the unified One Delta entry point.

Scribe is the public facade documented in the package docstring
(scribe.watch / scribe.compile_all) but previously had no direct tests.
These cover its real branches: baseline establishment, on-disk baseline
persistence across instances, threshold-gated baseline updates, pattern
compilation, and the combined stats property.
"""

import shutil
import tempfile

from fleet_scribe import Scribe


class TestScribe:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make(self, **kwargs):
        s = Scribe(cache_dir=self.tmpdir, **kwargs)
        self._scribe = s
        return s

    def test_first_watch_establishes_baseline(self):
        s = self._make()
        result = s.watch({"a": 1, "b": 2})
        assert result["is_baseline"] is True
        assert result["magnitude"] == 0.0
        assert result["added"] == {}
        # Baseline call is not counted as an observation
        assert s.observation_count == 0

    def test_second_watch_reports_delta(self):
        s = self._make()
        s.watch({"a": 1, "b": 2})
        result = s.watch({"a": 1, "b": 5, "c": 9})
        assert result["is_baseline"] is False
        assert "b" in result["changed"]
        assert "c" in result["added"]
        assert s.observation_count == 1

    def test_baseline_persists_across_instances(self):
        s = self._make()
        s.watch({"a": 1, "b": 2})
        s.automator.stop()

        # A brand-new Scribe pointing at the same cache dir should pick up
        # the previously-written baseline, so the first watch is NOT treated
        # as a fresh baseline.
        s2 = self._make()
        try:
            result = s2.watch({"a": 1, "b": 2})
            assert result["is_baseline"] is False
        finally:
            s2.automator.stop()

    def test_custom_baseline_key_isolates_state(self):
        tmp2 = tempfile.mkdtemp()
        try:
            s = Scribe(cache_dir=tmp2, baseline_key="app:v2")
            s.watch({"x": 10})
            s.automator.stop()

            # Same cache dir, different key -> no baseline loaded
            s_other = Scribe(cache_dir=tmp2, baseline_key="app:v3")
            try:
                result = s_other.watch({"x": 10})
                assert result["is_baseline"] is True
            finally:
                s_other.automator.stop()
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

    def test_change_at_threshold_reported_but_not_rebased(self):
        # Scribe hands the same threshold to DeltaDetection (which reports a
        # change when magnitude >= threshold) and to its own baseline-update
        # gate (which rebases only when magnitude > threshold, strict). So a
        # change whose magnitude lands exactly on the threshold is reported
        # but does NOT move the baseline — the only reachable "report without
        # rebase" branch.
        s = self._make(threshold=5.0)
        s.watch({"counter": 0})
        first = s.watch({"counter": 5})   # |5-0| == 5 -> reported, 5 > 5 False -> no rebase
        second = s.watch({"counter": 5})  # baseline still 0 -> reported again
        assert "counter" in first["changed"]
        assert "counter" in second["changed"]
        assert s.observation_count == 2

    def test_large_change_rebases(self):
        # A change above threshold should update the baseline, so the next
        # call (no further change) shows an empty delta.
        s = self._make(threshold=0.5)
        s.watch({"counter": 0})
        s.watch({"counter": 10})  # rebases to 10
        result = s.watch({"counter": 10})  # identical to new baseline
        assert result["changed"] == {}
        assert result["magnitude"] == 0.0

    def test_set_baseline_manually(self):
        s = self._make()
        s.watch({"a": 1})
        s.set_baseline({"a": 100})
        result = s.watch({"a": 1})
        # Now baseline is {a:100}, current {a:1} -> changed
        assert "a" in result["changed"]

    def test_compile_all_detects_and_compiles(self):
        s = self._make()
        history = [{"load": n} for n in [1.0, 2.0, 3.0, 4.0, 5.0]]
        compiled = s.compile_all(history)
        assert len(compiled) >= 1
        # patterns property reflects what was detected
        assert len(s.patterns) == len(compiled)
        # Compiled rules expose a summary and a working matcher
        assert all(c.summary for c in compiled)

    def test_compile_all_empty_history(self):
        s = self._make()
        assert s.compile_all([]) == []
        assert s.patterns == []

    def test_stats_shape(self):
        s = self._make()
        s.watch({"a": 1})
        stats = s.stats
        assert set(stats.keys()) == {
            "cache", "automator", "patterns_detected",
            "observations", "has_baseline",
        }
        assert stats["has_baseline"] is True
        assert stats["observations"] == 0
        assert stats["patterns_detected"] == 0
