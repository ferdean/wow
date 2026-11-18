# Phase 2 — Risk spikes

**Status:** closed and approved by Ferran, 10 Nov 2026 (revision 14). First approved on 8 Nov 2026 (revision 13); revision 14 adds S5 and S8, run on 9–10 Nov. S1, S2, S3, S5, S6 and S8 done; S4 and S7 partly done; the rest deferred with fallbacks to Phase 5 (see Open points). The changes to Phase 1 are in its revisions 4 and 5. Builds on the Phase 0 record (revision 2) and the Phase 1 requirements (revision 3), both approved 3 Nov 2026.

## How this phase works

- Each spike is the smallest throwaway experiment that retires one risk. Spike code lives in `spikes/` and never becomes app code.
- **Spikes run on the Raspberry Pi**, driven over SSH from the laptop. v1 depends on BlueZ on the Pi, and the timing checks (A-31) only mean something there; results from Windows would have to be repeated. A-13 (Windows build) therefore no longer blocks anything in this phase.
- Every Bluetooth spike writes a JSON Lines log of all GATT traffic with UTC and monotonic timestamps in milliseconds, a small version of the APP-813 format. Ferran sends the log files; Claude decodes and analyses them. The logs become the first replay fixtures (APP-820, D-17).
- The script-based spikes S1–S4 replace the nRF Connect session t22: same checks, plus timestamps, which t22 couldn't give for A-12. If the Pi isn't ready, t22 still works as a fallback for S1 and S3.
- Results go into the results table at the end; each one closes, confirms or refutes the assumptions it names.
- S1 ran on the Windows laptop (the log says `win32`). Its protocol results carry over to the Pi; its timings don't, so S2 onwards runs on the Pi.

## Risk register

Impact: what happens to v1 if the risk is real. Likelihood is a judgement from the evidence in Phase 0 and Phase 1.

| ID | Risk | Impact | Likelihood | Spike | Closes |
|------|------------------------------------------------------------|-----------------------------------|--------|------|------------------------|
| R-01 | The ERG path fails from the Pi: Request Control refused, targets ignored, Start or pairing needed first. | No ERG; v1 unusable. | Low: power target declared (feature bit 3) | S1 | A-5, A-25 (op and result codes) |
| R-02 | ERG settles too slowly or overshoots on 140↔330 W steps, so a lead time alone can't make 30/30s and 1-min surges follow the plan; or the Pi itself writes targets late. | Core sessions ride wrong; ERG smoothing moves into v1, or such blocks default to resistance mode. | Medium | S2 | A-12, A-31 |
| R-03 | With one rear cog, no chainring lets ERG hold both ~330 W and ~140 W at normal cadence. | 30/30s can't run in ERG; APP-207 and APP-309 carry them. | Medium: DC Rainmaker had to shift above ~350 W | S2 in each chainring | A-23 |
| R-04 | Indoor Bike Data power is late, smoothed or wrong compared with the Cycling Power service, or a resistance field of unexpected width shifts the power field. | Wrong power on screen and in the file. | Low–medium | S1, S2: both sources logged side by side; the decoder checks record length | D-18, A-37 |
| R-05 | Set Target Resistance Level needs a different parameter width than we send, or the levels don't get progressively harder. | Resistance mode doesn't work. | Medium: sources disagree | S1 | A-30, A-38 |
| R-06 | The D100's FTMS spin-down doesn't work as the spec describes. | D-20 can't be delivered. | Medium: only feature bit 15 is verified | S3 | A-22, A-24, A-25 (spin-down) |
| R-07 | After a lost link the trainer drops the target or re-advertises late, or after an app crash BlueZ holds a connection the restarted app can't use. | APP-318, APP-805, APP-809 and APP-811 at risk. | Medium | S4 | A-33, A-39 |
| R-08 | The Pi 5's Bluetooth shares its 2.4 GHz radio with Wi-Fi and loses data or delays writes. | Gaps in the file, late targets. | Low–medium: Pi 5 reports are about audio, not 1 Hz BLE | S5 | A-40 |
| R-09 | The HRM 200's battery value isn't a plain percentage, or two links on one controller drop heart rate. | Wrong battery warning, heart-rate gaps. | Low | S5, scan | A-21, A-32 |
| R-10 | intervals.icu workouts don't carry what the app needs: ramps apart from ranges, free ride, library steps. | Workout parsing redesigned around .zwo. | Medium | S6 (= t23) | A-26, A-27, A-35 |
| R-11 | Our FIT file is rejected or stripped (power, heart rate, laps, target), or a Garmin import comes back into intervals.icu as a duplicate. | Lost or doubled rides. | Medium | S7 | A-10, A-15, A-19, A-28 |
| R-12 | Safari doesn't grant the wake lock with a private root certificate, or Wi-Fi latency breaks the 250 ms budget. | Screen locks mid-interval; taps feel slow. | Medium | S8 | A-17, A-34 |
| R-13 | Pi platform: BlueZ version, wrong clock without network, LED access, slow boot. | Setup changes, small requirement edits. | Low | S0 (= t17) | A-16, A-29, A-36; APP-810 boot time |
| R-14 | Unread FTMS text: the procedure timeout (4.16.4) and split records (4.19). | Wrong timeout or record joining in Phase 3. | Low | S1, S2 logs show whether the D100 ever sets More Data; t19 keeps waiting for the text | A-25 (rest) |

**After Phase 2:** R-01 to R-05, R-08 to R-10 and R-12 retired; the others are rated in the risk matrix below and tracked in Open points.

## Risk matrix

Severity is what happens to v1 if the risk is real (the Impact column above), rated here on the scale below. Likelihood before Phase 2 is the register's own judgement; likelihood after Phase 2 follows the spike results. Retired risks leave the grid. Each cell's colour comes from its score, likelihood level × severity level: green 1–3, yellow 4–6, orange 8–9, red 12–16.

| Level | Severity | Likelihood |
|-------|----------|------------|
| 1 | Minor: a workaround outside the app, or small requirement edits | Low |
| 2 | Moderate: a feature needs a fallback or a redesign; rides still work | Low–medium |
| 3 | Major: a *must* fails during rides; sessions ride wrong or data is lost | Medium |
| 4 | Critical: v1 can't be used for training | High |

<!-- risk-matrix: the PDF draws the before and after grids from the table below -->

| Risk | Short name | Severity | Likelihood before | Likelihood after Phase 2 | Basis for the change |
|------|------------|----------|-------------------|--------------------------|----------------------|
| R-01 | ERG path from the Pi | Critical | Low | Retired | F-7, F-25 |
| R-02 | ERG settling on 140↔330 W steps | Major | Medium | Retired | F-25: 90 % in 1.5 s, overshoot ≤ 6 % |
| R-03 | One gear for 330 and 140 W | Moderate | Medium | Retired | F-27 |
| R-04 | Power late or mis-decoded | Major | Low–medium | Retired | F-1, F-4 |
| R-05 | Resistance command and levels | Moderate | Medium | Retired | F-12, A-38 |
| R-06 | FTMS spin-down | Minor | Medium | Low | F-30, F-37: one error after a sprint, one success |
| R-07 | Reconnect and crash recovery | Major | Medium | Low–medium | F-31 to F-33: the crash restart failed; the fix is known but untested (OP-1 to OP-3) |
| R-08 | Wi-Fi and Bluetooth on one radio | Moderate | Low–medium | Retired | F-46: 75 min with no gap over 1 s, Wi-Fi on 5 GHz |
| R-09 | Strap battery and heart-rate drops | Minor | Low | Retired | A-21, F-31 |
| R-10 | Workout content from intervals.icu | Moderate | Medium | Retired | F-17 to F-24, F-36 |
| R-11 | FIT file accepted, no duplicates | Moderate | Medium | Low | F-35; target power still open (OP-6) |
| R-12 | Wake lock and Wi-Fi latency | Moderate | Medium | Retired | F-41, F-44 to F-48 |
| R-13 | Pi platform details | Minor | Low | Low | S0; clock and LED still open (OP-8) |
| R-14 | Unread FTMS text | Minor | Low | Low | F-3; the text is still unread (OP-9) |

## New assumptions

| ID | Assumption | Status | Source | How it gets checked |
|------|--------------------------------|----------|---------------------------|-------------------------|
| A-37 | If the D100 reports a resistance level in Indoor Bike Data, the record length tells its width. | Not needed | S1: no record carries a resistance field (flags 0x0040 throughout), and the 10 undeclared bytes (F-1) make the length useless for this anyway. The decoder now takes the width from the resistance range layout: 6 bytes (FTMS 1.0) means sint16. | — |
| A-38 | Set Target Resistance Level takes a 1-byte parameter (uint8, 0.1 per step). | Confirmed | S1: `04 xx` succeeded at the first try for 0, 25, 50, 75 and 100, and the status echoes 1 byte. | — |
| A-39 | After the app is killed, BlueZ keeps the trainer connected, and a restarted app can use that connection without power-cycling the trainer. | Refuted | S4, 6 Nov: the restarted run didn't find the trainer (F-33). | Replaced by A-44 |
| A-40 | The Pi 5's on-board Bluetooth keeps 1 Hz data from the trainer and the strap with Wi-Fi active, with no gap over 2 s in an hour. | Confirmed on 5 GHz | S5, 10 Nov: 75 min with the S8 page running alongside; longest gap 0.49 s from the trainer and 0.98 s from the strap, no unplanned disconnect (F-46). Not tried on 2.4 GHz, where the Bluetooth audio stutter on the Pi 5 was reported (RPi-Distro firmware-nonfree #33). | — |
| A-41 | After granting control, the D100 sends one Reset status; a Reset at any other time means the trainer did reset. | Confirmed | 6 of 6 Request Controls, no Reset at other times (F-29). | — |
| A-42 | Repeat blocks in ride workouts come nested in `workout_doc` as `{"reps": n, "steps": [...]}`, as in the swim workout. | Confirmed | `workouts-repeat.json`, 6 Nov (F-36) | — |
| A-43 | When the same FIT reaches intervals.icu both from Garmin Connect and by direct upload, intervals.icu keeps one activity. | Not needed | Ferran, 6 Nov: the app's upload becomes a setting, so the rider picks one path (proposed APP-607 change). | — |
| A-44 | Releasing a stale BlueZ link (`org.bluez.Device1.Disconnect`) before connecting lets a restarted app reconnect without touching the trainer. | Open | bleak 3.0.2 source uses the same D-Bus call; bleak-retry-connector 4.7.1 (MIT, needs bleak ≥ 3.0.2) closes "unexpectedly connected" devices the same way before every connect (`close_stale_connections`). | Phase 5, reconnect slice (OP-3) |

## Facts checked for the spike code

| Fact | Source |
|------------------------------------------------------------|------------------------------------------|
| bleak 3.0.2 is the current release; it needs BlueZ ≥ 5.55 (since 1.0) and Python ≥ 3.10 (3.9 dropped in 2.0). | PyPI; bleak changelog |
| bleak 3.0.2 uses BlueZ StartNotify by default (the default changed in 3.0.2), and handles indications through `start_notify`. | bleak 3.0.2 source, `bleak/args/bluez.py` |
| bleak's default connect timeout is 30 s (since 2.1.1); the spikes use 10 s for reconnects. | bleak changelog |
| `write_gatt_char(..., response=True)` waits for the ATT write response; the FTMS answer then comes as a separate indication. | bleak 3.0.2 docstring; FTMS 1.0.1 Table 4.15 (Phase 1) |
| Indoor Bike Data layout: flags, then fields in bit order; Instantaneous Speed is present when bit 0 (More Data) is **0**; cadence 0.5 rpm; speed 0.01 km/h. | SIG GSS YAML via bluetooth-sig 0.6.0 |
| Cycling Power Measurement: flags, power (sint16), then optional fields; crank revolutions are uint16 + event time in 1/1024 s. | SIG GSS YAML |
| Heart Rate Measurement: uint8 or uint16 value by flag bit 0; energy before RR intervals. | SIG GSS YAML |
| The official Garmin FIT Python SDK (garmin-fit-sdk 21.221.0) includes an encoder, so S7 needs no third-party FIT writer. | garmin-fit-sdk 21.221.0 package contents |
| uv installs on Linux with `curl -LsSf https://astral.sh/uv/install.sh \| sh`. | uv documentation |
| Apple's rules for TLS server certificates: RSA keys of at least 2048 bits, SHA-2 signatures, the host name in Subject Alternative Name, Extended Key Usage with serverAuth, at most 825 days of validity. | Apple support 103769 |
| The 825-day limit applies to every root, private ones included; the 398-day limit only to roots preinstalled in iOS. | Apple DTS, Developer Forums thread 773796 |
| A root installed as a profile is trusted for TLS only after "full trust" is turned on under Settings → General → About → Certificate Trust Settings. | Apple support 102390 |
| iOS supports critical name constraints from iOS 9. | Apple, CA/B Forum server certificate working group, Feb 2020 |
| Safari on iOS supports the Screen Wake Lock API from 16.4. | caniuse |
| The browser releases a screen wake lock when the page is hidden; the usual pattern requests it again on `visibilitychange`. | Chrome for Developers, Screen Wake Lock |

## Spikes

Before every Bluetooth spike: close Onelap and nRF Connect on the phone (the D100 takes one connection at a time), and pedal to wake the trainer.

### S0 — Pi set-up (t17, extended) · desk, ~45 min

1. Raspberry Pi Imager: Raspberry Pi OS Lite (64-bit), Trixie. In its settings: hostname `wow`, your user, Wi-Fi, SSH with your laptop's public key.
2. From the laptop: `ssh <user>@wow.local`. Then `bluetoothctl --version` (A-16) and `bluetoothctl show` (should say `Powered: yes`).
3. Clock (A-29): unplug for 10 min, boot with the router off (or Wi-Fi switched off), run `timedatectl`, compare with your phone.
4. LED (A-36): check the green LED shows through the case; `cat /sys/class/leds/ACT/trigger`.
5. Boot time (APP-810): power on with a stopwatch; note when `ssh` first succeeds. Then `systemd-analyze`.
6. Tools: `curl -LsSf https://astral.sh/uv/install.sh | sh`, log out and in again.
7. Unzip `wow-spikes.zip` on the laptop and copy the folder: `scp -r wow-spikes <user>@wow.local:~`, then on the Pi `cd ~/wow-spikes && uv sync && uv run pytest -q` (should end with `27 passed`).

If a Bluetooth command fails with an access-denied error: `sudo usermod -aG bluetooth $USER`, then log in again.

**Send:** the outputs of steps 2–5.

### S1 — First contact · trainer, ~6 min · R-01, R-04, R-05

```
uv run spike_trainer.py scan
export WOW_TRAINER=<D100 address from the scan>
export WOW_HRM=<HRM 200 address from the scan>
uv run spike_trainer.py contact
```

The script reads device information, features and ranges, subscribes to Indoor Bike Data, Cycling Power, Fitness Machine Status and the control point, then shows one instruction at a time:

1. 30 s steady at ~85 rpm without control (baseline).
2. Request Control, then 200 W **without** Start or Resume: 20 s at ~80 rpm, 20 s at ~95 rpm.
3. Start or Resume, then 200 W again: same 40 s.
4. Resistance at 0, 25, 50, 75 and 100 % of the range, 30 s each, same gear, ~85 rpm. Ctrl-C stops at any time and leaves the trainer at its lowest level.

ERG is working when power stays near 200 W while the speed (which follows cadence in a fixed gear) changes.

**Pass:** Request Control succeeds; ERG holds ~200 W at both cadences in step 2 or 3; power rises from level to level in step 4.
**Note:** whether 200 W felt different before and after Start; how hard the top level felt.
**Send:** the `logs/scan-*.jsonl` and `logs/contact-*.jsonl` files, and the scan output.

### S2 — ERG step response · trainer, ~19 min, 14 without warm-up · R-02, R-03, R-04

A real interval session: 5 min at 150 W, 6 × (30 s at 330 W / 30 s at 140 W), 2 min at 220 W, 1 min at 325 W (~130 % FTP), 2 min at 220 W, 3 min at 140 W. Ride it on a day you'd do intervals anyway.

```
uv run spike_trainer.py steps --tag ring1 --lead 0
```

One run in the front chainring you ride on the trainer: the Zwift Cog fixes only the rear, so the front ring is the one gear choice left. Normal cadence, no shifting during the run. Lead 0 measures the raw response. A second run in the other front ring (`--tag ring2 --warmup 0`) only if the bike has one and the first run can't hold 330 W or get down to 140 W.

**Claude computes from the log**, per transition: delay to the first change, time to 90 % of the step (T90), overshoot, and the lag between Indoor Bike Data and Cycling Power; and for every target, the time from due to written (A-31: 100 ms).

**Decision rules (proposed here):**

- Lead time default (Table S) = median T90 rounded to 0.5 s, capped at 5 s.
- If median T90 is over 5 s or overshoot over 15 %, ERG smoothing moves from the later-versions list into v1.
- If the front ring you ride can't hold 330 W at normal cadence or can't get down to 140 W, try the other front ring if there is one. If no ring works, 30/30 blocks default to resistance mode and APP-309 becomes *must*.

**Limit:** without a separate power meter, the measured response is brake and reporting together. Cycling Power can't help: it carries the same value at the same instant (F-4). In steady ERG the reported power sits on the target (F-11), so the analysis looks at the transitions. Speed follows cadence in a fixed gear: keeping `v` steady keeps cadence steady.

**S2b, later:** the same profile with `--lead <value>`. Pass: from 5 s after each boundary, reported power stays within ±10 % of target for the rest of the step in at least 5 of 6 intervals.

### S3 — Spin-down · trainer, ~3 min after a 10 min warm-up · R-06

Run t05 (Onelap spin-down) first as the reference.

```
uv run spike_trainer.py spindown
```

The script requests control and starts the spin-down, shows the target speed band the trainer returns, and the live speed. Speed up past the band; stop pedaling when it shows `STOP PEDALING NOW`; wait for the result.

**Pass:** the start returns a speed band; a Stop Pedaling status arrives; Success arrives within 120 s (APP-504). Compare speeds and outcome with Onelap.

### S4 — Dropouts and crash · trainer, ~25 min · R-07

Two SSH sessions: one runs the ride, the other breaks things.

**Run 1, what the trainer does without us (A-33):**
```
uv run spike_trainer.py ride --watts 170 --minutes 6 --hold-off 30
```
a. After 2 min, in the second session: `bluetoothctl disconnect $WOW_TRAINER`. The script waits 30 s before reconnecting. Keep pedaling and note whether the resistance stays at 170 W, drops to easy, or changes otherwise.

**Run 2, recovery times (APP-805, APP-806, APP-105):**
```
uv run spike_trainer.py ride --watts 170 --minutes 15
```
b. Three times, 1 min apart: `bluetoothctl disconnect $WOW_TRAINER`. The script prints `trainer back after … s`.
c. Unplug the trainer's power for 10 s and plug it back (a trainer reset; the brake goes free meanwhile, so spin lightly). Note roughly how long after plugging in it recovers.
d. `bluetoothctl disconnect $WOW_HRM` once.
e. Crash (A-39): `pkill -9 -f spike_trainer`, then `bluetoothctl info $WOW_TRAINER | grep Connected`, then start Run 2 again and note whether it connects and takes control without touching the trainer.

**Pass:** b and d recover within 10 s; c recovers within 10 s of the trainer advertising again; e works without power-cycling the trainer.

### S5 — One-hour ride · trainer, 60 min Z2 · R-08, R-09

```
uv run spike_trainer.py ride --watts 170 --minutes 60
```

A normal endurance ride with the strap, Wi-Fi as usual and the phone nearby. Pick the wattage you'd ride anyway.

**Claude computes:** gaps over 2 s per source, unplanned disconnects, notification interval jitter.
**Note:** the strap battery the script prints at the start, and what the Garmin computer says about the strap (A-21).
**Pass:** no gap over 2 s and no unplanned disconnect (A-40); battery value 0–100 and close to Garmin's.

**Ran 10 Nov** as the planned Z2 ride, `ride --watts 165 --minutes 75`, with S8's page running on the iPhone (F-46 to F-50).

### S6 — intervals.icu workouts (t23, unchanged) · desk, ~15 min · R-10

As in t23: build the `WOW test` workout (Z2, 88–92 %, 150-170w, a ramp, free ride), save it in the library and on a day this week, create an API key, download `events.json`, `workouts.json` and `test.zwo`, attach the three files. Never paste the key.

### S7 — FIT round trip · desk, after S5 · R-11

Claude writes `spike_fit.py` with the official Garmin FIT Python SDK. It turns the S5 log into a FIT activity: one record per second (power, heart rate), laps, indoor cycling, and the per-second target stored in two candidate forms (A-28). Ferran uploads it to intervals.icu through the API, imports the same file into Garmin Connect, and checks 24 h later that intervals.icu shows one activity, not two (A-15).

**Pass:** both accept the file; power, heart rate and laps survive in both; target power visible in at least one form; no duplicate; intervals.icu's load is noted (A-19).

### S8 — iPhone display · desk, after S0 · R-12

Claude writes `spike_display.py`: a standard-library HTTPS server on the Pi with one test page, plus the steps to make a private root certificate and a server certificate for `wow.local`, and to install and fully trust the root on the iPhone. The page requests the screen wake lock, re-requests it when the page becomes visible again, and times 300 round trips to the Pi.

**Pass:** the wake lock is granted and the screen stays on for 20 min (A-17); 95th-percentile round trip ≤ 200 ms, so one way ≤ 100 ms (A-34).

**Ran 9 Nov** at the desk (22 min) and **10 Nov** (a check of the root, then alongside S5), with spike 0.1.5 to 0.1.7. `spike_certs.py` makes the root and the server certificate; its `--constraints` option chooses how the root is limited (F-38 to F-48).

## Run order

| When | What | Who |
|---------------|------------------------------------------------------------|---------|
| Any time | t14 (`winver`, 30 s): still useful for development on the laptop | Ferran |
| Before trainer session 1 | t04 done (no update offered), t05 done 5 Nov; S0 left: LED, clock detail | Ferran |
| Any time | S6 intervals.icu files: done 5 Nov | Ferran |
| Trainer session 1 (~40 min) | S1 done 4 Nov (laptop). Left: S2 in the front ring you ride, S3, on the Pi with spike-0.1.1 | Ferran |
| After session 1 | S1–S3 analysis, lead time proposal | Claude |
| Trainer session 2 (~90 min) | S4, then S5 | Ferran |
| After session 2 | S4–S5 analysis; S7 and S8 scripts | Claude |
| Desk | S7, S8 | Ferran |
| Next interval day | S2b with the proposed lead time | Ferran |
| 9–10 Nov | S8 at the desk; on 10 Nov a check of the root, then S5 during the Z2 ride with S8 alongside | Ferran |

## Closing Phase 2

**Exit criterion, changed:** every risk has a result, or a deferral that names its fallback and the phase that checks it. The original criterion (a result for every risk) needs S5, S7 and S8, about two more evenings.

**10 Nov:** S5 and S8 ran after all (F-38 to F-50), so OP-5 and OP-7 are closed and only the deferrals below marked for Phase 5 remain.

**6 Nov evening (done; results in the 6 Nov findings):**

| Step | What | Closes |
|------|------|--------|
| 1 | Copy the spike-0.1.3 folder to the Pi as `~/wow-spikes` (`scp -r wow-spikes ferran@wow.local:~/`), `uv run pytest -q` (33 passed), `uv run spike_trainer.py scan` | Scanning works under BlueZ |
| 2 | t32: `events.json` for a day with the fixed repeat workout | A-42 |
| 3 | S2: `steps --tag ring1 --lead 0`, optionally `--reps 3` (16 min instead of 19, 10 transitions instead of 16) | A-12, A-23, A-31, A-41 |
| 4 | S3: `spindown`, straight after S2 while warm | A-22, A-25 (spin-down), A-41 |
| 5 | S4, short (about 12 min, below) | A-33, A-39, A-41; reconnect times |
| 6 | `uv run spike_fit.py logs/*-20261106T*.jsonl -o tonight.fit`: one FIT activity from all of tonight's runs. Import it into Garmin Connect; next morning, check whether it reached intervals.icu by itself; if not, upload it there by hand | A-10, A-15, A-19 |
| 7 | Send `logs/`; Claude analyses, proposes the lead time and writes the close-out | — |

**Retest (6 Nov):** Ferran reran only the spin-down, which succeeded (F-37). The other points are deferred, each with the evidence already in hand:

| Point | Evidence now | Fallback | Checked in |
|-------|--------------|----------|------------|
| Trainer after a real link loss (A-33) | None (F-31). APP-318 re-sends the target after any reconnect, so no requirement depends on the answer. | — | Phase 5, reconnect slice (`--drop-at`) |
| Reconnect within 10 s (APP-805) | Connects on the Pi took 2.3–6.1 s; the strap came back in 4.0 s. | — | Phase 5, reconnect slice |
| Restart after a crash (A-44) | Mechanism understood (F-33); a maintained library does the same release before every connect. | Unplug the trainer for 10 s | Phase 5, reconnect slice (`--crash-at`) |
| Duplicates in intervals.icu (A-43) | Not needed: the upload becomes a setting. | — | — |

**S4, short version.** Second SSH session for the `bluetoothctl` commands, with the addresses typed out (the exports don't carry over):

- Run A (A-33): `ride --watts 170 --minutes 5 --hold-off 30`. After 2 min, `bluetoothctl disconnect 94:05:BB:03:5D:9D`. Keep pedaling for the 30 s hold-off and note whether it stays 170 W-hard or goes easy.
- Run B (APP-805, APP-806): `ride --watts 170 --minutes 6`. After 1 min, disconnect the trainer once and wait for `trainer back after … s`. At 3 min, `bluetoothctl disconnect E0:E2:EF:63:14:BC` (strap).
- Crash (A-39): during Run B, `pkill -9 -f spike_trainer`, then `bluetoothctl info 94:05:BB:03:5D:9D | grep Connected`, then `ride --watts 170 --minutes 2`: does it connect and take control without touching the trainer?
- Dropped from the full S4: unplugging the trainer's power.

**Deferred:**

| Spike | Risk | Fallback | Checked in |
|-------|------|----------|------------|
| S5, 1 h ride | R-08: Wi-Fi and Bluetooth on one radio (A-40) | 5 GHz Wi-Fi, or a USB adapter with `dtoverlay=disable-bt`; Phase 3 keeps the adapter configurable | Done 10 Nov: 75 min (F-46) |
| S2b | R-02: the lead time value | The lead time is a setting (APP-703) | Tuning on real workouts in Phase 5 |
| S7, FIT round trip (A-10, A-15, A-19 tonight with `spike_fit.py`) | R-11, A-28 only | Target power left out of the file if no form survives (A-28); no Garmin import if it duplicates (A-15) | Phase 5 recording slice; the FIT writer sits behind its own interface |
| S8, iPhone display | R-12 (A-17, A-34) | Auto-Lock set to Never (APP-409); Phase 3 keeps TLS in the server configuration, so dropping it changes no module | Done 9–10 Nov (F-38 to F-48) |
| S4 retest | A-33, A-44, APP-805 | See the table above | Phase 5 |
| S0 rest | A-29, A-36 | APP-824 stays either way; the LED (APP-826) is *could* | Phase 5 |

## S1 findings

From `contact-20261104T214602Z.jsonl` and `scan-20261104T213612Z.jsonl` (4 Nov, Windows 11 build 26200, bleak 3.0.2). Times are seconds from the start of the run.

| # | Finding | Evidence | Consequence |
|------|------------------------------------------------------------|------------------------------|------------------------------------------|
| F-1 | Every Indoor Bike Data record is 16 bytes, but its flags (0x0040: speed and power) declare 6. The D100 appends 10 bytes the flags don't declare. | 1076 of 1076 records | Decode by the flags and ignore what follows. A decoder that insists on an exact length fails on every record: the spike's did, and pyftms 0.4.15 checks that nothing is left over. APP-108 change proposed below. |
| F-2 | The undeclared bytes are five 16-bit values: one moves with speed, two with the brake (one is about 30 per resistance step and 0 with no load), one falls as the brake rises, one is constant (28). | Means per phase | Undocumented; not used. |
| F-3 | No record sets More Data, so none is split. | Flags in all 1076 records | APP-108's join never runs on the D100; it stays for other trainers. A-25's open section 4.19 doesn't block. |
| F-4 | Indoor Bike Data power and Cycling Power are the same value, sent at the same instant. | 1075 of 1075 pairs | D-18 stands; Cycling Power adds nothing. |
| F-5 | Power and speed arrive at about 3.6 Hz (median 281 ms, longest gap 485 ms). The HRM 200 sends heart rate at about 1.9 Hz and Battery Level about every 2 s. | Notification intervals | A-12's "1 Hz" (from reviews) is wrong. APP-602's 2 s hold has a wide margin. |
| F-6 | Cycling Power carries only the balance byte (always 0); no crank data. | 1075 records | No cadence from either service, as expected (D-05). |
| F-7 | Request Control, Set Target Power, Start or Resume and Set Target Resistance Level each answer `80 <op> 01` (success). ERG works without Start or Resume. | 10 commands | R-01 retired; A-5 confirmed by demonstration. |
| F-8 | After control is granted, the D100 sends a Reset status (`01`). | 0.3 s after `80 00 01` | APP-105 requests control again after a reset. If every grant produces a Reset, that loops. A-41, checked in S2–S4. |
| F-9 | Every status is sent three times within about 0.3 s. | 23 statuses, 9 distinct | Status handling must be idempotent. The spike now reports each once. |
| F-10 | Step 53 → 200 W at ~31 km/h: first change 0.8 s after the write began, 90 % at 3.6 s, within 1 W at 4.8 s, no overshoot. The rise is close to linear at ~48 W/s. | Power, 39.1–44 s | Fits A-12's ~3 s. If ~48 W/s is a rate limit, 140 → 330 W needs about 4.4 s to 90 %. S2 measures it. |
| F-11 | In steady ERG the reported power stays at 200.0 ± 0.5 W while speed drifts from 28.6 to 26.0 km/h. | ERG phases, 2 s bins | Most likely the trainer's own estimate, held on target by its controller: in steady ERG it can't show a tracking error. APP-402's rationale (power varies within a stroke) doesn't apply to the D100. |
| F-12 | Resistance 0, 25, 50, 75, 100 % gave 59, 82, 138, 231, 313 W while speed fell from 32 to 25 km/h. | Resistance phases | A-30 confirmed: the whole range, each level harder. |
| F-13 | On Windows a control point write took 109–203 ms to complete; the answer came 172–390 ms after the write began. | 10 commands | Nothing about the Pi (A-31); S2 on the Pi measures it. |
| F-14 | The D100 advertises FTMS with service data `01 20 00` (available, indoor bike) and the Zwift service UUID; the HRM 200 advertises Heart Rate (0x180D). | Scan | A-32 confirmed. |
| F-15 | HRM 200: Battery Level `0x50`, 80 %, throughout; heart rate as 8 bits with one RR interval per notification; sensor contact not supported. | 525 + 137 notifications | A-21 confirmed. The strap can't report whether it's worn. |
| F-16 | Device information: DECATHLON, model 355194, firmware 0.108, build 7 Jan 2025, as in the Phase 0 probe. | Reads | Onelap offered no update (5 Nov): 0.108 is the firmware v1 rides on. |

## S6 findings

From `events.json` (3–10 Nov), `workouts.json` (library) and `test.zwo` (the Staircase workout of 5 Nov), fetched 5 Nov.

| # | Finding | Evidence | Consequence |
|------|------------------------------------------------------------|------------------------------|------------------------------------------|
| F-17 | Planned and library workouts both carry the parsed workout as `workout_doc.steps`, with the same step structure. | 5 of 5 rides | A-35 confirmed. A-26's worry that the parse can be missing doesn't show in this sample. |
| F-18 | Each target keeps its unit: `w`, `%ftp` or `power_zone`. A range is `{start, end}`; a ramp adds `"ramp": true`; free ride is `"freeride": true` with no power; warm-up steps carry `"warmup": true`. | `tEST`: `88-92%`, `150-170w`, `ramp 50%-75%`, `freeride` | A-26 holds for ranges and ramps; A-27 confirmed. |
| F-19 | intervals.icu rides a range at its midpoint and counts free ride as 0 W: `tEST` averages 141 W, exactly what midpoints give. | `average_watts` | APP-205's midpoint rule matches intervals.icu. |
| F-20 | A zone target arrives as a zone number: `105m Z2` is `{"units": "power_zone", "value": 2}`. intervals.icu shows 163 W for that ride, the middle of its Z2 (138–187 W at FTP 250). Every ride also carries `zoneTimes`, with each zone's upper bound in % of FTP; intervals.icu has 7 power zones, the app's defaults 6. | `Easy`, 7 Nov | A-26 refuted for zones. APP-204 doesn't list zone targets, so as written APP-206 would run the weekly Z2 ride in resistance mode. Change proposed below. |
| F-21 | Repeats come nested, `{"reps": 6, "steps": [...]}`, in the swim workout; no ride in the sample has one. | Swim, 6 Nov | A-42. |
| F-22 | The .zwo loses information: absolute watts become fractions of intervals.icu's FTP (`ftpOverride` 250), the 145–175 W range becomes a `SteadyState` with `PowerLow` and `PowerHigh`, and the warm-up flag is gone. | `test.zwo` vs `workout_doc` | The app reads `workout_doc`; the .zwo download isn't needed. |
| F-23 | The `3x` in Staircase's description didn't become a repeat: the parse has the 1 min 240 W / 1 min 140 W / 3 min 150 W block once, total 90 min instead of 100. | `workout_doc`, 5400 s | Ferran confirmed a parsing issue in the description. The app rides what intervals.icu parsed, as Zwift or a Garmin would. |
| F-24 | Events include gym and swim sessions; the day is `start_date_local` at midnight; `indoor` is `false` or `null` on planned rides. | `events.json` | APP-201 filters on category `WORKOUT` and type `Ride`; the indoor flag can't be used. |

## 6 Nov findings (S2, S3, S4, FIT)

From the logs of 6 Nov on the Pi (spike 0.1.2): `steps` (3 reps), `spindown`, three `ride` runs, two scans, and Ferran's notes.

| # | Finding | Evidence | Consequence |
|------|------------------------------------------------------------|------------------------------|------------------------------------------|
| F-25 | ERG step response: power starts moving 0.7 s after the write begins; 90 % of the step (T90) at 1.46 s going up and 1.50 s going down, over 10 transitions between 140 and 330 W; overshoot inside a transition at most 12 W (6 % of a 190 W step); steady state within ±2.3 W. Ferran found it faster than Rouvy. | `steps` log | A-12 refuted: much faster than ~3 s. Lead time default 1.5 s by the agreed rule (median T90, rounded to 0.5 s). ERG smoothing stays out of v1: both thresholds (5 s, 15 %) are far off. |
| F-26 | F-10 corrected: S1's slow rise (~48 W/s) was not a rate limit; S2's steps rise at about 240 W/s. The one visible difference: S1 set the target without Start or Resume, S2 sent Start or Resume first. | S1 vs S2 | The app sends Start or Resume after taking control, as S2 did. |
| F-27 | 330 W and 140 W both held in Ferran's front ring, at 26–30 km/h. | Notes; speed | A-23 confirmed. R-03 retired. |
| F-28 | On the Pi a target is written 0–1 ms after it falls due; the write completes in 95–195 ms and the trainer answers in 186–390 ms, as on Windows. | 13 commands | A-31 confirmed for the start of the write. APP-801's "write within 100 ms" can only mean the start of the write (change proposed). |
| F-29 | Every Request Control (6 of 6, S1 included) is followed by exactly one Reset status 0.2–0.3 s later; no Reset came at any other time. | All logs | A-41 confirmed; the APP-105 change stands. |
| F-30 | Spin-down: the trainer returns a band of 0–40 km/h and repeats Stop Pedaling every ~0.25 s while speed is above 40 km/h. Ferran sprinted to 44 km/h, so the coast began 4.5 s after the first Stop Pedaling; the trainer reported Error 29.9 s after speed fell back through 40 km/h, at 6.6 km/h. The brake was off during the coast (vendor field 0). The coast from 40 to 10 km/h took 26.4 s, the same as Onelap's successful 26 s. | `spindown` log | The trainer behaves as it does under Onelap; the likeliest cause is the overshoot (assumption). Retest R1 with a gentle approach. A-22 stays open. The display must show the speed faster than once a second here (APP-803 covers it). |
| F-31 | `bluetoothctl disconnect` never cut the trainer link: in both S4 runs the trainer kept sending 40 packets every 10 s, at 160 W, also through the 30 s the spike showed as a loss in run A (that was F-32's false alarm). The strap disconnect worked; it was back in 4.0 s. Ferran felt no change in those 30 s because ERG was still running. | Packets per 10 s, both runs | APP-806 met (4.0 s ≤ 10 s). A-33 still untested; spike 0.1.4 drops the link itself (`--drop-at`). |
| F-32 | bleak on BlueZ retries an aborted connect inside `connect()` and reports the abort as a disconnect. In S4 run A the spike took that for a link loss and later tried to connect a second time while the first link was still up. | `ride` log, 1.2 s; bleak 3.0.2 source (`le-connection-abort-by-local` retry) | The app ignores disconnect reports that arrive during a connect or from an older client (spike 0.1.4 does; Phase 3 state machine). |
| F-33 | After `kill -9` the restarted spike couldn't find the trainer: BlueZ keeps the link after its owner dies (bluez#89, as bleak's source notes), the D100 stops advertising while linked, and bleak connects by address only after seeing an advertisement. | Crash run: "not found" after 30 s | A-39 refuted. Fix: release the stale link through BlueZ (`Device1.Disconnect`) before every connect (spike 0.1.4); A-44 checks it. |
| F-34 | Over about 21 min of runs on the Pi, the longest trainer gap was 1.6 s; heart rate had none apart from the forced drop. | Gaps per device | First evidence for A-40, assuming the Pi was on Wi-Fi as set up. |
| F-35 | Garmin Connect accepted `tonight.fit` with power and heart rate, then passed it on to intervals.icu by itself. The activity has no name; it has no speed because the file records none. | Ferran's check | A-10 confirmed. A-15 refuted: with the app uploading to intervals.icu (APP-607) and a Garmin import, each ride could arrive twice unless intervals.icu spots the duplicate (A-43). D-10 needs a decision. |
| F-36 | A ride with repeats arrives with each set nested: `{"reps": 6, "text": "Set 1 6x", "steps": [330 W 30 s, 140 W 30 s], "duration": 360}`. The block's duration covers all its reps. Cool-down steps carry `"cooldown": true`; a ramp can run downwards (170 → 120 W). | `workouts-repeat.json` (library, 6 Nov) | A-42 confirmed. |
| F-37 | Spin-down retest: Ferran built up slowly (long trousers) and peaked at 40.5 km/h. Stop Pedaling came at 40.0 km/h and repeated only while speed stayed near 40; the trainer reported Success (`14 02`) 30 s after speed fell back below 40. The Success status carries 2 extra bytes (`97 6C`), which FTMS doesn't define for this status; their meaning is unknown (perhaps a coast-down time, assumption). | `spindown-20261106T210145Z` | A-22 confirmed. The 6 Nov error most likely came from the sprint to 44 km/h. Spin-down stays *must*. The display tells the rider to ease up to the upper speed without a sprint (Phase 3 screen design). The app logs the extra bytes (APP-813). |

## 9–10 Nov findings (S8, S5)

From `display-20261109T123343Z.jsonl` (desk, 9 Nov), the console of the root check on 10 Nov, and `display-20261110T173926Z.jsonl` with `ride-20261110T174048Z.jsonl` (the Z2 ride, 10 Nov). Spike 0.1.5 to 0.1.7 on the Pi, Safari 26.6 on the iPhone, Wi-Fi on 5 GHz (5540 MHz). Times are UTC.

| # | Finding | Evidence | Consequence |
|------|------------------------------------------------------------|------------------------------|------------------------------------------|
| F-38 | The first root, limited to `wow.local` and excluding every IP address, wasn't trusted although it was installed and given full trust: Safari warned, Ferran clicked through twice, and the Pi logged two handshakes the phone refused (`certificate unknown`). After the click-through the page still counted as a secure context, and the wake lock worked. | 9 Nov log, 12:35:08; Ferran | A-17 not shown by this run. Clicking through a warning before every ride isn't acceptable. |
| F-39 | The wake lock was granted on the Start tap, and the screen stayed on for 21:57 with Auto-Lock at 30 s: 264 beats, none more than 5.1 s apart, page never hidden. | 9 Nov log; Ferran (Auto-Lock) | The lock holds through a long untouched stretch. |
| F-40 | Without a tap, Safari refuses the wake lock: `NotAllowedError: Permission was denied` after every page load, 7 of 7 over both days. | Both display logs; 10 Nov console | The page can't keep the screen on by itself after a load or reload. |
| F-41 | Round trips at the desk, 9 Nov: 5,264, none failed; median 24 ms, 95th percentile 34 ms, 99th 55 ms, longest 350 ms; 11 (0.2 %) over 100 ms. | 9 Nov log | A-34 confirmed: about 17 ms one way at the 95th percentile, against 100 ms. |
| F-42 | After about 10 s in another app, Safari reloaded the page by itself, three times within 7 s. Ferran didn't touch it. During the ride, six returns from other apps caused no reload. | 9 Nov log, 12:58:31–38; Ferran | A reload happens without warning: the display rebuilds from the Pi (APP-807) and needs a tap for the lock (F-40). |
| F-43 | Safari resets its idle connections a few seconds after the page goes into the background: 23 resets during the ride. Harmless; spike 0.1.6 logs them instead of printing a traceback. | 10 Nov display log | The app's server treats a reset as normal. |
| F-44 | A root limited to `wow.local` by name only, without the IP-address exclusion, is trusted: no warning and no refused handshake on 10 Nov, at the desk or during the ride. Only the exclusion and a fresh install changed between the two roots, so the exclusion is the likely cause of F-38 (assumption). | 10 Nov console and display log | Keep the name-only root. A leaked key could still sign certificates for `wow.local` names and for IP addresses, not for other sites' names. |
| F-45 | When the page comes back into view after another app, Safari grants the wake lock again without a tap: 8 of 8 (2 at the desk, 6 during the ride). | 10 Nov console and display log | Requesting the lock again on `visibilitychange` works; only a reload needs a tap. |
| F-46 | S5: 75 min of ERG at 165 W, with the S8 page running alongside (4 round trips a second) and the Pi on 5 GHz Wi-Fi. Trainer: 18,037 Indoor Bike Data records at 4.0 Hz, longest gap 0.49 s. Strap: 9,012 heart-rate values at 2.0 Hz, longest gap 0.98 s. No gap over 1 s, no unplanned disconnect; both links closed as planned. | Ride log | A-40 confirmed on 5 GHz; R-08 retired. |
| F-47 | Round trips during the ride, with Bluetooth busy: 12,742, none failed; median 23 ms, 95th percentile 29 ms, 99th 47 ms, longest 368 ms. | 10 Nov display log | Bluetooth traffic doesn't slow the Wi-Fi round trip (A-34). |
| F-48 | Riding untouched, the screen stayed on for 50:06 with the lock held: 601 beats, none more than 5.1 s apart, until the page was next hidden. The display test's own 75-min run didn't complete: Ferran reloaded the page after 8 min, and the run restarted. | 10 Nov display log, 17:50:50–18:41:02; Ferran | A-17 confirmed, together with F-44. |
| F-49 | The strap reported 80 % battery throughout, in 2,330 notifications about 2 s apart. Garmin's own reading wasn't compared. | Ride log | A-21 stands as confirmed in S1; S5's battery comparison is left out. |
| F-50 | ERG at 165 W: mean 165.3 W, 97.7 % of records within ±2 W. 48 short upward excursions to at most 215 W, each back within 4.2 s (median 1.0 s), most likely gear or cadence changes (assumption). Records came at 4.0 Hz this time, alternating about 200 and 290 ms apart, against 3.6 Hz in S1 (F-5). | Ride log | Consistent with F-25. APP-602's 2 s hold keeps a wide margin. |

## Changes to Phase 1

Approved with this record on 8 Nov 2026 and applied in Phase 1 revision 4.

| Requirement | Change | Why |
|-------------|--------|-----|
| APP-108 | Add: "and shall ignore bytes beyond the fields the flags declare". | F-1 |
| APP-105 | Exempt the one Reset status that follows a granted Request Control. | F-8; only if S2–S4 confirm A-41 |
| APP-204, APP-205 | Add power-zone targets: the midpoint of the zone as intervals.icu defines it in the workout's `zoneTimes` (% of FTP), times the app's FTP. A zone without an upper bound (Z7) is handled by APP-206. Recommended over the app's own zones (APP-702) because the plan's zones are intervals.icu's (7 zones), and the two can differ. | F-20 |
| APP-801 | "start writing it to the trainer within 100 ms" instead of "write it": a write takes 95–195 ms to complete on both hosts. | F-28 |
| Table S | Lead time default 1.5 s instead of 0 s. | F-25 |
| D-10, APP-607, APP-608, APP-609, table S | Uploading to intervals.icu becomes a setting: "Where upload to intervals.icu is on, when the ride files are written, the system shall upload the FIT file…"; APP-608 and APP-609 apply where it is on. New table S row: upload to intervals.icu, on or off, default on. The FIT download for a Garmin import (APP-610) stays. Ferran, who imports into Garmin Connect (which passes rides on to intervals.icu), would turn it off. | F-35; Ferran, 6 Nov |
| APP-305, APP-402, APP-503, APP-602 | Rationales only: the D100 reports at about 3.6 Hz, its ERG power doesn't vary within a stroke, and its spin-down Success carries 2 undocumented bytes, which are logged. Requirement texts unchanged. | F-5, F-11 |

**From S5 and S8:** approved with revision 14 of this record on 10 Nov 2026 and applied in Phase 1 revision 5.

| Requirement | Change | Why |
|-------------|--------|-----|
| APP-416 (new) | "While a ride or calibration is running, if the display doesn't hold the screen wake lock, then the display shall show a full-width prompt that requests the lock when tapped." *must*, verified by demonstration; traces UC-01, UC-04, D-03. | F-40, F-42 |
| APP-409 | Rationale only: Safari grants the lock on a tap and again when the page comes back into view, but not after a reload, which it sometimes does by itself; APP-416 covers that. | F-40, F-42, F-45 |
| APP-802 | Rationale only: Wi-Fi round trips measured 29–34 ms at the 95th percentile. | F-41, F-47 |
| APP-816 | Rationale only: Safari trusts a private root limited to the Pi's name; one that also excluded IP addresses wasn't trusted. | F-38, F-44 |
| A-34 | Confirmed. | F-41, F-47 |

## Results

| Spike | Date | Result | Assumptions | Decision |
|-------|------|--------|-------------|----------|
| S0 | 4–5 Nov | Nearly done. BlueZ 5.82; controller powered, central role; spike tools install on the Pi and pass their tests. Boot: systemd startup 16.6 s (kernel 2.5 s, userspace 14.1 s), well inside APP-810's 90 s before the app's own start. Clock reported working; whether that was the cold test (10 min unplugged, no network) is being confirmed, because a secondary test found the Pi 5 clock stops while unplugged without the battery. ACT LED present, with `none`, `timer`, `heartbeat` and `default-on` among its triggers. Not yet run: LED written without root, LED seen through the case. | A-16 confirmed; A-29, A-36 open | — |
| S1 | 4 Nov | Pass, on the laptop. Control, ERG and resistance work; ERG held 200.0 ± 0.5 W. No cadence change happened (speed 26–29 km/h throughout), so ERG across cadences isn't shown; S2 covers it. The spike's decoder rejected every Indoor Bike Data record (F-1), so the live line showed no speed; fixed in spike-0.1.1. | A-5, A-24, A-30, A-32, A-38 confirmed; A-21 confirmed (from S1); A-37 not needed; A-25 partly checked; A-41 new | Decode Indoor Bike Data by its flags and ignore undeclared bytes. D-18 stands. |
| S2 | 6 Nov | Pass, on the Pi, 3 reps. T90 1.5 s, overshoot ≤ 6 %, targets written 0–1 ms after falling due; gear fine at 330 and 140 W. | A-12 refuted (faster); A-23, A-31, A-41 confirmed | Lead time default 1.5 s; no ERG smoothing in v1. |
| S2b | — | Deferred: the lead time is tuned on real workouts (OP-4). | A-12 refuted by S2 | Default 1.5 s. |
| S3 | 6 Nov | Pass on the retest: Success after a gentle approach. The first run (sprint to 44 km/h) ended in Error. | A-22 confirmed; A-25 spin-down codes confirmed | Spin-down stays *must*; the display guides a gentle approach. |
| S4 | 6 Nov | Partial. Strap recovered in 4.0 s. The trainer link was never cut; the restart after a crash failed. | A-39 refuted; A-33, A-44 open (Phase 5) | Release stale BlueZ links before connecting; ignore disconnects during connect. Retest in Phase 5. |
| S5 | 10 Nov | Pass: 75 min instead of 60, Wi-Fi on 5 GHz, with S8's page running alongside. Longest gap 0.49 s (trainer) and 0.98 s (strap), no unplanned disconnect; strap battery 80 % throughout, not compared with Garmin's. | A-40 confirmed on 5 GHz | The Pi stays on 5 GHz Wi-Fi; a 2.4 GHz network would need this check again. |
| S6 | 5 Nov | Pass. Ranges, ramps and free ride arrive marked and with their units; planned and library workouts share one structure; zone targets arrive as zone numbers. | A-27, A-35 confirmed; A-26 refuted for zones; A-42 new | Workouts are read from `workout_doc`, not the .zwo. APP-204/205 change proposed for zone targets. |
| S7 | 6 Nov | Partial, with `spike_fit.py`. Garmin Connect accepted the file and passed it on to intervals.icu. | A-10 confirmed; A-15 refuted; A-43 not needed; A-19, A-28 open (Phase 5) | Upload to intervals.icu becomes a setting. |
| S8 | 9–10 Nov | Pass after a change of root. The first root (name, and no IP addresses) wasn't trusted; one limited by name only is. Wake lock on tap; screen on for 22 min at the desk and 50 min while riding; the lock comes back without a tap when the page returns to view (8 of 8), never after a reload. Round trip at the 95th percentile 34 ms at the desk, 29 ms while riding. | A-17, A-34 confirmed | Root limited by name only. The display asks for a tap whenever it lacks the lock (APP-416). |

## Decisions made in Phase 2

1. Spikes ran on the Pi over SSH; S1's protocol results from the laptop stand. Spike logs (JSON Lines, UTC and monotonic ms) and the intervals.icu files are the first test fixtures (D-17).
2. Indoor Bike Data is decoded by its flags; bytes beyond the declared fields are ignored. The resistance field width follows the resistance range layout; Set Target Resistance Level sends 1 byte (F-1, A-37, A-38).
3. D-18 stands: power comes from Indoor Bike Data; Cycling Power carries the same value (F-4).
4. Status handling is idempotent: the D100 sends each status three times and repeats Stop Pedaling (F-9, F-30).
5. After taking control the app sends Start or Resume, and ignores the one Reset status that follows its own Request Control (F-26, F-29).
6. Lead time default 1.5 s; no ERG smoothing in v1 (F-25).
7. Before every connect the app releases any stale BlueZ link to that device, and it ignores disconnect reports during a connect or from an older client. bleak-retry-connector is a Phase 3 candidate for this (F-32, F-33).
8. Workouts are read from `workout_doc`; the .zwo download isn't used. Zone targets ride at the middle of intervals.icu's zone times the app's FTP (F-20, F-22).
9. FIT files are written with the official Garmin FIT Python SDK; Garmin Connect accepts them (F-35).
10. Uploading to intervals.icu becomes a setting; the Garmin import stays optional (F-35).
11. Spin-down works over FTMS when the rider eases up to the band without a sprint (F-37); it stays *must*.
12. Deferred with fallbacks: S2b lead-time tuning, the rest of S7 (A-19, A-28), the rest of S0, and the S4 retest (all Phase 5). S5 and S8, first deferred, ran on 9–10 Nov. See Closing Phase 2.
13. The changes to Phase 1 above are applied in Phase 1 revisions 4 and 5.
14. The Pi stays on 5 GHz Wi-Fi, where A-40 holds (F-46).
15. The display's private root is limited to the Pi's name, without excluding IP addresses; the server certificate lasts 365 days (F-38, F-44). Where the root's key lives is a Phase 3 choice.
16. The display requests the wake lock on a tap and again whenever the page comes back into view; while it lacks the lock during a ride or calibration, it asks for a tap (APP-416; F-40, F-45).

Phase 2 ended when every risk had a result or a recorded deferral. **Approved by Ferran on 8 Nov 2026**, together with the changes to Phase 1 (revision 4). **Closed on 10 Nov 2026** with revision 14 (S5 and S8) and Phase 1 revision 5, approved by Ferran.

## Open points

Everything Phase 2 leaves open, where it closes, and what happens if it goes wrong. None blocks Phase 3.

| # | Open point | Evidence so far | If it goes wrong | Closes in | Task |
|------|----------------------------------------------|--------------------------------|------------------------------|----------------|------|
| OP-1 | What the D100 does after a real link loss: keeps the last target or not (A-33). | Not tested: `bluetoothctl` never cut the link (F-31). | Nothing to change: the app re-sends the target after any reconnect (APP-318); only the dropout message wording depends on it. | Phase 5, reconnect slice | t35 |
| OP-2 | Reconnect and re-send within 10 s after a dropout (APP-805). | Connects on the Pi took 2.3–6.1 s; the strap came back in 4.0 s (F-31). | Tune scanning and retry timing in the reconnect slice. | Phase 5, reconnect slice | t35 |
| OP-3 | Restart after a crash: releasing the stale BlueZ link first (A-44). | Mechanism understood (F-33); bleak-retry-connector does the same release before every connect. | Unplug the trainer for 10 s. | Phase 5, reconnect slice | t35 |
| OP-4 | Lead time on real workouts (was S2b). | Default 1.5 s from 10 transitions (F-25). | It's a setting (APP-703). | Phase 5, tuning on real rides | t30 |
| OP-5 | One hour of Bluetooth with Wi-Fi active on the Pi (A-40; was S5). | **Closed 10 Nov:** 75 min on 5 GHz with no gap over 1 s (F-46). | On 2.4 GHz: a USB Bluetooth adapter with `dtoverlay=disable-bt`; Phase 3 keeps the adapter configurable. | Closed | t33 |
| OP-6 | Target power in the FIT file (A-28) and intervals.icu's load for our file (A-19). | Garmin Connect accepts our FIT file and passes it on (F-35). | Leave the target out of the file. | Phase 5, recording slice | t29 |
| OP-7 | Screen wake lock with a private root certificate (A-17) and the Wi-Fi round trip (A-34); was S8. | **Closed 10 Nov:** root trusted, lock held for 50 min, round trip 29–34 ms at the 95th percentile (F-41, F-44 to F-48). | Auto-Lock set to Never (APP-409). | Closed | t39, t41 |
| OP-8 | Clock after a cold start without network (A-29) and the LED without root (A-36); rest of S0. | Clock reported working on 5 Nov; LED triggers listed. | APP-824 warns either way; the LED (APP-826) is *could*. | Phase 5 | t17 |
| OP-9 | FTMS text for the procedure timeout (4.16.4) and split records (4.19); part of A-25. | No readable copy; the D100 never splits a record (F-3). | Phase 3 sets the timeout as an assumption and the simulator tests it. | When a copy is available | t19 |
| OP-10 | Meaning of the D100's undeclared bytes: 10 in Indoor Bike Data (F-2), 2 in spin-down Success (F-37). | Logged, not used. | No effect: the app doesn't use them. | Not planned | — |
| OP-11 | Own stale-link release and connect retry, or bleak-retry-connector 4.7.1. | Both do the same D-Bus release (F-32, F-33). | — | Phase 3, tech choices | — |

## Spike files

| File | Purpose |
|------|---------|
| `spikes/phase2/spike_trainer.py` | S1–S5: scan, contact, steps, spindown, ride |
| `spikes/phase2/ftms_codec.py` | Pure decoders and encoders, step plans |
| `spikes/phase2/bluez_release.py` | Releases a stale BlueZ link before connecting |
| `spikes/phase2/test_spikes.py` | 34 pytest tests, including real D100 records and a fake trainer that answers like FTMS |
| `spikes/phase2/spike_display.py`, `spike_display.html` | S8: HTTPS server on the Pi, a plain-HTTP port that serves the root and redirects, the test page (wake lock, round trips at 4 Hz, a beat every 5 s) and the PASS/FAIL report |
| `spikes/phase2/spike_certs.py` | S8: private root (name constraints `full`, `dns` or `none`) and a 365-day server certificate for `wow.local`, made with `openssl` |
| `spikes/phase2/test_display.py` | 30 pytest tests: statistics, the report, certificates checked with OpenSSL (a certificate for another name is refused), and both servers over real TLS |
| `spikes/phase2/spike_fit.py`, `test_fit.py` | Logs to one FIT activity (indoor cycling, 1 s records of power and heart rate, a lap per run and per S2 step), with the official Garmin FIT Python SDK |
| `spikes/phase2/pyproject.toml`, `uv.lock` | bleak 3.0.2, garmin-fit-sdk 21.221.0, tzdata 2026.6; pytest 9.2.0 and flake8 7.5.0 for development |

## Change log

| Rev. | Date | Change |
|------|------|--------|
| 1 | 4 Nov 2026 | Risk register, spikes S0–S8, run order. |
| 2 | 4 Nov 2026 | S0 partly done, S1 done: findings F-1 to F-16, A-37 not needed, A-38 confirmed, A-41 added, proposed changes to Phase 1. Spike tool 0.1.1: Indoor Bike Data decoded by flags, statuses reported once. |
| 3 | 5 Nov 2026 | t04 (no firmware update offered) and t05 done; S0 boot time recorded; clock result pending detail. |
| 4 | 5 Nov 2026 | S6 done: findings F-17 to F-24, A-26 refuted for zones, A-27 and A-35 confirmed, A-42 added, zone targets proposed for APP-204/205. |
| 5 | 5 Nov 2026 | S2 runs once, in the front ring Ferran rides; a second ring only if the first fails. Ferran confirmed the Staircase `3x` was a parsing issue. |
| 6 | 6 Nov 2026 | Closing plan proposed: exit with S2, S3 and a short S4; S2b, S5, S7, S8 and the rest of S0 deferred with fallbacks. Spike tool 0.1.2 adds `--reps`. |
| 7 | 6 Nov 2026 | `spike_fit.py` (spike 0.1.3): tonight's logs become one FIT activity, so A-10, A-15 and A-19 are checked tonight; only A-28 stays deferred. |
| 8 | 6 Nov 2026 | S2 done; S3, S4 and the FIT check with open points: findings F-25 to F-35, A-12 and A-15 refuted, A-23, A-31, A-41 and A-10 confirmed, A-43 and A-44 added, retest R1–R6 defined, more proposed Phase 1 changes. Spike 0.1.4: stale BlueZ links released before connecting, disconnects during connect ignored, `--drop-at` and `--crash-at`. |
| 9 | 6 Nov 2026 | F-31 evidence detailed (packets per 10 s through run A's 30 s); F-36 and A-42 confirmed from the repeat workout. |
| 10 | 6 Nov 2026 | Retest dropped: its points deferred to Phase 5 with evidence and fallbacks. Upload to intervals.icu becomes a setting (A-43 not needed); spin-down proposed as *should*. Decisions made and approval question. Ready for approval. |
| 11 | 6 Nov 2026 | Spin-down retest succeeded (F-37): A-22 confirmed, spin-down stays *must*, the downgrade proposal is withdrawn. |
| 12 | 8 Nov 2026 | Approved by Ferran. Open points section (OP-1 to OP-11); A-39, A-40, A-41 and A-44 rows brought up to date; changes to Phase 1 marked as applied in its revision 4. |
| 13 | 8 Nov 2026 | Risk matrix: severity scale, ratings before and after Phase 2, colour-coded grids in the PDF. The "after" note in the risk register brought up to date. |
| 13 | 8 Nov 2026 | Approved by Ferran, with the severity ratings. |
| 14 | 10 Nov 2026 | S8 (9–10 Nov) and S5 (10 Nov) done: findings F-38 to F-50; A-17, A-34 and A-40 (on 5 GHz) confirmed; R-08 and R-12 retired; OP-5 and OP-7 closed; facts checked for S8. Changes to Phase 1 revision 5: new APP-416; rationales of APP-409, APP-802 and APP-816; A-34. Spike 0.1.5 to 0.1.7 add `spike_display.py` and `spike_certs.py`. Closed and approved by Ferran. |

## Sources

- bleak changelog: https://bleak.readthedocs.io/en/stable/history.html
- bleak 3.0.2 on PyPI (source of the BlueZ backend and `bleak/args/bluez.py`): https://pypi.org/project/bleak/3.0.2/
- BlueZ issue 89, devices stay connected after the client exits (cited in bleak's BlueZ backend): https://github.com/bluez/bluez/issues/89
- Bluetooth SIG GSS YAML (Indoor Bike Data, Cycling Power Measurement, Heart Rate Measurement), from the verbatim copies in bluetooth-sig 0.6.0: https://pypi.org/project/bluetooth-sig/
- pyftms 0.4.15 (secondary): https://pypi.org/project/pyftms/
- Gigazine, Raspberry Pi 5 RTC test (secondary): https://gigazine.net/gsc_news/en/20231109-raspberry-pi-5-rtc
- intervals.icu forum, false duplicates on Dropbox sync (content hash, developer, 31 Jul 2021): https://forum.intervals.icu/t/syncing-from-dropbox-not-all-file-synced-false-duplicate/4458
- Raspberry Pi firmware-nonfree issue 33, Wi-Fi and Bluetooth interference: https://github.com/RPi-Distro/firmware-nonfree/issues/33
- uv installation: https://docs.astral.sh/uv/getting-started/installation/
- Garmin FIT Python SDK: https://pypi.org/project/garmin-fit-sdk/
- Garmin, FIT Activity file (required messages and fields): https://developer.garmin.com/fit/articles/file-types/activity.html
- bleak-retry-connector 4.7.1 (`close_stale_connections`): https://pypi.org/project/bleak-retry-connector/ and https://github.com/Bluetooth-Devices/bleak-retry-connector/commit/85a3efe1589dc48eb009da7c3aaa69d7decfe26d
- Decathlon support, Van Rysel D100 (calibration in Onelap Fit, about every two weeks): https://support.decathlon.co.uk/van-rysel-d100-zwift-edition
- Garmin, Encoding FIT Activity files: https://developer.garmin.com/fit/articles/cookbook/encoding_activity_files.html
- DC Rainmaker, Van Rysel D100 review: https://dcrainmaker.com/2025/02/decathlon-van-rysel-d100-smart-trainer-review.html
- Phase 0 record, revision 2: `claude/phase0-discovery.md`
- Apple, Requirements for trusted certificates in iOS 13 and macOS 10.15: https://support.apple.com/en-us/103769
- Apple, Trust manually installed certificate profiles in iOS: https://support.apple.com/en-ca/102390
- Apple Developer Forums, certificate lifetime limits and private roots (Apple DTS): https://developer.apple.com/forums/thread/773796
- CA/Browser Forum server certificate working group, Apple on critical name constraints (Feb 2020): https://archive.cabforum.org/pipermail/servercert-wg/2020-February/001684.html
- caniuse, Screen Wake Lock API: https://caniuse.com/wake-lock
- Chrome for Developers, Stay awake with the Screen Wake Lock API: https://developer.chrome.com/articles/wake-lock/
- Phase 1 requirements, revision 5: `claude/phase1-requirements.md`
