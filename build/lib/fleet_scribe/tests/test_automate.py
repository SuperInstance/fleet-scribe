"""Tests for fleet_scribe.automate — Action automation."""

import time
from fleet_scribe.automate import (
    Action,
    Automator,
    ACTION_FUNCTION,
    ACTION_HTTP,
    ACTION_SHELL,
)


class TestAction:
    def test_can_fire_no_throttle(self):
        a = Action(ACTION_FUNCTION, lambda _: None, throttle_seconds=0.0)
        assert a.can_fire()

    def test_can_fire_respects_throttle(self):
        a = Action(ACTION_FUNCTION, lambda _: None, throttle_seconds=10.0)
        a.mark_fired()
        assert not a.can_fire()
        # Almost immediately after, still can't fire
        assert not a.can_fire()

    def test_can_fire_after_throttle_passes(self):
        a = Action(ACTION_FUNCTION, lambda _: None, throttle_seconds=0.01)
        a.mark_fired()
        time.sleep(0.015)
        assert a.can_fire()


class TestAutomator:
    def setup_method(self):
        self.automator = Automator()

    def teardown_method(self):
        self.automator.stop()

    def test_register_http_action(self):
        self.automator.on_delta(
            pattern="metrics.load",
            action_type=ACTION_HTTP,
            target="https://example.com/webhook",
            throttle_seconds=60.0,
        )
        assert self.automator.stats["rules_registered"] == 1

    def test_register_shell_action(self):
        self.automator.on_delta(
            pattern="files.*",
            action_type=ACTION_SHELL,
            target="echo 'changed: {{changed}}'",
            throttle_seconds=0.0,
        )
        assert "files.*" in self.automator._rules

    def test_watch_fires_on_matching_pattern(self):
        fired_events = []

        def capture(payload):
            fired_events.append(payload)

        self.automator.on_delta(
            pattern="mykey",
            action_type=ACTION_FUNCTION,
            target=capture,
            throttle_seconds=0.0,
        )

        delta_result = {
            "added": {},
            "removed": {},
            "changed": {"mykey": {"before": 1, "after": 2}},
            "magnitude": 1.0,
        }
        fired = self.automator.watch(delta_result, {"mykey": 2})
        assert "mykey" in fired
        # Wait for async worker
        time.sleep(0.1)
        assert len(fired_events) == 1

    def test_watch_matches_added(self):
        fired = []
        self.automator.on_delta(
            pattern="newkey",
            action_type=ACTION_FUNCTION,
            target=lambda p: fired.append(p),
            throttle_seconds=0.0,
        )
        delta_result = {
            "added": {"newkey": "value"},
            "removed": {},
            "changed": {},
            "magnitude": 1.0,
        }
        fired_result = self.automator.watch(delta_result, {"newkey": "value"})
        time.sleep(0.1)
        assert "newkey" in fired_result

    def test_watch_matches_removed(self):
        fired = []
        self.automator.on_delta(
            pattern="oldkey",
            action_type=ACTION_FUNCTION,
            target=lambda p: fired.append(p),
            throttle_seconds=0.0,
        )
        delta_result = {
            "added": {},
            "removed": {"oldkey": "value"},
            "changed": {},
            "magnitude": 1.0,
        }
        fired_result = self.automator.watch(delta_result, {})
        time.sleep(0.1)
        assert "oldkey" in fired_result

    def test_watch_catches_all_with_wildcard(self):
        fired = []
        self.automator.on_delta(
            pattern="*",
            action_type=ACTION_FUNCTION,
            target=lambda p: fired.append(p),
            throttle_seconds=0.0,
        )
        delta_result = {
            "added": {"anykey": 1},
            "removed": {},
            "changed": {},
            "magnitude": 1.0,
        }
        fired_result = self.automator.watch(delta_result, {})
        time.sleep(0.1)
        assert "*" in fired_result

    def test_watch_respects_throttle(self):
        fired_count = [0]

        def count(payload):
            fired_count[0] += 1

        self.automator.on_delta(
            pattern="throttled",
            action_type=ACTION_FUNCTION,
            target=count,
            throttle_seconds=10.0,  # long throttle
        )

        delta_result = {
            "added": {"throttled": 1},
            "removed": {},
            "changed": {},
            "magnitude": 1.0,
        }

        # Fire first time
        self.automator.watch(delta_result, {})
        time.sleep(0.1)
        assert fired_count[0] == 1

        # Fire again immediately — should be throttled
        self.automator.watch(delta_result, {})
        time.sleep(0.1)
        # Throttled, so still only 1
        assert fired_count[0] == 1

    def test_stats_track_fire_counts(self):
        self.automator.on_delta(
            pattern="x",
            action_type=ACTION_FUNCTION,
            target=lambda _: None,
            throttle_seconds=0.0,
        )
        for _ in range(3):
            self.automator.watch(
                {"added": {"x": 1}, "removed": {}, "changed": {}, "magnitude": 1.0},
                {},
            )
        time.sleep(0.1)
        stats = self.automator.stats
        assert stats["fire_counts"]["x"] == 3
        assert stats["total_fires"] == 3

    def test_build_payload_includes_current_state(self):
        payloads = []

        def capture(payload):
            payloads.append(payload)

        self.automator.on_delta(
            pattern="key1",
            action_type=ACTION_FUNCTION,
            target=capture,
            throttle_seconds=0.0,
        )
        self.automator.watch(
            {"added": {}, "removed": {}, "changed": {"key1": {}}, "magnitude": 0.0},
            {"key1": "current_value"},
        )
        time.sleep(0.1)
        assert len(payloads) == 1
        assert payloads[0]["current_state"] == "current_value"