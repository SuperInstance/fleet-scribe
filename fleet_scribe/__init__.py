"""fleet_scribe — One Delta: only perceive when the gradient changes.

The fleet-scribe library implements the One Delta principle:
    1. Cache everything
    2. Detect only what changes (delta)
    3. Compile stable patterns once
    4. Automate predictable responses
    5. Only spend compute on what's different from a moment ago

Modules:
    core    — DeltaDetection: compare state to baseline, return only changes
    cache   — FileCache: persistent cache for baselines and fingerprints
    compile — Pattern detection and compilation into fast check functions
    automate — Action automation when deltas match registered patterns

Quick start:
    from fleet_scribe import Scribe

    scribe = Scribe(cache_dir="/tmp/scribe_cache")
    deltas = scribe.watch(current_state)
    scribe.compile_all(history)
"""

from .core import DeltaDetection
from .cache import FileCache
from .compile import Pattern, CompiledRule, detect_stable_patterns, compile
from .automate import Automator, Action

__all__ = [
    "Scribe",
    "DeltaDetection",
    "FileCache",
    "Pattern",
    "CompiledRule",
    "detect_stable_patterns",
    "compile",
    "Automator",
    "Action",
    "__version__",
]

__version__ = "0.1.0"


# ── Main Scribe class ─────────────────────────────────────────────────────────

from typing import Any, Dict, List, Optional


class Scribe:
    """Unified interface for One Delta state observation.

    Scribe combines delta detection, persistent caching, pattern compilation,
    and action automation into a single entry point.

    Usage:
        scribe = Scribe(cache_dir="/tmp/my_scribe")
        scribe.cache.set("baseline:v1", initial_state)

        # In your observation loop:
        deltas = scribe.watch(current_state)
        if deltas["magnitude"] > 0.1:
            print("State changed!", deltas)

        # After several cycles, compile stable patterns:
        patterns = scribe.compile_all(observation_history)
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        threshold: float = 0.0,
        baseline_key: str = "default:baseline",
    ):
        """Initialize Scribe.

        Args:
            cache_dir: Directory for FileCache. Defaults to ~/.cache/fleet-scribe/
            threshold: Minimum delta magnitude to report. 0 = report all changes.
            baseline_key: Cache key for the current baseline state.
        """
        self._threshold = threshold
        self._baseline_key = baseline_key

        self.cache = FileCache(cache_dir)
        self.detector = DeltaDetection(threshold=threshold)
        self.automator = Automator()

        self._baseline: Optional[Dict[str, Any]] = None
        self._patterns: List[Any] = []
        self._observation_count = 0

        # Try to load existing baseline from cache
        baseline_val, _ = self.cache.get(baseline_key)
        if baseline_val is not None:
            self._baseline = baseline_val

    def watch(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Compare current state against baseline, return deltas.

        This is the main entry point for the observation loop. On the first
        call, the state becomes the baseline and an empty delta is returned.

        Args:
            state: Current state dict

        Returns:
            Delta dict with 'added', 'removed', 'changed', 'magnitude'
        """
        if self._baseline is None:
            # First observation — establish baseline
            self._baseline = dict(state)
            self.cache.set(self._baseline_key, self._baseline)
            return {
                "added": {},
                "removed": {},
                "changed": {},
                "magnitude": 0.0,
                "is_baseline": True,
            }

        # Compare against baseline
        deltas = self.detector.delta(state, self._baseline)
        deltas["is_baseline"] = False
        self._observation_count += 1

        # If there was a meaningful change, update the baseline
        if deltas["magnitude"] > self._threshold:
            self._baseline = dict(state)
            self.cache.set(self._baseline_key, self._baseline)

        # Fire any matching automator rules
        self.automator.watch(deltas, state)

        return deltas

    def set_baseline(self, state: Dict[str, Any]) -> None:
        """Manually set the baseline state."""
        self._baseline = dict(state)
        self.cache.set(self._baseline_key, self._baseline)

    def compile_all(self, history: List[Dict[str, Any]]) -> List[Any]:
        """Analyze history and compile stable patterns.

        Args:
            history: List of state dicts (oldest first), >= 2 entries

        Returns:
            List of Pattern objects with confidence >= 0.5
        """
        patterns = detect_stable_patterns(history)
        self._patterns = patterns

        # Pre-compile all patterns into rules
        compiled = [compile(p) for p in patterns]
        return compiled

    @property
    def patterns(self) -> List[Any]:
        """Return the list of detected patterns from last compile_all() call."""
        return self._patterns

    @property
    def observation_count(self) -> int:
        """Total number of watch() calls since initialization."""
        return self._observation_count

    @property
    def stats(self) -> Dict[str, Any]:
        """Return combined statistics from cache, detector, and automator."""
        return {
            "cache": self.cache.stats,
            "automator": self.automator.stats,
            "patterns_detected": len(self._patterns),
            "observations": self._observation_count,
            "has_baseline": self._baseline is not None,
        }