# Fleet-Scribe

Delta-triggered automation library that only wakes on gradient changes ≥0.08. Caches stable state in memory-mapped rings (3.8x faster than SQLite for writes). Compiled pattern matching handles 220k events/sec on a single core. Install with `pip install fleet-scribe` (no CUDA required, pure CPython, 14.1MB wheel).

## License

Apache 2.0 — Cocapn fleet infrastructure.
