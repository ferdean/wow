# WitchesOnWheels

Runs structured workouts on the Van Rysel D100 from a Raspberry Pi 5; the iPhone shows the ride. Requirements, architecture, interfaces and the test plan are the phase documents in `docs/`.

**State:** Phase 5, slices SL-01 to SL-09 built: Bluetooth foundation, rides with recording and FIT, workouts from intervals.icu, ride controls, dropouts and reconnect, crash recovery and the systemd service, uploads and past rides, and the spin-down calibration. The phase documents in `docs/` have the details.

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

FTP, zones, lead time, the battery warning, upload, the intervals.icu account and the trainer and strap are set on the Settings screen (from Home); `settings.json` and `secrets.json` don't need editing by hand. The devices are released 10 minutes after the last ride, Pre-ride or calibration, so Onelap can connect without stopping wow.

For the display alone on the laptop: `npm run dev` in `display/`, with `wow --sim` running; Vite proxies `/ws` to `https://localhost:8443` (set `WOW_PI` for another address).

## Install on the Pi as a service

On the Pi, from the repository, after `uv sync --frozen` and with the built display in `src/wow/web/static/`:

```
sudo deploy/install.sh
```

It builds the wheel, installs it with the locked dependencies into `/opt/wow/venv`, creates the user `wow` and `/var/lib/wow`, copies `deploy/wow.pi.toml` to `/etc/wow/wow.toml` the first time, and (re)starts `wow.service` (ports 443 and 80, so the page is `https://wow.local`). Put `settings.json`, `secrets.json` (mode 600) and the TLS files under `/var/lib/wow` (TLS in `tls/`), owned by `wow`. Logs: `journalctl -u wow -f`.

## Start, stop and switch modes

### On the Pi (the service)

`wow.service` starts at boot and comes back 2 s after a crash. Control it only through systemd:

```
systemctl status wow                 # running? since when?
journalctl -u wow -f                 # follow the log
sudo systemctl stop wow              # stays stopped until start or the next boot
sudo systemctl start wow
sudo systemctl restart wow           # after any change to /etc/wow/wow.toml
sudo systemctl disable --now wow     # stop, and don't start at boot
sudo systemctl enable --now wow      # start, and start at boot again
```

`stop` and `restart` send SIGTERM, and wow shuts down in order. It sets the trainer to its lowest level, releases the trainer and the strap, closes the ride files and logs `wow stopped; worst event-loop lag …`. systemd waits up to 20 s for this.

Stop between rides. If wow stops during a ride, the ride stays open, and at the next start Home offers Continue or Finish.

Don't use `kill -9` or `systemctl kill --signal=KILL wow` except to test crash recovery (D-18): the trainer is then neither set to its lowest level nor released.

Switch between the simulator and the real trainer and strap:

```
sudo sed -i 's/^simulate = .*/simulate = true/' /etc/wow/wow.toml   # false: real devices
sudo systemctl restart wow
journalctl -u wow -n 50 | grep started   # "... started with simulated devices" in simulation
```

Before simulating, turn **Upload** off on the Settings screen, and turn it back on afterwards. Otherwise a ride finished on the simulator is uploaded to intervals.icu like a real one. Simulated rides also show up in Past rides, where you can delete them.

`wow-probe` and `uv run wow` from a checkout on the Pi need the same devices (and `uv run wow` the same ports), so stop the service first:

```
sudo systemctl stop wow
uv run wow-probe --trainer 94:05:BB:03:5D:9D --hrm E0:E2:EF:63:14:BC --watts 150 --seconds 60
sudo systemctl start wow
```

### On the laptop

```
uv run wow --config wow.toml          # devices as `simulate` in wow.toml says
uv run wow --config wow.toml --sim    # simulator; --sim overrides wow.toml
```

Stop with one Ctrl-C and wait for `wow stopped …`. `kill <pid>` sends SIGTERM and does the same orderly stop. To switch modes, stop and start again with or without `--sim`. Both modes write to `wow-data/`, so the Upload note above applies here too.

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

It prints RR-01 to RR-14 as pass, fail with the worst value, or not applicable; copy the lines into `docs/verification-log.md`. It reads the ride's files (`events.jsonl`, `samples.jsonl`, `ble.jsonl`, `timing.jsonl`, `meta.json`, `ride.fit`), and `logs/ble-system.jsonl` for the connection made before the ride.

To keep a real ride as a replay case (T-LOG-05), read the three files it writes before committing them:

```
uv run python tools/keep_ride.py wow-data/rides/<ride id> --out testdata/rides
uv run pytest -m pi tests/adapters/test_replay_kept.py
```

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
tools/              gate.py, trace.py, check_ride.py, keep_ride.py, import_spike_log.py
docs/               phase documents, verification log, generated traceability
```
