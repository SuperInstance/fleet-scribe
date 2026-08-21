# Fleet Scribe

Python library implementing the **One Delta** principle: only perceive when the
gradient changes. Cache everything, detect only what changes, compile stable
patterns once, and automate the predictable responses.

## Status

| Feature | Status |
| --- | --- |
| Delta detection with configurable threshold (`DeltaDetection`) | **stable** |
| Persistent file cache (`FileCache`) | **stable** |
| Pattern detection + compilation (`compile`) | **stable** |
| Action automation (`Automator`) | **stable** |
| `Scribe` unified facade | **stable** |
| `scribe` CLI (app mirror → PLATO tiles) | **experimental** — depends on an external PLATO HTTP endpoint |

> **Unverified claims from earlier marketing copy.** Previous versions of this
> README advertised "3.8x faster than SQLite for writes" and "220k events/sec
> on single core". **No benchmark or SQLite comparison exists in this repo** to
> support either number, and the implementation is JSON-per-entry file I/O plus
> pure-Python pattern detection, so those figures should not be relied on. They
> are retained here only to flag that they are unsubstantiated; please re-measure
> before quoting them.

## Install

From source (the package is not published to PyPI):

```bash
git clone <this repo>
cd fleet-scribe
pip install .
```

Runtime dependency: [`numpy`](https://numpy.org/) (used by `core.DeltaDetection`
for array diffs). There is **no** `plato-sdk` dependency — all PLATO integration
talks to the HTTP endpoint directly via `urllib`.

## Quick start

```python
from fleet_scribe import Scribe

scribe = Scribe(cache_dir="/tmp/scribe_cache")
scribe.watch(current_state)        # first call establishes the baseline
deltas = scribe.watch(new_state)   # subsequent calls return only what changed
rules = scribe.compile_all(history)
```

## Modules

- `core.DeltaDetection` — compare state to a baseline, return only the deltas
  (dict / array / text). Configurable threshold filters noise.
- `cache.FileCache` — persistent JSON-backed cache with TTL pruning and hit/miss
  stats.
- `compile` — detect constant / cyclic / trending patterns in history and
  compile them into fast check functions.
- `automate.Automator` — fire registered actions (function / HTTP / shell /
  PLATO tile) when deltas match, with per-pattern throttling.

## License

MIT — see [LICENSE](LICENSE).
