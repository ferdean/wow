# WitchesOnWheels

Runs structured workouts on the Van Rysel D100 from a Raspberry Pi 5; the iPhone shows the ride. Requirements, architecture, interfaces and the test plan are the phase documents in `docs/`.

**State:** Phase 5 closed on 18 Nov 2026: slices SL-01 to SL-14 built and approved, from the Bluetooth foundation to routes and the route screen. Version 0.8.0 goes into Phase 6, verification and validation, which starts with the closing checks on the Pi. The phase documents in `docs/` have the details.

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

FTP, zones, lead time, the battery warning, your weight (for routes), upload, the intervals.icu account and the trainer and strap are set on the Settings screen (from Home); `settings.json` and `secrets.json` don't need editing by hand. The devices are released 10 minutes after the last ride, Pre-ride or calibration, so Onelap can connect without stopping wow.

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

Rides on the simulator are never uploaded by themselves, whatever the Upload setting says (from 0.7.0; with 0.6.0 turn Upload off first); "Upload now" on their Summary still sends one if you ask. They show up in Past rides, where you can delete them.

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

## Garmin Connect upload (experimental branch)

On `feature/garmin-upload`, wow can also upload each finished ride to Garmin Connect (Settings → Garmin Connect, default off), through the unofficial python-garminconnect client. Sign in once on the Pi as the service's user:

```
sudo -u wow /opt/wow/venv/bin/wow-garmin login     # email, password, MFA code; stores tokens only
sudo -u wow /opt/wow/venv/bin/wow-garmin check
```

`docs/garmin-upload.md` has the design, the assumptions and the Pi checks to pass before merging.

## Riders who share the trainer (experimental branch, 0.8.2)

On `feature/garmin-upload`, several riders can share the trainer, each with their own settings, intervals.icu account, Garmin Connect sign-in and workouts. Name them in `/etc/wow/wow.toml`, the rider who rode before first:

```toml
[riders]
ferran = "Ferran"
anna = "Anna"
```

The page then asks who's riding, and each ride uploads to its own rider's accounts. `wow-garmin` takes the rider with `--rider anna`. `docs/riders.md` has the design, the setup and the Pi checks to pass before merging.

## Routes

A ride can be ridden along a GPX route. The trainer is controlled as without a route (ERG or resistance; there is no slope mode). Every second wow moves you along the route with your power (your weight from Settings plus a 9 kg bike, on the cycling power model of Martin et al., 1998); at Finish the same track goes into `ride.fit` with speed, distance, altitude and position, marked as a virtual ride. A ride longer than the route starts it again from the beginning.

During the ride, tap **Route ›** on the workout profile for the route screen: speed and climb in large, power, heart rate and step time small, a drawing of the route with your place and the distance, and the elevation profile with your place and altitude. Tap the drawing or **Workout** to go back; the workout screen is where every ride starts.

Put `.gpx` files in the data directory's `routes` folder:

```
mkdir -p wow-data/routes && cp deploy/routes/example-loop.gpx wow-data/routes/         # laptop
scp my-route.gpx pi:/tmp/                                                                # Pi, from the laptop
ssh pi 'sudo install -o wow -g wow -m 0640 /tmp/my-route.gpx /var/lib/wow/routes/'
```

Choose the route on Pre-ride (it stays chosen until you change it). The Summary shows the distance and climb. A file over 10 MB, with a DOCTYPE, with fewer than two points or shorter than 100 m is left out, and the log says why. `deploy/routes/example-loop.gpx` is a made-up 18.8 km loop with one 60 m hill, no real map data.

## Gallery

`https://wow.local/#gallery` (`:8443` on the laptop) lists every screen state the tests know (`testdata/display`) and shows each one through the real screens, on the phone; nothing is sent to the Pi. Swipe back to return to the list. It is how DS-8 (D-30, D-31) and the walk-through I-14 to I-20 are done.

## Gate

```
uv run python tools/gate.py --through SL-14
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

## Phase documents

One source each, in `docs/`; the Claude project holds copies of them.

| Document | File | Revision |
|----------|------|----------|
| Phase 0 discovery | `docs/phase0-discovery.md` | 2 |
| Phase 1 requirements | `docs/phase1-requirements.md` | 8 |
| Phase 2 risk spikes | `docs/phase2-spikes.md` | 14 |
| Phase 3A architecture | `docs/phase3-arch.md` | 6 |
| Phase 3B interface control document | `docs/phase3-icd.md` | 5 |
| Phase 3C display design | `docs/phase3-display.md` (figures in `docs/img/phase3-display/`) | 3 |
| Phase 4 test plan | `docs/phase4-test-plan.md` | 5 |
| Phase 5 implementation | `docs/phase5-implementation.md` | 15, closed |

### PDFs

`tools/make_pdf.py` typesets the phase documents in the format of the Phase 0 record, Mermaid diagrams and Phase 2's risk matrix included. Laptop only: its Python dependency is in the uv group `docs`, which `uv sync` and the Pi's install leave out. Once:

```
sudo apt install pandoc texlive-xetex texlive-latex-extra fonts-lmodern
uv sync --group docs
uv run --group docs playwright install chromium
npm ci --prefix tools/pdf
```

Then:

```
uv run --group docs python -m tools.make_pdf                 # every docs/phase*.md
uv run --group docs python -m tools.make_pdf docs/phase3-icd.md
```

The PDFs go to `build/pdf/`, named after the Markdown files. `--chrome <path>` uses an installed Chrome instead of Playwright's. `--screens` redraws 3C's figures instead, from the gallery (`tools/pdf/screens.json`) into `docs/img/phase3-display/`; it needs the built display in `src/wow/web/static/`, and the PDF is made by a second run. A missing glyph is printed after the PDF's name.

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
tools/              gate.py, trace.py, check_ride.py, keep_ride.py, import_spike_log.py, make_pdf.py (pdf/)
docs/               phase documents and their figures (img/), verification log, generated traceability
```
