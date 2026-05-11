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
    
    # Three perception triggers
    TIMERS = {}  # name -> {"ttl": seconds, "expires_at": time, "fired": bool}
    DEADBANDS = {}  # name -> {"min": float, "max": float}
    
    def set_timer(self, name, ttl):
        """Set a T-minus timer. If it expires without the event, perception triggers."""
        self.TIMERS[name] = {"ttl": ttl, "expires_at": time.time() + ttl, "fired": False}
    
    def fire_event(self, name):
        """Mark a timed event as fired."""
        if name in self.TIMERS:
            self.TIMERS[name]["fired"] = True
    
    def set_deadband(self, name, min_val=0, max_val=1):
        """Set a deadband for a sensor/reading."""
        self.DEADBANDS[name] = {"min": min_val, "max": max_val}
    
    def check_triggers(self, actual):
        """Check all three perception triggers."""
        triggers = []
        
        # 1. Reading outside simulation bounds
        for k, v in actual.items():
            if isinstance(v, (int, float)) and k in self.simulation:
                expected = self.simulation.get(k, v)
                deadband = self.DEADBANDS.get(k, {}).get("max", 0.1)
                if abs(v - expected) > deadband:
                    triggers.append(("out_of_bounds", k, v, expected))
        
        # 2. T-minus expired without event
        now = time.time()
        for name, timer in list(self.TIMERS.items()):
            if now > timer["expires_at"] and not timer["fired"]:
                triggers.append(("expected_event_missed", name))
                del self.TIMERS[name]
        
        # 3. Unexpected event through deadband
        for k, v in actual.items():
            if isinstance(v, (int, float)) and k in self.DEADBANDS:
                db = self.DEADBANDS[k]
                if v < db["min"] or v > db["max"]:
                    triggers.append(("deadband_violation", k, v, db))
        
        return triggers
    
    def run_cycle(self):
        """One perception-action cycle. Intelligence sleeps until a trigger fires."""
        actual = self.observe()
        
        if not self.simulation:
            self.tile_to_plato(self.room, f"Scribe initialized for {self.app}",
                f"Digital twin builder started for {self.app}.")
            self.simulation = actual
            return {"status": "initialized"}
        
        triggers = self.check_triggers(actual)
        
        if triggers:
            self.divergences += len(triggers)
            for t in triggers:
                self.tile_to_plato(self.room, f"Trigger: {t[0]}", f"Triggered: {json.dumps(t)[:200]}")
            self.simulation = actual
            return {"status": "perception", "triggers": triggers}
        else:
            self.llm_calls_saved += 1
            return {"status": "sleeping"}
    
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
        status_icon = {"initialized": "🔄", "perception": "⚡", "sleeping": "💤"}
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
