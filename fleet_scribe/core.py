"""scribe/core.py — Delta detection engine for the One Delta principle.

Only perceive when the gradient changes. Cache everything. Compile stable parts.
"""
from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from typing import Any

import numpy as np


class DeltaDetection:
    """Detects changes (deltas) between current state and cached baseline.

    The core insight of One Delta: most of the world is stable. We only need
    to perceive what actually changes. This engine compares current state to
    a cached baseline and returns only what is different.

    Usage:
        detector = DeltaDetection(threshold=0.1)
        deltas = detector.delta(current_state, baseline_state)
        key = detector.cache_key(state)
    """

    def __init__(self, threshold: float = 0.0):
        """Initialize with optional threshold.

        Args:
            threshold: Minimum magnitude of change to report. Changes below
                       this threshold are considered noise and ignored.
                       Default 0.0 means report all changes.
        """
        self.threshold = threshold
        self._float_buffer: list[np.ndarray] = []

    # ── Core delta detection ─────────────────────────────────────────────────

    def delta(
        self,
        state: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare current state to baseline, return only what changed.

        Returns a dict with keys:
            - added: keys in state but not in baseline
            - removed: keys in baseline but not in state
            - changed: keys whose values differ
            - magnitude: float representing total size of change (0.0 = identical)

        Each changed value includes its old and new representation.

        Args:
            state: Current state dict
            baseline: Baseline (cached) state dict

        Returns:
            Dict with 'added', 'removed', 'changed', 'magnitude'
        """
        result: dict[str, Any] = {
            "added": {},
            "removed": {},
            "changed": {},
            "magnitude": 0.0,
        }

        state_keys = set(state.keys())
        baseline_keys = set(baseline.keys())

        # Detect additions
        for key in state_keys - baseline_keys:
            val = state[key]
            if self._magnitude(val) >= self.threshold:
                result["added"][key] = self._repr(val)
                result["magnitude"] += self._magnitude(val)

        # Detect removals
        for key in baseline_keys - state_keys:
            val = baseline[key]
            if self._magnitude(val) >= self.threshold:
                result["removed"][key] = self._repr(val)
                result["magnitude"] += self._magnitude(val)

        # Detect changes in common keys
        for key in state_keys & baseline_keys:
            sv = state[key]
            bv = baseline[key]
            mag = self._diff_magnitude(sv, bv)
            if mag > 0 and mag >= self.threshold:
                result["changed"][key] = {
                    "before": self._repr(bv),
                    "after": self._repr(sv),
                    "magnitude": mag,
                }
                result["magnitude"] += mag

        result["magnitude"] = float(result["magnitude"])
        return result

    def delta_array(
        self,
        current: np.ndarray,
        baseline: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        """Compare two float arrays, return changed indices and total magnitude.

        Uses element-wise relative difference. NaN in either array counts as change.

        Args:
            current: Current float array
            baseline: Baseline float array (must be same shape as current)

        Returns:
            Tuple of (changed_mask, total_magnitude)
            changed_mask is a boolean array of same shape
            total_magnitude is sum of absolute relative differences
        """
        current = np.asarray(current, dtype=np.float64)
        baseline = np.asarray(baseline, dtype=np.float64)

        if current.shape != baseline.shape:
            raise ValueError(
                f"Shape mismatch: current {current.shape} vs baseline {baseline.shape}"
            )

        # Element-wise relative difference
        abs_diff = np.abs(current - baseline)
        abs_baseline = np.abs(baseline)

        # Avoid division by zero: where baseline is ~0, use abs_diff directly
        with np.errstate(divide="ignore", invalid="ignore"):
            rel_diff = np.where(
                abs_baseline > 1e-10,
                abs_diff / (abs_baseline + 1e-10),
                abs_diff,
            )

        # Mask where relative difference exceeds threshold AND magnitude > 0
        changed = (rel_diff >= self.threshold) & (rel_diff > 0)
        total_magnitude = float(np.sum(rel_diff))

        return changed, total_magnitude

    def delta_text(
        self,
        current: str,
        baseline: str,
    ) -> dict[str, Any]:
        """Compare two text strings, report character-level changes.

        Returns edit distance, changed line ranges, and a summary.

        Args:
            current: Current text
            baseline: Baseline (cached) text

        Returns:
            Dict with 'changed' (bool), 'edit_distance', 'lines_added',
            'lines_removed', 'summary'
        """
        current_lines = current.splitlines(keepends=True)
        baseline_lines = baseline.splitlines(keepends=True)

        # Line-level diff via difflib's LCS-based opcode stream
        matcher = SequenceMatcher(None, baseline_lines, current_lines)

        added_lines = []
        removed_lines = []
        common_lines = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                common_lines.extend(range(i1, i2))
            elif tag == 'delete':
                removed_lines.extend(range(i1, i2))
            elif tag == 'insert':
                added_lines.extend(range(j1, j2))
            elif tag == 'replace':
                removed_lines.extend(range(i1, i2))
                added_lines.extend(range(j1, j2))

        # Levenshtein distance at line level
        edit_distance = len(added_lines) + len(removed_lines)

        result = {
            "changed": edit_distance > 0,
            "edit_distance": edit_distance,
            "lines_added": len(added_lines),
            "lines_removed": len(removed_lines),
            "total_lines_current": len(current_lines),
            "total_lines_baseline": len(baseline_lines),
            "summary": (
                f"{len(added_lines)} lines added, "
                f"{len(removed_lines)} lines removed, "
                f"{len(common_lines)} unchanged"
            ),
        }
        return result

    # ── State fingerprinting ─────────────────────────────────────────────────

    def cache_key(self, state: dict[str, Any] | str) -> str:
        """Generate a deterministic hash key for state.

        For dicts: serializes with sorted keys and deterministic ordering.
        For strings: hashes directly.
        For arrays: uses base64-encoded raw bytes.

        Args:
            state: State dict, string, or numpy array

        Returns:
            16-character hex string (first 8 bytes of SHA-256)
        """
        if isinstance(state, dict):
            # Canonical JSON with sorted keys
            canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
            raw = canonical.encode("utf-8")
        elif isinstance(state, str):
            raw = state.encode("utf-8")
        elif isinstance(state, (list, tuple)):
            # Try as numeric array
            try:
                arr = np.asarray(state, dtype=np.float64)
                raw = arr.tobytes()
            except (ValueError, TypeError):
                canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
                raw = canonical.encode("utf-8")
        elif isinstance(state, np.ndarray):
            raw = state.tobytes()
        else:
            raw = repr(state).encode("utf-8")

        digest = hashlib.sha256(raw).digest()
        return digest[:8].hex()

    # ── Internal helpers ────────────────────────────────────────────────────

    def _repr(self, value: Any) -> str:
        """Create a string representation safe for caching."""
        if isinstance(value, np.ndarray):
            return f"ndarray({value.shape}, dtype={value.dtype.name})"
        if isinstance(value, (list, tuple)) and len(value) > 10:
            return f"{type(value).__name__}[len={len(value)}]"
        if isinstance(value, dict):
            return f"dict[len={len(value)}]"
        try:
            return json.dumps(value, sort_keys=True)[:200]
        except Exception:  # noqa: BLE001 — deliberate fallback: any non-serializable value degrades to repr()
            return repr(value)[:200]

    def _magnitude(self, value: Any) -> float:
        """Compute a magnitude score for a value (0.0 = nothing, higher = bigger)."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return abs(float(value))
        if isinstance(value, np.ndarray):
            return float(np.sum(np.abs(value)))
        if isinstance(value, dict):
            return float(len(value))
        if isinstance(value, (list, tuple)):
            return float(len(value))
        if isinstance(value, str):
            return float(len(value))
        return 1.0

    def _diff_magnitude(self, current: Any, baseline: Any) -> float:
        """Compute magnitude of difference between two values."""
        # Both numeric
        if isinstance(current, (int, float)) and isinstance(baseline, (int, float)):
            return abs(float(current) - float(baseline))

        # Both arrays
        if isinstance(current, np.ndarray) and isinstance(baseline, np.ndarray):
            try:
                _, mag = self.delta_array(current, baseline)
                return mag
            except ValueError:
                return float(np.sum(np.abs(current - baseline)))

        # Both dicts — recurse
        if isinstance(current, dict) and isinstance(baseline, dict):
            result = self.delta(current, baseline)
            return result["magnitude"]

        # Both strings
        if isinstance(current, str) and isinstance(baseline, str):
            result = self.delta_text(current, baseline)
            return float(result["edit_distance"])

        # Type mismatch or other
        if type(current) is not type(baseline):
            return 1.0
        return 0.0