# WitchesOnWheels

Runs structured workouts on the Van Rysel D100 from a Raspberry Pi 5; the iPhone shows the ride. Requirements, architecture, interfaces and the test plan are the phase documents in `docs/`.

**State:** Phase 5, slice SL-02 (first ride on screen). SL-01 gave the Bluetooth foundation; SL-02 adds the workout plan in watts and percent of FTP, the target policy with the lead time, the ride state machine (armed, steps, workout done, finish, cancel), the view state, the ride controller, the journal and Bluetooth log of each ride, the HTTPS site with the display WebSocket, `wow` itself, and the display with Home, Pre-ride and the ERG ride screen. Two built-in workouts: "ERG check" (6 min) and "30/30 and a surge" (19 min). Recording to FIT, the Summary and intervals.icu follow in SL-03 and SL-04.

## Set-up

Python 3.13 and uv, on the laptop or the Pi:

```
uv sync --frozen
```

The display is built on the laptop (Node.js 22.12 or later; the Pi has no Node.js):

```
cd display
npm ci
npm run build        # writes src/wow/web/static/
```

## Run

```
cp deploy/wow.example.toml wow.toml                 # set the three TLS paths
mkdir -p wow-data && cp deploy/settings.example.json wow-data/settings.json
uv run wow --config wow.toml                         # real D100 and HRM 200
uv run wow --config wow.toml --sim                   # simulated devices
```

Open `https://wow.local:8443` in Safari. `http://wow.local:8080/setup/root.crt` serves the root certificate; any other plain-HTTP path redirects to HTTPS. In `--sim` the simulated rider starts pedaling 3 s after the first target arrives, so the ride starts by itself.

For the display alone on the laptop: `npm run dev` in `display/`, with `wow --sim` running; Vite proxies `/ws` to `https://localhost:8443` (set `WOW_PI` for another address).

## Gate

```
uv run python tools/gate.py --through SL-02
```

Runs pytest without the `slow` and `pi` tests (flake8, strict mypy, the display's svelte-check, ESLint and tsc, the import check, and `uv sync --frozen` and `npm ci` from clean copies run inside it as T-TOOL-01 to T-TOOL-04), checks the coverage floors of the test plan (2.5), runs Vitest, then `tools/trace.py`, which writes `docs/traceability.md` and prints the slice's traceability note. It needs the approved test plan at `docs/phase4-test-plan.md` and `npm ci` done in `display/`.

Tests marked `pi` run on the Pi and show as "due on the Pi" until `docs/verification-log.md` has a line with their result:

```
uv run pytest -m "pi and slow" -s tests/system            # T-SYS-01, 60 min
WOW_SYS_MINUTES=5 uv run pytest -m "pi and slow" -s tests/system   # a shorter look
```

SL-01 finishes when the Phase 2 S1 and S2 logs are in `testdata/ble/` (see `testdata/README.md`):

```
uv run python tools/import_spike_log.py <path>/contact-20261104T214602Z.jsonl testdata/ble/phase2-s1-contact.jsonl
uv run python tools/import_spike_log.py <path>/<S2 steps log>.jsonl testdata/ble/phase2-s2-steps.jsonl
```

## Ride checks

After every real ride (test plan, section 6):

```
uv run python tools/check_ride.py wow-data/rides/<ride id>
```

It prints RR-01 to RR-04 as pass, fail with the worst value, or not applicable; copy the lines into `docs/verification-log.md`. It reads the ride's `events.jsonl` and `ble.jsonl`, and `logs/ble-system.jsonl` for the connection made before the ride.

## Probe on the real devices

On the Pi, with the trainer awake and the strap on (close Onelap and nRF Connect first):

```
uv run wow-probe --trainer 94:05:BB:03:5D:9D --hrm E0:E2:EF:63:14:BC --watts 150 --seconds 60
```

It connects both, takes control, holds 150 W, prints one line a second, sets the lowest resistance level, releases the trainer and writes `probe-<UTC>.jsonl` in the Bluetooth log format (IF-11). `--simulate` runs the same against the simulator; `--adapter` picks the Bluetooth adapter (default `hci0`).

## Layout

```
src/wow/core/       pure logic: codecs, FTMS session, workout, plan, target policy, ride, view (no I/O, no clock)
src/wow/ports/      interfaces: GattConnector and GattClient, Clock, Trainer and HeartRateMonitor
src/wow/app/        asyncio shell: main, console, ride controller, recorder, device manager, FtmsTrainer, HrmLink
src/wow/web/        HTTPS and HTTP sites, display WebSocket hub; static/ is the built display
src/wow/adapters/   bleak and BlueZ, the simulator (ble_sim), the logging connector, the clocks
src/wow/builtin/    built-in workouts (ICD IF-13)
display/            Svelte 5 display: link, screens, ui, device, IF-06 types
deploy/             example wow.toml and settings.json
tests/              pytest: core (L1, L2), app on the stepped clock (L3), web (L5), system (L6), tools
testdata/           language-neutral fixtures (README inside)
tools/              gate.py, trace.py, check_ride.py, import_spike_log.py
docs/               phase documents, verification log, generated traceability
```
