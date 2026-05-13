# Fleet Scribe

Your AI just re-read every file in your project. All 40,000 tokens. Again. For the third time today. Nothing changed. It cost you money and time to learn what you already knew.

This is the problem fleet-scribe fixes.

Most AI systems reprocess everything every time. Expensive. Slow. Wasteful. fleet-scribe implements the **One Delta principle**: only perceive when the gradient changes. If the data hasn't moved, don't think about it. Cache the stable parts. Compile the predictable. Automate the routine. Spend compute only on what's actually different from a moment ago.

## How It Works

```python
from scribe import Scribe

scribe = Scribe()
deltas = scribe.watch(current_state)
# Returns only what changed since last check
```

Like a motion sensor for computation. The ship's log that only writes when something happens.

## Modules

| Module | What it does |
|--------|-------------|
| `core.py` | Delta detection: compare current state to cached baseline, report only changes above threshold |
| `cache.py` | Persistent cache: store baselines on disk, auto-prune stale entries, track hit/miss stats |
| `compile.py` | Pattern detection: find stable patterns in history (constants, cycles, trends), compile them to optimized rules |
| `automate.py` | Action automation: trigger actions when deltas match registered patterns, with throttling |

## Quick Start

```bash
pip install fleet-scribe
```

```python
from scribe import Scribe

scribe = Scribe()
last_state = {}

while True:
    current = collect_sensors()
    deltas = scribe.watch(current, baseline=last_state)
    if deltas:
        respond_to_changes(deltas)
    last_state = current
    time.sleep(10)
```

## License

Apache 2.0 — Cocapn fleet infrastructure.
