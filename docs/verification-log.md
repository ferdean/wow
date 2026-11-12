# Verification log

One line per ride check run, demonstration step and inspection (test plan, section 4). `tools/trace.py` reads the Item and Result columns: Item is an `RR-`, `D-` or `I-` ID, Result is `pass` or `fail`; the latest line of an item counts.

| Date | App version | Ride | Item | Result | Evidence | Note |
|------|-------------|------|------|--------|----------|------|
Ride 2026-11-12T162426Z
RR-01 pass: 1 connection(s) began 00, 07, then targets
RR-02 pass: 7 commands written, worst 0.8 ms, 0 replaced before writing, 1 equal to the command before
RR-03 pass: 6 steps, worst +1.0 ms
RR-04 pass: 5 target changes, worst +1.0 ms from one lead time (1.5 s) before the boundary; 0 boundaries without a change