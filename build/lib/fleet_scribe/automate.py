"""scribe/automate.py — Action automation when deltas match registered patterns.

The One Delta principle: once a delta is detected and matches a compiled
pattern, the response should be automatic — no human in the loop.

This module wires together:
    1. Delta patterns (from compile.py)
    2. Triggers (HTTP webhooks, shell commands, function calls, PLATO tiles)
    3. Throttling (cooldown per pattern to avoid flooding)
"""

import json
import queue
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List


# ── Action types ─────────────────────────────────────────────────────────────

ACTION_FUNCTION = "function"
ACTION_HTTP = "http"
ACTION_SHELL = "shell"
ACTION_PLATO = "plato"


@dataclass
class Action:
    """An action to be triggered when a delta matches a pattern.

    Attributes:
        action_type: One of function, http, shell, plato
        target: The thing to invoke (function ref, URL, command string, PLATO params)
        throttle_seconds: Minimum seconds between consecutive firings
        last_fired: Timestamp of last firing (managed internally)
    """

    action_type: str
    target: Any
    throttle_seconds: float = 0.0
    last_fired: float = field(default_factory=lambda: 0.0, repr=False)

    def can_fire(self) -> bool:
        """Check if enough time has passed since last firing (respecting throttle)."""
        if self.throttle_seconds <= 0:
            return True
        return (time.time() - self.last_fired) >= self.throttle_seconds

    def mark_fired(self) -> None:
        """Record that this action just fired."""
        self.last_fired = time.time()


# ── Action executors ──────────────────────────────────────────────────────────

class ActionExecutor:
    """Executes actions of different types in a worker thread."""

    def __init__(self, max_workers: int = 4):
        self._q: queue.Queue = queue.Queue()
        self._workers: List[threading.Thread] = []
        self._running = False
        self._max_workers = max_workers

    def start(self) -> None:
        """Start the worker threads."""
        if self._running:
            return
        self._running = True
        for i in range(self._max_workers):
            t = threading.Thread(target=self._worker, daemon=True, name=f"AutomatorWorker-{i}")
            t.start()
            self._workers.append(t)

    def stop(self) -> None:
        """Stop the worker threads gracefully."""
        self._running = False
        for _ in self._workers:
            self._q.put(None)  # poison pill
        self._workers.clear()

    def submit(self, action: Action, payload: Dict[str, Any]) -> None:
        """Submit an action for async execution."""
        self._q.put((action, payload))

    def _worker(self) -> None:
        """Worker thread — pulls actions from queue and executes them."""
        while self._running:
            try:
                item = self._q.get(timeout=1.0)
                if item is None:
                    break
                action, payload = item
                self._execute(action, payload)
                self._q.task_done()
            except queue.Empty:
                continue

    def _execute(self, action: Action, payload: Dict[str, Any]) -> None:
        """Execute a single action with the given payload."""
        try:
            if action.action_type == ACTION_FUNCTION:
                self._exec_function(action, payload)
            elif action.action_type == ACTION_HTTP:
                self._exec_http(action, payload)
            elif action.action_type == ACTION_SHELL:
                self._exec_shell(action, payload)
            elif action.action_type == ACTION_PLATO:
                self._exec_plato(action, payload)
            else:
                print(f"[Automator] Unknown action type: {action.action_type}")
        except Exception as e:
            print(f"[Automator] Action failed: {e}")

    def _exec_function(self, action: Action, payload: Dict[str, Any]) -> None:
        """Call a Python function."""
        fn = action.target
        if callable(fn):
            fn(payload)

    def _exec_http(self, action: Action, payload: Dict[str, Any]) -> None:
        """Send an HTTP request."""
        url = action.target
        method = payload.get("_http_method", "POST")
        headers = payload.get("_http_headers", {"Content-Type": "application/json"})
        body = json.dumps(payload.get("_http_body", payload)).encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    def _exec_shell(self, action: Action, payload: Dict[str, Any]) -> None:
        """Run a shell command. Template variables from payload are substituted."""
        cmd = action.target
        # Simple template substitution: {{key}} → value
        for k, v in payload.items():
            cmd = cmd.replace(f"{{{{{k}}}}}", str(v))

        subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=30,
        )

    def _exec_plato(self, action: Action, payload: Dict[str, Any]) -> None:
        """Write a tile to a PLATO room."""
        import urllib.request

        Plato_URL = action.target.get("url", "https://plato.purplepincher.org")
        room = action.target.get("room", "scribe-default")
        question = payload.get("question", "automated tile")
        answer = payload.get("answer", json.dumps(payload))
        tags = payload.get("tags", ["automated", "automator"])

        data = {
            "room": room,
            "question": question[:200],
            "answer": answer[:2000],
            "tags": tags[:10],
        }
        req = urllib.request.Request(
            f"{Plato_URL}/tile",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                json.loads(resp.read())
        except Exception as e:
            print(f"[Automator] PLATO tile write failed: {e}")


# ── Automator ────────────────────────────────────────────────────────────────

@dataclass
class PatternAction:
    """A registered pattern-action pair."""

    pattern_sig: str  # Pattern signature or key
    action: Action


class Automator:
    """Watches deltas and fires registered actions when patterns match.

    The Automator is the "if this, then that" engine of the One Delta system.
    Register a pattern + action, and every time a delta matching that pattern
    is processed, the action fires (subject to throttling).

    Usage:
        automator = Automator()
        automator.on_delta(
            pattern="metrics.load",
            action=Action(ACTION_HTTP, "https://hook.example.com/alert"),
            throttle_seconds=60.0,
        )
        automator.watch(delta_result, state)

    Thread-safe for concurrent delta submissions from multiple sources.
    """

    def __init__(self, max_workers: int = 4):
        self._rules: Dict[str, PatternAction] = {}
        self._executor = ActionExecutor(max_workers=max_workers)
        self._executor.start()
        self._fire_count: Dict[str, int] = {}

    def on_delta(
        self,
        pattern: str,
        action_type: str,
        target: Any,
        throttle_seconds: float = 60.0,
    ) -> None:
        """Register an action to fire when a delta matching `pattern` is seen.

        Args:
            pattern: Pattern signature or key to match against.
                     Use "*" to match all deltas.
            action_type: One of "function", "http", "shell", "plato"
            target: The action target:
                - function: a callable that accepts a payload dict
                - http: URL string
                - shell: command string with {{variable}} templates
                - plato: dict with "url", "room" keys
            throttle_seconds: Minimum seconds between fires for this pattern.
                               Default 60.0 (1 minute).
        """
        action = Action(
            action_type=action_type,
            target=target,
            throttle_seconds=throttle_seconds,
        )
        self._rules[pattern] = PatternAction(pattern_sig=pattern, action=action)

    def watch(self, delta_result: Dict[str, Any], state: Dict[str, Any]) -> List[str]:
        """Process a delta result and fire any matching registered actions.

        Args:
            delta_result: Output from DeltaDetection.delta()
            state: The current state dict

        Returns:
            List of pattern signatures that fired (for observability)
        """
        fired = []
        delta_magnitude = delta_result.get("magnitude", 0.0)

        for sig, rule in self._rules.items():
            if rule.action.throttle_seconds > 0 and not rule.action.can_fire():
                continue

            should_fire = False
            if sig == "*":
                should_fire = delta_magnitude > 0
            elif sig in delta_result.get("changed", {}):
                should_fire = True
            elif sig in delta_result.get("added", {}):
                should_fire = True
            elif sig in delta_result.get("removed", {}):
                should_fire = True

            if should_fire:
                payload = self._build_payload(sig, delta_result, state)
                self._executor.submit(rule.action, payload)
                rule.action.mark_fired()
                self._fire_count[sig] = self._fire_count.get(sig, 0) + 1
                fired.append(sig)

        return fired

    def _build_payload(
        self,
        sig: str,
        delta_result: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build the payload dict passed to an action."""
        # Determine what changed for this signature
        changed = delta_result.get("changed", {}).get(sig, {})
        added = sig in delta_result.get("added", {})
        removed = sig in delta_result.get("removed", {})

        return {
            "pattern": sig,
            "delta_magnitude": delta_result.get("magnitude", 0.0),
            "changed": changed,
            "added": added,
            "removed": removed,
            "current_state": state.get(sig),
            "timestamp": time.time(),
        }

    def stop(self) -> None:
        """Stop the automator and its executor."""
        self._executor.stop()

    @property
    def stats(self) -> Dict[str, Any]:
        """Return automator statistics."""
        return {
            "rules_registered": len(self._rules),
            "fire_counts": dict(self._fire_count),
            "total_fires": sum(self._fire_count.values()),
        }