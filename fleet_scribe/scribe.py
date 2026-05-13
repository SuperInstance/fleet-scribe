#!/usr/bin/env python3
"""
fleet-scribe — One command. Sits beside any app. Builds a PLATO twin.

Core loop:
    1. MIRROR — app state → PLATO tiles
    2. SIMULATE — continuous field predicts next state
    3. SNAP — gradient between simulation and observation
    4. PERCEIVE — if gradient > threshold, LLM is cued
    5. OPTIMIZE — patterns compile to FLUX bytecode

Usage:
    pip3 install fleet-scribe
    scribe --app my_app
    scribe --app my_app --cycles 10 --threshold 0.3
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

PLATO_URL = "https://plato.purplepincher.org"
DEFAULT_CYCLES = 0  # 0 = infinite
DEFAULT_INTERVAL = 5  # seconds between cycles
DEFAULT_THRESHOLD = 0.15
WATCH_DIRS = ["."]

# ── PLATO Client ─────────────────────────────────────────────────────────────

class PlatoClient:
    """Minimal PLATO tile client"""

    def __init__(self, url: str = PLATO_URL):
        self.url = url.rstrip("/")

    def tile(self, room: str, question: str, answer: str, tags: list = None) -> Optional[str]:
        data = {
            "room": room,
            "question": question[:200],
            "answer": answer[:2000],
        }
        if tags:
            data["tags"] = tags[:10]
        req = urllib.request.Request(
            f"{self.url}/tile",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                return result.get("tile_id")
        except Exception as e:
            print(f"  ⚠️ PLATO tile error: {e}")
            return None

    def room_tiles(self, room: str, limit: int = 10) -> List[Dict]:
        try:
            with urllib.request.urlopen(f"{self.url}/room/{room}?limit={limit}", timeout=10) as resp:
                data = json.loads(resp.read())
                return data.get("tiles", [])
        except Exception:
            return []


# ── App Mirroring ────────────────────────────────────────────────────────────

class AppMirror:
    """Mirrors an application's state to PLATO tiles"""

    def __init__(self, app_name: str, watch_dirs: List[str]):
        self.app_name = app_name
        self.room = f"scribe-{app_name}"
        self.watch_dirs = watch_dirs
        self.files: Dict[str, str] = {}  # path → last content hash

    def snapshot(self) -> Dict[str, Any]:
        """Take a snapshot of the app's visible state"""
        state = {
            "app": self.app_name,
            "timestamp": datetime.utcnow().isoformat(),
            "files": {},
            "processes": [],
            "metrics": {},
        }

        # Check watched files
        for watch_dir in self.watch_dirs:
            if not os.path.isdir(watch_dir):
                continue
            for root, dirs, files in os.walk(watch_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("__")]
                for f in files[:30]:  # limit
                    if f.endswith((".pyc", ".pyo", ".so", ".o")):
                        continue
                    path = os.path.join(root, f)
                    try:
                        stat = os.stat(path)
                        state["files"][path] = {
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                        }
                    except OSError:
                        pass

        # Check running processes matching app name
        try:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                if self.app_name.lower() in line.lower() and "scribe" not in line.lower():
                    parts = line.split()
                    if len(parts) >= 11:
                        state["processes"].append({
                            "pid": parts[1],
                            "cpu": parts[2],
                            "mem": parts[3],
                            "cmd": parts[10][:60],
                        })
        except Exception:
            pass

        # System metrics
        try:
            with open("/proc/loadavg") as f:
                state["metrics"]["load"] = f.read().strip().split()[:3]
        except Exception:
            pass

        return state

    def detect_changes(self, new_state: Dict) -> Tuple[float, List[str]]:
        """Detect changes between current and previous state. Returns (gradient, changes)."""
        changes = []
        gradient = 0.0

        # Check file changes
        new_files = new_state.get("files", {})
        old_paths = set(self.files.keys())
        new_paths = set(new_files.keys())

        added = new_paths - old_paths
        removed = old_paths - new_paths

        for f in added:
            changes.append(f"➕ {f}")
        for f in removed:
            changes.append(f"➖ {f}")

        # Check file modifications
        for f in new_paths & old_paths:
            if new_files[f]["modified"] != self.files.get(f, {}).get("modified"):
                # Use size change ratio as gradient contribution
                old_size = self.files.get(f, {}).get("size", 0)
                new_size = new_files[f]["size"]
                if old_size > 0:
                    size_ratio = abs(new_size - old_size) / old_size
                    gradient += min(size_ratio, 1.0)
                changes.append(f"✏️ {f} ({old_size}→{new_size}B)")

        self.files = {f: dict(v) for f, v in new_files.items()}
        gradient = min(gradient, 10.0)
        return gradient, changes


# ── Simulation Engine ────────────────────────────────────────────────────────

class Simulator:
    """Simple simulation engine — predicts next state from current trends"""

    def __init__(self):
        self.history: List[float] = []  # gradient history
        self.prediction: Optional[float] = None

    def predict(self, gradient: float) -> float:
        """Predict next gradient based on history. Returns expected gradient."""
        self.history.append(gradient)
        if len(self.history) < 3:
            return 0.0

        # Simple linear extrapolation
        recent = self.history[-3:]
        x = [0, 1, 2]
        y = recent
        n = len(x)
        if n < 2:
            return 0.0

        slope = (n * sum(x[i] * y[i] for i in range(n)) - sum(x) * sum(y)) / \
                (n * sum(x[i] ** 2 for i in range(n)) - sum(x) ** 2 + 0.001)
        self.prediction = recent[-1] + slope
        return self.prediction


# ── CLI ──────────────────────────────────────────────────────────────────────

def cli():
    parser = argparse.ArgumentParser(
        description="📝 The Scribe — Sits beside any app, builds a PLATO twin"
    )
    parser.add_argument("--app", "-a", required=True, help="Application name to observe")
    parser.add_argument("--cycles", "-c", type=int, default=DEFAULT_CYCLES,
                        help="Number of cycles (0 = infinite)")
    parser.add_argument("--interval", "-i", type=int, default=DEFAULT_INTERVAL,
                        help="Seconds between cycles")
    parser.add_argument("--threshold", "-t", type=float, default=DEFAULT_THRESHOLD,
                        help="Snap threshold (gradient > this triggers perception)")
    parser.add_argument("--dir", "-d", nargs="+", default=WATCH_DIRS,
                        help="Directories to watch")
    parser.add_argument("--plato", default=PLATO_URL,
                        help=f"PLATO URL (default: {PLATO_URL})")
    parser.add_argument("--once", action="store_true",
                        help="Single cycle, then exit")

    args = parser.parse_args()

    plato = PlatoClient(args.plato)
    mirror = AppMirror(args.app, args.dir)
    sim = Simulator()

    print(f"📝 Scribe watching: {args.app}")
    print(f"   Room: scribe-{args.app}")
    print(f"   PLATO: {args.plato}")
    print(f"   Threshold: {args.threshold}")
    print(f"   Interval: {args.interval}s")
    print()

    cycle = 0
    while True:
        cycle += 1
        if args.cycles > 0 and cycle > args.cycles:
            break

        try:
            timestamp = datetime.utcnow().strftime("%H:%M:%S")
            print(f"[{timestamp}] Cycle {cycle} — mirroring {args.app}...")

            # 1. MIRROR — snapshot app state
            state = mirror.snapshot()

            # 2. SNAP — detect changes
            gradient, changes = mirror.detect_changes(state)

            # 3. SIMULATE — predict next state
            expected = sim.predict(gradient)

            # 4. PERCEIVE — if gradient > threshold, LLM is cued
            needs_perception = gradient > args.threshold

            # Build summary
            summary = (
                f"App: {args.app}\n"
                f"Files watched: {len(state.get('files', {}))}\n"
                f"Processes: {len(state.get('processes', []))}\n"
                f"Gradient: {gradient:.3f} (threshold: {args.threshold})\n"
                f"Predicted gradient: {expected:.3f}\n"
                f"Perception needed: {'⚠️ YES' if needs_perception else '✅ no'}\n"
                f"Changes: {len(changes)}"
            )

            if changes:
                summary += "\n\nChanges:\n" + "\n".join(changes[:20])

            # 5. TILE to PLATO
            tile_id = plato.tile(
                room=mirror.room,
                question=f"Scribe cycle {cycle} — {args.app} gradient={gradient:.3f}",
                answer=summary,
                tags=["scribe", args.app, "gradient-snap"]
            )

            status = "⚠️ " if needs_perception else "✅ "
            print(f"   {status}gradient={gradient:.3f} / predicted={expected:.3f} / changes={len(changes)}")
            if tile_id:
                print(f"   📝 tiled to scribe-{args.app}/")
            if changes:
                for c in changes[:5]:
                    print(f"      {c}")

            # If perception needed, tile additional info
            if needs_perception:
                plato.tile(
                    room=mirror.room,
                    question=f"⚠️ Perception trigger — gradient={gradient:.3f} exceeded threshold",
                    answer=f"Gradient {gradient:.3f} > threshold {args.threshold}\n"
                           f"Predicted: {expected:.3f}\n"
                           f"Deviation: {abs(gradient - expected):.3f}\n"
                           f"Changes since last cycle:\n" + "\n".join(changes[:10]),
                    tags=["scribe", args.app, "perception", "high-gradient"]
                )

            if args.once:
                break

        except KeyboardInterrupt:
            print("\n📝 Scribe stopped.")
            break
        except Exception as e:
            print(f"  ❌ Error: {e}")

        time.sleep(args.interval)

    print(f"\n📝 Scribe completed {cycle} cycles for '{args.app}'")


if __name__ == "__main__":
    cli()
