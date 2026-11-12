# Test data

Language-neutral inputs and expected outputs (APP-821, D-17): JSON and JSON Lines only, so a JavaScript v2 can run the same cases. Units follow the ICD (AD-20): no suffix for SI values (s, W), a suffix otherwise (`_kmh`, `_rpm`, `_bpm`, `_pct`, `_raw`, `_ms`). Bytes are lower-case hex text.

## `ftms/` and `hr/`: codec cases (L1)

| File | Content |
|------|---------|
| `ftms/indoor_bike_data.json` | Indoor Bike Data records (`hex`), the Resistance Level field width the range layout implies (`resistance_width`: 2 for the 6-byte FTMS 1.0 layout, 1 for the 3-byte layout), and the decoded values (`expect`) or `"drop": true`. `joins` lists records split with More Data and the joined result. |
| `ftms/machine.json` | Fitness Machine Feature, the range characteristics, the capabilities derived from them, encoded commands, control point responses and statuses. |
| `hr/heart_rate.json` | Heart Rate Measurement and Battery Level. |

Each entry names the catalogue test it belongs to (`case`). The values come from the ICD (4.1.3, 4.1.4, 4.2.2) and the Phase 2 findings named in each entry; records that exist only to place a field at its offset were written by hand.

## `timelines/`: state-machine cases (L2)

One pair per case: `<case>-<name>.events.json` (in) and `<case>-<name>.actions.json` (expected out). Events and actions are the JSON forms of the core's dataclasses: an object with `type` (the class name in snake case) and one field per attribute; bytes as hex.

```json
{"case": "T-SES-05", "machine": "ftms_session", "title": "...", "until": 20.0,
 "events": [{"at": 10.0, "event": {"type": "set_command", "command": {"type": "erg", "power": 330}}}]}
```

- `at` is the machine's `now`: seconds on the monotonic clock (ICD IF-04).
- An entry with `"every": e, "count": n` stands for `n` entries at `at`, `at + e`, … (used for long runs such as 10 minutes of refused control).
- **Harness rule:** events go in at their times; whenever the machine's `next_deadline()` comes before the next event (and not after `until`), a `{"type": "tick"}` goes in at that deadline. An event and a deadline at the same instant: the event first. Entries with equal times keep their order in the file.
- The expected file lists every action with the `now` of the call that returned it, in order. Times are compared rounded to 1 µs.

`timelines/ftms_session/` holds the trainer-session cases T-SES-01 to T-SES-10 and the supporting edge cases S-SES-01. `timelines/ride/` holds the ride cases T-RID-01 to T-RID-06 and the supporting cases S-RID-01; their workouts are in the events file as JSON forms of `Workout`.

## `workouts/`: workout documents (L1)

`<name>.workout_doc.json`: a `workout_doc` as intervals.icu sends it, with the expected steps in watts at each FTP the case names. `plain-steps` is hand-written for T-WKO-01 (watts and percent of FTP only); the recorded S6 files join in SL-04, when the parser reads ranges, zones, ramps and free ride.

## `display/`: golden views (L1; S-DSP-01)

`<state>.view.json`: the complete `view` message (ICD IF-06) for one state of test plan 3.1, written by `tests/core/test_view.py` from the scripted scenes of `tests/support/scenes.py` and compared on every run. After an intended change, rewrite them with `WOW_UPDATE_GOLDEN=1 uv run pytest tests/core/test_view.py` and review the difference. Vitest renders every file (S-DSP-01). SL-02 has Home, Pre-ride (trainer connected and missing) and the ride screen (waiting for power, ERG, last 5 s, target limited, strap missing, workout done).

## `ble/`: Bluetooth logs (L4, and the log parts of T-COD-01 and T-SIM-01)

Files in the format of ICD IF-11. The Phase 2 spike logs use an earlier field set; convert each once:

```
uv run python tools/import_spike_log.py <spike log> testdata/ble/<name>.jsonl
```

| Name | From | Used by |
|------|------|---------|
| `phase2-s1-contact.jsonl` | `contact-20261104T214602Z.jsonl` (S1, 4 Nov) | T-COD-01 (all 1076 records decode), T-SIM-01 |
| `phase2-s2-steps.jsonl` | the `steps` log of 6 Nov (S2) | T-SIM-01 |
| `phase2-s3-spindown.jsonl` | `spindown-20261106T210145Z.jsonl` (S3 retest) | T-LOG-04 (SL-06) |
| `phase2-s5-ride.jsonl` | `ride-20261110T174048Z.jsonl` (S5) | T-LOG-04, T-MET-07 (later slices) |

The importer maps the spike's `rx` to `notify` (or `indicate` on the control point), `tx` to `write`, `read` to `read`, and the events `connected` and `disconnected` to link lines; it prints what it leaves out. Addresses default to the D100 and the HRM 200 (`--trainer`, `--hrm`). Until the S1 and S2 files exist, the two log-based tests are skipped, and `tools/trace.py` reports SL-01 as not finished.

## `tls/`: test certificates (L5)

A test-only root (`root.crt`) and a server certificate for `wow.local`, `localhost` and `127.0.0.1` signed by it (`server.crt`, `server.key`, P-256, valid to 2036), made with OpenSSL on 12 Nov 2026 with the extensions Python's strict verification wants (basic constraints, key usage, subject and authority key identifiers). The root's key was deleted after signing, so these files can't sign anything else. They are not the Pi's certificates: those come from Phase 2's `spike_certs.py` and stay out of the repository.
