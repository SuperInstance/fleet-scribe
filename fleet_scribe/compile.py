"""scribe/compile.py — Compile stable patterns into optimized check rules.

The One Delta principle says: once you know something is stable (constant, cyclic,
or trending), you don't need to re-examine it — just apply the compiled rule.

This module:
    1. Analyzes state history to find stable patterns
    2. Packages them into Pattern objects with confidence scores
    3. Compiles patterns into fast check functions
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ── Pattern types ────────────────────────────────────────────────────────────

PATTERN_CONSTANT = "constant"
PATTERN_CYCLE = "cycle"
PATTERN_TREND = "trend"
PATTERN_NONE = "none"


@dataclass
class Pattern:
    """A stable pattern detected in state history.

    Attributes:
        key: Dot-path to the field this pattern describes (e.g. "metrics.load")
        pattern_type: One of CONSTANT, CYCLE, TREND, or NONE
        signature: Opaque signature that uniquely identifies this pattern instance
        frequency: How often this pattern fires (per observation unit)
        last_seen: Timestamp of last observation matching this pattern
        confidence: 0.0 to 1.0 — how confident we are in this pattern
        metadata: Additional pattern-specific data (cycle_period, trend_direction, etc.)
    """

    key: str
    pattern_type: str
    signature: str
    frequency: float = 0.0
    last_seen: float = 0.0
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_constant(self) -> bool:
        return self.pattern_type == PATTERN_CONSTANT

    def is_cycle(self) -> bool:
        return self.pattern_type == PATTERN_CYCLE

    def is_trend(self) -> bool:
        return self.pattern_type == PATTERN_TREND


# ── Compiled rule ─────────────────────────────────────────────────────────────

@dataclass
class CompiledRule:
    """A compiled, optimized check function for a pattern.

    Created by calling Pattern.compile(). The rule can be checked
    without re-running full analysis — just apply the fast predicate.
    """

    pattern: Pattern
    check_fn: Callable[[Any], bool]  # Returns True if current value matches pattern
    summary: str  # Human-readable description

    def matches(self, value: Any) -> bool:
        """Check if a value matches this compiled rule."""
        return self.check_fn(value)


# ── Pattern detection ─────────────────────────────────────────────────────────

State = dict[str, Any]


def detect_stable_patterns(history: list[State]) -> list[Pattern]:
    """Analyze state history and return all detected stable patterns.

    Looks for three kinds of stability:
        - Constant: value never changes across all observations
        - Cycle: value repeats on a regular period
        - Trend: value consistently increases or decreases

    Args:
        history: List of state dicts (each from a snapshot), ordered oldest→newest.
                 Must have at least 3 entries for cycle/trend detection.

    Returns:
        List of Pattern objects. Patterns with confidence < 0.5 are excluded.
    """
    if len(history) < 2:
        return []

    patterns: list[Pattern] = []

    # Collect all keys across all states
    all_keys: list[str] = []
    for state in history:
        for key in _flatten_keys(state):
            if key not in all_keys:
                all_keys.append(key)

    now = time.time()

    for key in all_keys:
        values = []
        for state in history:
            val = _get_nested(state, key)
            values.append(val)

        # Constant check
        constant_pattern = _detect_constant(key, values, now)
        if constant_pattern:
            patterns.append(constant_pattern)
            continue  # constants suppress other patterns

        # Only check cycles/trends for numeric values
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        if len(numeric_values) < 3:
            continue

        # Cycle check
        cycle_pattern = _detect_cycle(key, numeric_values, len(history), now)
        if cycle_pattern:
            patterns.append(cycle_pattern)

        # Trend check
        trend_pattern = _detect_trend(key, numeric_values, now)
        if trend_pattern:
            patterns.append(trend_pattern)

    return [p for p in patterns if p.confidence >= 0.5]


def compile(pattern: Pattern) -> CompiledRule:
    """Compile a Pattern into a fast check function.

    The resulting CompiledRule.check_fn(current_value) returns True
    if the value matches the expected pattern behavior — no analysis needed.

    Args:
        pattern: A Pattern object from detect_stable_patterns

    Returns:
        CompiledRule with a fast check_fn
    """
    if pattern.is_constant():
        expected = pattern.metadata.get("constant_value")
        return CompiledRule(
            pattern=pattern,
            check_fn=lambda v: v == expected,
            summary=f"constant({expected!r})",
        )

    elif pattern.is_cycle():
        period = pattern.metadata.get("period", 1)
        phase = pattern.metadata.get("phase", 0)
        amplitude = pattern.metadata.get("amplitude", 0.0)

        def check_cycle(v: float) -> bool:
            if not isinstance(v, (int, float)):
                return False
            expected = phase + period  # simplified: just check approximate match
            return abs(v - expected) <= amplitude * 1.5

        return CompiledRule(
            pattern=pattern,
            check_fn=check_cycle,
            summary=f"cycle(period={period}, phase={phase})",
        )

    elif pattern.is_trend():
        direction = pattern.metadata.get("direction", "up")
        rate = pattern.metadata.get("rate", 0.0)

        def check_trend(v: float) -> bool:
            if not isinstance(v, (int, float)):
                return False
            if direction == "up":
                return v >= rate  # v at or above expected trend line
            else:
                return v <= rate

        return CompiledRule(
            pattern=pattern,
            check_fn=check_trend,
            summary=f"trend({direction}, rate={rate:.4f})",
        )

    else:
        # No-op rule — always returns True (nothing known)
        return CompiledRule(
            pattern=pattern,
            check_fn=lambda _: True,
            summary="noop",
        )


# ── Pattern detection helpers ─────────────────────────────────────────────────


def _flatten_keys(
    d: dict[str, Any],
    prefix: str = "",
) -> list[str]:
    """Flatten a nested dict into dot-path keys."""
    result = []
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        result.append(full_key)
        if isinstance(v, dict):
            result.extend(_flatten_keys(v, full_key))
    return result


def _get_nested(d: dict[str, Any], key: str) -> Any:
    """Get a value from a nested dict using dot-path key."""
    parts = key.split(".")
    current = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _detect_constant(key: str, values: list[Any], now: float) -> Pattern | None:
    """Detect if all values are identical (constant)."""
    if not values:
        return None

    first = values[0]
    identical = all(v == first for v in values[1:])

    if identical:
        signature = f"const:{key}:{repr(first)[:50]}"
        return Pattern(
            key=key,
            pattern_type=PATTERN_CONSTANT,
            signature=signature,
            frequency=1.0,
            last_seen=now,
            confidence=1.0 if len(values) >= 3 else 0.7,
            metadata={"constant_value": first},
        )
    return None


def _detect_cycle(
    key: str,
    values: list[float],
    n_observations: int,
    now: float,
) -> Pattern | None:
    """Detect periodic (oscillating) patterns using autocorrelation."""
    if len(values) < 4:
        return None

    try:
        # Compute autocorrelation at different lags
        mean = statistics.mean(values)
        variance = statistics.variance(values) if len(values) > 1 else 0.0
        if variance < 1e-10:
            return None

        n = len(values)
        max_lag = min(n // 2, 10)

        best_lag = 1
        best_corr = -1.0

        for lag in range(1, max_lag + 1):
            corr = 0.0
            count = 0
            for i in range(n - lag):
                corr += (values[i] - mean) * (values[i + lag] - mean)
                count += 1
            if count > 0:
                corr /= count * variance
                if corr > best_corr:
                    best_corr = corr
                    best_lag = lag

        # Autocorrelation > 0.5 suggests a cycle
        if best_corr > 0.5 and best_lag > 1:
            # Estimate amplitude and phase
            amplitude = max(values) - min(values)
            phase = values[0]  # simplified phase as first value

            signature = f"cycle:{key}:lag={best_lag}:corr={best_corr:.3f}"
            return Pattern(
                key=key,
                pattern_type=PATTERN_CYCLE,
                signature=signature,
                frequency=1.0 / best_lag if best_lag > 0 else 0.0,
                last_seen=now,
                confidence=best_corr,
                metadata={
                    "period": best_lag,
                    "autocorrelation": best_corr,
                    "amplitude": amplitude,
                    "phase": phase,
                    "n_observations": n_observations,
                },
            )
    except Exception:  # noqa: BLE001, S110 — any stats/math failure means "no cycle pattern"; None is the contract
        pass

    return None


def _detect_trend(
    key: str,
    values: list[float],
    now: float,
) -> Pattern | None:
    """Detect monotonic (always-up or always-down) trends."""
    if len(values) < 3:
        return None

    # Compute direction consistency
    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    if not deltas:
        return None

    positive = sum(1 for d in deltas if d > 0)
    negative = sum(1 for d in deltas if d < 0)

    total = len(deltas)
    consistency = max(positive, negative) / total if total > 0 else 0.0

    if consistency < 0.8:
        return None  # Not clearly trending

    direction = "up" if positive > negative else "down"

    # Compute average rate of change
    rate = sum(deltas) / len(deltas)

    # Predict next value
    predicted = values[-1] + rate

    signature = f"trend:{key}:{direction}:{rate:.6f}"
    return Pattern(
        key=key,
        pattern_type=PATTERN_TREND,
        signature=signature,
        frequency=1.0,
        last_seen=now,
        confidence=consistency,
        metadata={
            "direction": direction,
            "rate": rate,
            "predicted": predicted,
            "delta_avg": rate,
            "deltas_std": statistics.stdev(deltas) if len(deltas) > 1 else 0.0,
        },
    )