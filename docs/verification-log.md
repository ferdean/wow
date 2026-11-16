# Verification log

One line per ride check run, demonstration step and inspection (test plan, section 4). `tools/trace.py` reads the Item and Result columns: Item is an `RR-`, `D-` or `I-` ID, Result is `pass` or `fail`; the latest line of an item counts.

| Date | App version | Ride | Item | Result | Evidence | Note |
|------|-------------|------|------|--------|----------|------|
| 2026-11-12 | 0.2.0 | 2026-11-12T162426Z | RR-01 | pass | `check_ride.py` | 1 connection began 00, 07, then targets |
| 2026-11-12 | 0.2.0 | 2026-11-12T162426Z | RR-02 | pass | `check_ride.py` | 7 commands written, worst 0.8 ms; 0 replaced before writing; 1 equal to the one before |
| 2026-11-12 | 0.2.0 | 2026-11-12T162426Z | RR-03 | pass | `check_ride.py` | 6 steps, worst +1.0 ms |
| 2026-11-12 | 0.2.0 | 2026-11-12T162426Z | RR-04 | pass | `check_ride.py` | 5 target changes, worst +1.0 ms from one lead time (1.5 s) before the boundary; 0 boundaries without a change |
| 2026-11-13 | 0.2.0 | - | T-SYS-01 | pass | `pytest -m "pi and slow" tests/system`, 60 min | RR-02 pass: 121 commands written, worst 2.8 ms; loop lag worst 40.4 ms || 2026-11-13 | 0.3.0 | — | S-FIT-01 | pass | `pytest -m "pi and slow" tests/adapters/test_fit.py` | 14400 records encoded in 0.5 s on the Pi |
| 2026-11-13 | 0.3.0 | — | T-REC-03 | pass | `pytest -m "pi and slow" tests/system/test_kill.py` | 20 kills in 387 s; every sample older than 5 s on disk |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-01 | fail | `check_ride.py` | `00 07 00`: an earlier run's writes with the same generation mixed in (SF-12); to run again with the fixed check |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-02 | pass | `check_ride.py` | 61 commands written, worst 0.9 ms; 461 replaced before writing, 382 equal to the one before (ramp updates every second) |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-03 | pass | `check_ride.py` | 5 steps, worst +1.0 ms |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-04 | pass | `check_ride.py` | 4 target changes, worst +0.9 ms from one lead time (1.5 s, Ferran's `settings.json`) before the boundary |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-05 | pass | `check_ride.py` | 6313 samples, none without power or heart rate |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-12 | pass | `check_ride.py` | files written 0.29 s after finished |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-13 | pass | `check_ride.py` | 0.3.0 in meta.json, journal, FIT |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | RR-14 | pass | `check_ride.py` | 6313 records, 6 laps, 0 pauses |
| 2026-11-13 | 0.3.0 | 2026-11-13T170154Z | D-13 | pass | screenshot 19:47, journal | trainer to its lowest level (`04 00`) at the end; Summary with every metric and the upload state 0.3 s after Finish |
| 2026-11-14 | 0.3.0 | 2026-11-13T170154Z | RR-01 | pass | `check_ride.py` after IM-66 | 1 connection began 00, 07, then targets |
