# Phase 0 — Discovery record

**Status:** approved by Ferran, 3 Nov 2026 (revision 2). Probe results are in. Revision 2 adds the HRM battery warning (D-19), spin-down calibration in v1 (D-20), the Zwift Cog and the Pi hardware received. Items still open don't block Phase 1 and are listed at the end.

## Context

A personal app that runs structured ERG workouts (30/30s, sweet-spot blocks with ~130 % FTP surges) on the rider's smart trainer, without a paid subscription. One rider in v1. Reliability matters more than looks.

## Equipment

| Role | Item | Interface | Known limits |
|----------|--------------------------|------------------------|------------------------------------------|
| Trainer | Van Rysel D100 (Decathlon, bought Oct 2025, CH). Firmware 0.108, build dated 7 Jan 2025. Fitted with a Zwift Cog. | Bluetooth only: Fitness Machine (FTMS), Cycling Power, a Zwift protocol service, a TI firmware-update service. No ANT+. | One Bluetooth connection at a time. Power targets 50–600 W in 1 W steps (A-20). Incline 0–6 %, no descents. Cadence not supported. ±5 % claimed, ~3 % measured by BikeRadar. Data at 1 Hz. One rear cog: no rear shifting, so high and low ERG targets must be reachable in a single gear (A-23). |
| Heart rate | Garmin HRM 200 | Bluetooth (Heart Rate, Battery) and ANT+ | Up to 3 Bluetooth connections at once (Wareable). Reports battery level (A-21). |
| Cadence | None yet | Bluetooth sensor later | — |
| v1 host | Raspberry Pi 5 with official case, 27 W supply and microSD card (received 3 Nov), Raspberry Pi OS Trixie | Built-in Bluetooth 5.0 / BLE, Wi-Fi | BlueZ 5.82 in Trixie; bleak needs ≥ 5.55. |
| Dev and spikes | Windows laptop, native Python with uv | Built-in Bluetooth | bleak 3.0.2 needs Windows 11 build ≥ 22000. WSL is not used. |
| Display | iPhone, Safari | Home Wi-Fi | Screen wake lock only on HTTPS pages. |

## Probe results (3 Nov 2026, nRF Connect on iPhone)

Bit meanings are from FTMS v1.0, Tables 3.2, 3.3, 4.3 and 4.4. All values are little-endian.

### Van Rysel D100 (`VANRYSEL-HT-9d5d`)

| Item | Raw | Meaning |
|------------------------------|-------------------------|---------------------------------------------|
| Advertising, FTMS service data | `01 20 00` | Flags bit 0: machine available. Type 0x0020, bit 5: indoor bike. |
| Fitness Machine Features (0x2ACC, first 4 bytes) | `01 40 00 00` = 0x00004001 | Bit 0: average speed. Bit 14: power measurement. Bit 1 (cadence) is **not** set. |
| Target Setting Features (0x2ACC, last 4 bytes) | `0C A0 00 00` = 0x0000A00C | Bit 2: resistance target. Bit 3: **power target (ERG)**. Bit 13: indoor bike simulation (slope). Bit 15: spin-down control. Bit 1 (inclination target) is not set. |
| Supported Power Range (0x2AD8) | `32 00 58 02 01 00` | 50 to 600 W, 1 W steps (A-20). |
| Supported Inclination Range (0x2AD5) | `00 00 3C 00 01 00` | 0 to 6.0 %, 0.1 % steps (A-20). |
| Supported Resistance Level Range (0x2AD6) | `00 00 64 00 01 00` | 0 to 100, steps of 1; unit not yet confirmed (A-20). |
| Fitness Machine Control Point (0x2AD9) | write, write without response, indicate | Present. |
| Indoor Bike Data (0x2AD2) | notify | Present; not captured yet. |
| Cycling Power (0x1818) | Measurement 0x2A63 notify; Feature 0x2A65 = `FF 1F 00 00`; Sensor Location 0x2A5D = `0C` | A second power source. The feature value claims many optional features at once; not decoded. |
| Other services | `00000001-19CA-4651-86E5-FA29DCDD09D1`; TI Over-the-Air Download | Zwift protocol and firmware update. Not used. |

### Garmin HRM 200 (`HRM200:739158`)

| Item | Meaning |
|-----------------------------------|-----------------------------------------------------------------|
| Advertising | Heart Rate (0x180D), Garmin manufacturer data. |
| Heart Rate (0x180D) | Heart Rate Measurement (0x2A37), notify. |
| Battery (0x180F) | Battery Level (0x2A19), read and notify. nRF Connect showed `80` (A-21). |
| Device Information | Garmin, model 4606, hardware A. |
| Garmin service `6A4E2800-667B-11E3-949A-0800200C9A66` | Proprietary. Not used. |

## Decisions

| ID | Decision | From |
|------|----------------------------------------------------------------------|------------------------|
| D-01 | v1 is Python (uv, pinned versions) and runs on a Raspberry Pi 5 near the trainer. The Windows laptop is for development and spikes only; WSL is not used. | Batch 2 Q1, batch 3 Q1, batch 4 Q1; A-3 |
| D-02 | The iPhone is the only display, through Safari over home Wi-Fi. | Batch 2 Q1 |
| D-03 | The Pi serves the page over HTTPS with a root certificate the iPhone trusts, so the page can keep the screen awake. Fallback: Auto-Lock set to Never. | Batch 3 Q2; A-14, A-17 |
| D-04 | Trainer control uses standard FTMS only: no Zwift protocol, no ANT+. | Batch 4 Q3; probe |
| D-05 | The trainer's cadence is ignored. Cadence comes from a separate Bluetooth sensor once one is added. | Batch 1 Q2; A-7 |
| D-06 | Heart rate from the HRM 200 is shown live and recorded. It is not used for control. | Batch 1 Q2; A-8 |
| D-07 | Workouts come from intervals.icu planned workouts through its API. Targets are applied with the app's FTP. | Batch 1 Q5, batch 3 Q5 |
| D-08 | FTP and zones are set in the app. | Batch 3 Q5 |
| D-09 | One FIT file per ride: power and heart rate every second, target power, one lap per workout step, marked as indoor cycling; cadence when a sensor exists. Plus a raw log of all Bluetooth traffic. | Batch 2 Q2 |
| D-10 | The app uploads the FIT file to intervals.icu through the official endpoint. The rider imports the same file into Garmin Connect by hand. | Batch 2 Q3; A-10, A-11, A-15 |
| D-11 | ERG transitions: each new target is sent early by a lead time measured in Phase 2. A workout can switch a block to resistance mode instead. | Batch 2 Q4; A-12; probe (resistance target supported) |
| D-12 | Trainer dropout: the workout clock keeps running, the app reconnects on its own and re-sends the current target, and the file marks the gap. A heart-rate dropout only leaves a gap. | Batch 2 Q5 |
| D-13 | Phone controls: choose today's planned workout and start it, pause and resume, skip a step, intensity ±5 %, switch the current block between ERG and resistance mode. Large touch targets. | Batch 3 Q3 |
| D-14 | Free ride with a manual watt target or resistance level, recorded the same way (should). | Batch 3 Q4 |
| D-15 | Per ride the app computes NP, IF, TSS, work in kJ and time in each zone. Fitness and fatigue over weeks stay in intervals.icu, which sees every ride. | Batch 3 Q5, batch 4 Q2; A-18, A-19 |
| D-16 | One rider in v1. | Batch 3 Q5 |
| D-17 | Test inputs and expected outputs are kept as language-neutral data files (workout files, recorded trainer messages, expected target timelines, expected ride metrics) so a JavaScript v2 can be checked against the same set. | Batch 4 Q3 |
| D-18 | Power is read from FTMS Indoor Bike Data. The Cycling Power service is used only if Phase 2 shows Indoor Bike Data is unreliable. | Probe; A-6 refuted |
| D-19 | The app shows the HRM 200's battery level and warns the rider when it is low, replacing the warning the Garmin bike computer gives outdoors. The threshold is set in Phase 1. | Rider, 3 Nov; probe (Battery Service); A-21 |
| D-20 | v1 can run a spin-down calibration on the D100 through FTMS and shows the result. | Rider, 3 Nov; probe (Target Setting Features bit 15); A-22 |

## Later, not in v1

Candidates for the Phase 1 out-of-scope list.

- A JavaScript v2 to share with friends: other trainers, several riders.
- Simulated speed, distance and altitude; slope mode with routes. The D100 supports slope through simulation parameters (0–6 %, no descents).
- Virtual shifting. The Zwift Cog has one rear cog; Zwift adds virtual gears, most other apps don't. ERG doesn't need shifting.
- Automatic upload to Garmin Connect. There is no official write API for individuals (A-11).
- ANT+.
- Fitness and fatigue tracking in the app.

## Assumptions

| ID | Assumption | Status | Source | How it gets checked |
|------|--------------------------------|----------|---------------------------|-------------------------|
| A-1 | The 16-bit UUIDs used (FTMS 0x1826 and its characteristics, Cycling Power 0x1818, Speed and Cadence 0x1816, Heart Rate 0x180D) are the SIG-assigned ones. | Confirmed | nRF Connect (Nordic) named each one on both devices | 0x1816 once a cadence sensor exists |
| A-2 | Tacx FE-C over BLE and legacy Wahoo UUIDs are correct. | Not needed | Community forums | The D100 uses neither |
| A-3 | WSL2 has no Bluetooth without a custom kernel and usbipd. | Confirmed | Espressif ESP-Matter docs | Led to D-01 |
| A-4 | intervals.icu serves planned workouts as .zwo, .fit, .mrc or .erg. | Confirmed | intervals.icu forum | Phase 2 API spike |
| A-5 | The D100 accepts a target power through the FTMS control point. | Confirmed | Probe: control point present, Target Setting Features bit 3 set | Phase 2 sends a real target |
| A-6 | The D100 has no separate Cycling Power service. | Refuted | Probe: Cycling Power 0x1818 present | Led to D-18 |
| A-7 | The D100's cadence is unusable. | Confirmed | Probe: Fitness Machine Features bit 1 not set; spec sheet; reviews | Led to D-05 |
| A-8 | The HRM 200 exposes the standard Heart Rate service and allows up to 3 Bluetooth connections. | Confirmed | Probe (service); Wareable (connections) | — |
| A-9 | The strap is a Garmin HRM 200. | Confirmed | Rider, 30 Oct; probe | — |
| A-10 | Garmin Connect's Import Data accepts our FIT file and keeps power, heart rate and laps. | Open | FulGaz help article | Phase 2: import a test file |
| A-11 | Individuals can't push activities into Garmin Connect through an official API. | Open | the5krunner, 22 Oct 2026 | Garmin developer documentation |
| A-12 | The D100 settles on a new ERG target in about 3 s and reports at 1 Hz. | Open | DC Rainmaker, BikeRadar | Phase 2 step-response spike |
| A-13 | The laptop runs Windows 11 build ≥ 22000. | Open | bleak documentation | `winver` |
| A-14 | Safari won't keep the screen awake for a plain-HTTP page. | Open | MDN, caniuse | Phase 2 spike |
| A-15 | A FIT file imported into Garmin Connect is not passed on to intervals.icu. | Open | intervals.icu forum (developer 2021, user 2022) | Phase 2: import one file, watch intervals.icu |
| A-16 | Raspberry Pi OS Trixie ships BlueZ 5.82 (bleak needs ≥ 5.55). | Open | Raspberry Pi archive listing | `bluetoothctl --version` on the Pi |
| A-17 | With a fully trusted root certificate, Safari treats the Pi's HTTPS page as secure and grants the wake lock. | Open | Apple support 102390, MDN | Phase 2 spike |
| A-18 | NP is the fourth root of the mean of the fourth powers of 30 s rolling-average power. | Open | intervals.icu forum user post | Primary source before Phase 1 |
| A-19 | intervals.icu computes its own load for an uploaded ride with its own FTP. | Open | intervals.icu forum user post | Phase 2 upload spike |
| A-20 | The range characteristics are minimum, maximum (sint16) and step (uint16), giving power 50–600 W, incline 0–6.0 %, resistance 0–100. | Open | GATT Specification Supplement (little-endian default); matches DC Rainmaker's 600 W and 6 % | FTMS sections 4.12–4.14 before Phase 1 uses them |
| A-21 | The HRM 200's Battery Level is a percentage from 0 to 100. nRF Connect showed `80`; if that is hexadecimal it means 128, which is out of range. | Open | Battery Level as uint8 percent (Hubble guide, secondary) | Phase 2: read it with the probe script and compare with what the Garmin computer shows |
| A-22 | The D100 runs a spin-down through the FTMS control point and reports progress and result through Fitness Machine Status (0x2ADA). | Open | Probe: Target Setting Features bit 15 set. The op codes and 0x2ADA were not checked: the FTMS copy is truncated and the screenshots cut off after 0x2AD9. | Claude confirms the procedure from FTMS 4.16–4.17; Phase 2 runs one spin-down and compares with Onelap |
| A-23 | With the Zwift Cog, the D100 holds both ~330 W and ~140 W ERG targets at normal cadence in one gear. | Open | DC Rainmaker needed a gear change above ~350 W in ERG; smartbiketrainers.com reports ERG works with the Cog in other apps | Phase 2 ERG spike at both targets, in each chainring if the bike has two |

## Still open, not blocking Phase 1

- Check the laptop's Windows version (A-13).
- Update the D100 firmware in the Onelap app if an update is offered, then run one spin-down there as a reference for D-20.
- Set up the Raspberry Pi (A-16).
- Get a full copy of FTMS sections 4.12–4.17 (A-20, A-22).

## Sources

- Bluetooth SIG, Fitness Machine Service v1.0 (Tables 3.2, 3.3, 4.2–4.4): https://community.appinventor.mit.edu/uploads/short-url/yTLhgjXECIekyCgPg0GOBz1k4Bh.pdf
- Bluetooth SIG, Fitness Machine Service 1.0 page: https://www.bluetooth.com/specifications/specs/fitness-machine-service-1-0/
- Bluetooth SIG, GATT Specification Supplement (2025-01-15): https://viys.github.io/viys/docs/GATT_Specification_Supplement.pdf
- DC Rainmaker, Van Rysel D100 review: https://dcrainmaker.com/2025/02/decathlon-van-rysel-d100-smart-trainer-review.html
- BikeRadar, Van Rysel D100 review: https://www.bikeradar.com/van-rysel-d100-home-trainer-with-zwift-cog-and-click-review
- Wareable, Garmin HRM 200 review: https://www.wareable.com/fitness-trackers/garmin-hrm-200-review
- bleak on PyPI: https://pypi.org/project/bleak/
- Espressif, CHIP Tool in WSL2: https://docs.espressif.com/projects/esp-matter/en/latest/esp32/using_chip_tool.html
- Raspberry Pi OS Trixie bluez package: https://aptpeek.dev/raspberrypi/trixie/main/arm64/bluez/5.82-1.1+rpt2
- intervals.icu, downloading planned workouts: https://forum.intervals.icu/t/downloading-planned-workouts-from-the-api/93737
- intervals.icu, API integration cookbook: https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090
- intervals.icu, virtual rides not syncing from Garmin: https://forum.intervals.icu/t/virtual-rides-not-syncing-from-garmin/3689
- the5krunner, Garmin personal API: https://the5krunner.com/2026/10/22/garmin-personal-api/
- FulGaz, uploading rides to Garmin Connect: https://feedback.fulgaz.com/help/articles/360020004431-uploading-fulgaz-rides-to-garmin-connect
- GPX 1.1 schema: https://www.topografix.com/GPX/1/1
- garmin-fit-sdk on PyPI: https://pypi.org/project/garmin-fit-sdk/
- MDN, WakeLock.request(): https://developer.mozilla.org/docs/Web/API/WakeLock/request
- caniuse, Screen Wake Lock: https://caniuse.com/wake-lock
- Apple support 102390, trusting installed root certificates: https://support.apple.com/en-ca/102390
- TrainingPeaks, estimating TSS: https://www.trainingpeaks.com/learn/articles/estimating-training-stress-score-tss/
- Smart Bike Trainers, Zwift Cog compatibility: https://www.smartbiketrainers.com/zwift-cog-compatibility-explained-28030
- Hubble, Battery Level over BLE: https://hubble.com/community/guides/how-to-read-and-transmit-battery-level-over-ble-from-your-iot-device/
