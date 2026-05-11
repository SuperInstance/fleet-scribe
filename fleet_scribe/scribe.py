#!/usr/bin/env python3
"""The Scribe — download-and-try digital twin builder.
One command. Sits beside any app. Builds a PLATO twin."""
import json, time, urllib.request, sys, hashlib, os, math

PLATO = os.environ.get("PLATO_URL", "http://localhost:8847")
VERSION = "0.1.0"

class Scribe:
    def __init__(self, app_name="my_app", port=None):
        self.app = app_name
        self.port = port
        self.room = f"scribe-{app_name}"
        self.state = {}
        self.simulation = {}
        self.divergences = 0
        self.optimizations = 0
        self.tiles = 0
        self.llm_calls_saved = 0
    
    def observe(self):
        """Observe the app state. For now: simulate observation."""
        return {
            "timestamp": time.time(),
            "app": self.app,
            "tiles": self.tiles,
            "divergences": self.divergences,
            "optimizations": self.optimizations,
        }
    
    def tile_to_plato(self, domain, question, answer):
        """Submit a tile to PLATO."""
        tile = {
            "domain": domain,
            "question": question,
            "answer": answer,
            "source": f"scribe-{self.app}",
            "confidence": 0.9,
        }
        try:
            data = json.dumps(tile).encode()
            req = urllib.request.Request(f"{PLATO}/submit", data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
            if resp.get("status") == "accepted":
                self.tiles += 1
            return resp
        except Exception as e:
            return {"error": str(e)}
    
    def snap_gradient(self, actual, predicted):
        """Compute snapped gradient between observation and simulation."""
        numeric_keys = [k for k in set(list(actual.keys()) + list(predicted.keys())) 
                       if isinstance(actual.get(k), (int, float)) and isinstance(predicted.get(k), (int, float))]
        diff = sum(abs(actual.get(k, 0) - predicted.get(k, 0)) for k in numeric_keys)
        return math.tanh(diff)  # Normalize to [0, 1]
    
    def run_cycle(self):
        """One perception-action cycle of the Scribe."""
        actual = self.observe()
        
        if not self.simulation:
            # First cycle: mirror state to PLATO
            self.tile_to_plato(
                self.room,
                f"Scribe initialized for {self.app}",
                f"Digital twin builder started for application: {self.app}. "
                f"Observing state and building PLATO representation."
            )
            self.simulation = actual
            return {"status": "initialized", "tiles": self.tiles}
        
        gradient = self.snap_gradient(actual, self.simulation)
        
        if gradient > 0.1:
            # Divergence detected — perception triggered
            self.divergences += 1
            self.tile_to_plato(
                self.room,
                f"Divergence detected: gradient={gradient:.3f}",
                f"App state diverged from simulation by {gradient:.3f}. "
                f"Actual: {json.dumps(actual)[:100]}. "
                f"Predicted: {json.dumps(self.simulation)[:100]}."
            )
            # Update simulation
            self.simulation = actual
            return {"status": "divergence", "gradient": gradient}
        else:
            # No divergence — intelligence sleeping
            self.llm_calls_saved += 1
            return {"status": "stable", "gradient": gradient}
    
    def summary(self):
        return {
            "app": self.app,
            "tiles": self.tiles,
            "divergences": self.divergences,
            "optimizations": self.optimizations,
            "llm_calls_saved": self.llm_calls_saved,
        }

def cli():
    import argparse
    parser = argparse.ArgumentParser(description="The Scribe — download-and-try digital twin builder")
    parser.add_argument("--app", default="my_app", help="Application name")
    parser.add_argument("--port", type=int, help="Application port (optional)")
    parser.add_argument("--cycles", type=int, default=3, help="Number of cycles to run")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between cycles")
    args = parser.parse_args()
    
    print(f"📝 The Scribe v{VERSION}")
    print(f"   App: {args.app}")
    print(f"   PLATO: {PLATO}")
    print(f"   Cycles: {args.cycles}")
    print()
    
    scribe = Scribe(app_name=args.app, port=args.port)
    
    for i in range(args.cycles):
        result = scribe.run_cycle()
        status_icon = {"initialized": "🔄", "divergence": "⚡", "stable": "✅"}
        print(f"  Cycle {i+1}: {status_icon.get(result['status'], '❓')} {result['status']}")
        time.sleep(args.interval)
    
    s = scribe.summary()
    print()
    print(f"=== Summary ===")
    print(f"  Tiles submitted: {s['tiles']}")
    print(f"  Divergences: {s['divergences']}")
    print(f"  Optimizations: {s['optimizations']}")
    print(f"  LLM calls saved: {s['llm_calls_saved']}")
    
    main_summary = scribe.summary()
    
    # Final tile
    scribe.tile_to_plato(
        f"scribe-{args.app}",
        f"Scribe session complete — {main_summary['tiles']} tiles, {main_summary['divergences']} divergences",
        f"Scribe ran {args.cycles} cycles for {args.app}. "
        f"Submitted {main_summary['tiles']} tiles to PLATO room scribe-{args.app}. "
        f"Detected {main_summary['divergences']} divergences. "
        f"Saved {main_summary['llm_calls_saved']} LLM calls by running on snapped gradients."
    )

if __name__ == "__main__":
    cli()
