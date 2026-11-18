# Phase 1 — Requirements

**Status:** approved, revision 8, 18 Nov 2026. Revision 8 applies the changes Ferran approved during Phase 5 (Phase 5 sections 13.6, 35.5, 41.5 and 47.5, marked P5): the lead time default of 1.0 s and the zone range in table S, and the route requirements of SL-13 and SL-14: UC-09, APP-613, APP-709 and APP-901 to APP-910 (APP-903 as changed with SL-14), the rider's weight in table S, simulated speed, distance and altitude taken off the later-versions list, and slope mode as the first V2 to-do. Revision 7 applied the changes Ferran approved with the Phase 4 findings on 11 Nov 2026 (APP-317, APP-825, rationales of APP-302 and APP-405). Revision 6 applied the changes approved with Phase 3 on 11 Nov 2026 (APP-211, APP-301, APP-802, APP-822, APP-823, new APP-830, landscape in the later-versions list). Revision 5 applied the changes from Phase 2's last spikes (S5 and S8), approved when Phase 2 closed on 10 Nov 2026; revision 4 applied the earlier Phase 2 changes (8 Nov 2026); revision 3 was approved on 3 Nov 2026. Builds on the Phase 0 record, revision 2 (approved 3 Nov 2026).

## How to read this

- **The system** is the app on the Raspberry Pi together with its page in Safari on the iPhone. **The display** is that page.
- **EARS patterns:** "The system shall…" (always), "When…" (event), "While…" (state), "If…, then…" (unwanted event), "Where…" (optional feature).
- **Priority:** *must*: v1 is not usable for weekly training without it. *should*: in v1 unless it puts a *must* at risk. *could*: only if time is left.
- **Verification:** **T** test, automated with pytest against the simulated trainer and heart-rate monitor or recorded data. **I** inspection of code, files or the display. **D** demonstration on the real trainer, strap, Pi and iPhone. What the display shows is verified by looking at it on the iPhone, as D or I; no automated display test is required (Ferran, 11 Nov 2026). The Phase 4 test plan has the checks.
- **Traces:** the use case, then the Phase 0 decision (D-xx), assumption (A-xx) or Phase 2 finding (F-xx) behind it. **P1** marks a choice first proposed in this document; check those first. **P3** marks a change made with Phase 3, **P4** one made with Phase 4, **P5** one made with Phase 5.
- **Level of detail:** requirements name the FTMS procedures and characteristics they rely on. Byte layouts, op codes and message sequences are in the Phase 3 Interface Control Document, so the requirements don't repeat or freeze the protocol.

## Checks closed before writing

| ID | Result | Source |
|------|----------------------------------------------------------------|------------------------------|
| A-18 | **Confirmed.** NP: 30 s rolling average of power, each value to the 4th power, the mean of those, then the 4th root. How the first 30 s, gaps and pauses are handled is not specified there; table M sets our rules. | TrainingPeaks, owner of the NP definition |
| A-20 | **Confirmed for power and incline.** Supported Power Range is sint16 minimum, sint16 maximum, uint16 increment, in W: the D100 gives 50–600 W in 1 W steps. Supported Inclination Range is the same layout in 0.1 %: 0–6.0 % in 0.1 % steps. **Resistance:** the current SIG definition is three uint8 fields (3 bytes), but the D100 sends 6 bytes, which matches the older FTMS 1.0 layout of sint16, sint16, uint16 in steps of 0.1 (as pyftms decodes it). The raw values 0–100 in steps of 1 stand. FTMS sends resistance targets as a unitless UINT8 with a resolution of 0.1, so a level has no physical meaning across trainers. The requirements therefore show resistance as a percentage of the trainer's range, and the physical unit no longer matters. | SIG GSS YAML; FTMS 1.0.1 Table 4.15; pyftms |
| A-21 | **Format confirmed:** Battery Level is a uint8 percentage from 0 to 100; the SIG reserves every other value. **Still open:** what the HRM 200 actually sends (`80` in nRF Connect). | SIG GSS YAML |
| A-22 | **Still open.** The FTMS 1.0.1 text available to me ends in Table 4.15, before the spin-down procedure (4.16.2.20) and Fitness Machine Status (4.17). The details come from pyftms for now (A-25). APP-501 to APP-506 hold either way. | FTMS 1.0.1; pyftms |

## Terms

| Term | Meaning |
|------------------|----------------------------------------------------------------------|
| Ride | One session from the first pedal stroke after Start to Finish, with or without a workout. One ride gives one FIT file. |
| Ride time | Time since the first pedal stroke after Start, without paused time. It keeps running through dropouts (D-12). It is the FIT timer time. |
| Step | One line of a workout: a duration and a target. |
| Block | A repeat set and the steps in it; a step outside any repeat set is a block of its own. |
| ERG mode | The trainer holds a target power (FTMS Set Target Power). |
| Resistance mode | The trainer holds a resistance level (FTMS Set Target Resistance Level); power then depends on the rider. Levels are shown as 0–100 % of the trainer's supported range. |
| Free-ride level | The resistance level used for free-ride steps and after the workout ends (APP-705, table S). |
| Intensity | A factor on every ERG target, 100 % at Start (D-13). |
| Lead time | How early the next ERG target is sent before a step boundary (D-11). |
| Dropout | A lost link, or no data from a connected device for 3 s. |
| Route | A GPX file in the Pi's `routes` folder that a ride can follow (UC-09). The route gives the ride its speed, distance, altitude and position; it never changes the trainer's control. |

## Screens

Requirements refer to these screens by name. Phase 3 designed their layouts; screens the rider builds himself are in the later-versions list.

| Screen | Purpose |
|------------------|----------------------------------------------------------------------|
| Home | Shown whenever no ride or calibration runs: today's planned workouts, the intervals.icu library, the built-in workouts, free ride, calibration, ride history and settings. |
| Pre-ride | Opens when the rider picks a workout or free ride: the states of the trainer and heart-rate monitor, the strap's battery, the workout preview with the mode of each block, the route (APP-902), and Start. |
| Ride, ERG | The ride screen while the current step runs in ERG mode (APP-401). |
| Ride, resistance | The ride screen while the current step runs in resistance mode (APP-414). |
| Ride, route | The route view of the ride screen during a ride on a route (APP-909). |
| Summary | After Finish (APP-411), with the route's distance and climb on a ride on a route (APP-906). |
| Ride history | Past rides, FIT download and upload state (APP-610, APP-611). |
| Calibration | The spin-down (APP-501 to APP-504). |
| Settings | Table S, device choice (APP-114) and the intervals.icu account (APP-706). |

## Use cases

| ID | Use case | Outline |
|-------|---------------------------------|----------------------------------------------------------|
| UC-01 | Ride a planned workout | The rider opens the page, picks today's workout, a library workout or a built-in one, checks device status and the preview on the Pre-ride screen, and starts. The system runs each step on the trainer, shows live data, records the ride, and ends when the rider finishes. |
| UC-02 | Adjust a ride in progress | Pause and resume, skip a step, intensity ±5 %, switch the current block between ERG and resistance mode, change the resistance level. |
| UC-03 | Free ride | Ride without a workout at a chosen target power or resistance level, recorded the same way. |
| UC-04 | Calibrate the trainer | Run a spin-down from the Home screen and see whether it succeeded. |
| UC-05 | Keep and share a ride | See the ride summary; where upload is on, the system uploads the ride to intervals.icu; the rider can download the FIT file to import into Garmin Connect; past rides are listed. |
| UC-06 | Set up the rider and equipment | FTP, zones, lead time, battery threshold, the rider's weight for routes, upload to intervals.icu on or off, intervals.icu account, choice of trainer and strap. |
| UC-07 | Recover from faults | Trainer or strap dropout, phone disconnect or loss, Pi off the network, app crash or power cut during a ride. |
| UC-08 | Develop and verify without hardware | Simulated devices, replay of recorded Bluetooth logs, shared test data for a later JavaScript version. |
| UC-09 | Ride along a route | The rider copies GPX files to the Pi and picks one on Pre-ride; the ride runs as usual. During the ride the ride screen can switch to a route view: a drawing of the route, its elevation profile, the speed and the grade at the rider's place. The ride's FIT file and Summary carry the speed, distance, altitude and position of a ride along that route. The trainer is controlled exactly as without a route (P5). |

## Requirements

### 1 Devices and connection

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-101 | The system shall control the trainer through the Bluetooth Fitness Machine Service (FTMS). | FTMS is the Bluetooth SIG's standard trainer interface, so the trainer code stays portable (D-04). ANT+ and the Zwift protocol are listed under Not planned; this requirement doesn't forbid anything. | must | I | UC-01, UC-03, UC-04; D-04 |
| APP-102 | When the Pre-ride screen opens, the system shall connect to the configured trainer and heart-rate monitor and show the state of each: searching, connected or not found. | Connection problems show before Start, not during the first interval. | must | T, D | UC-01, UC-03; P1 |
| APP-103 | When the system connects to a trainer, the system shall read its Fitness Machine Feature and supported power, resistance and inclination ranges, and hide the modes the trainer doesn't declare. | Targets have to stay inside what the trainer accepts, and ranges differ between trainers. | must | T | UC-01; D-04, A-20 |
| APP-104 | When the system connects to the trainer, the system shall request control through the Fitness Machine Control Point before it sends any target. | FTMS provides Request Control (op code 0x00) for this. | must | T, D | UC-01; D-04 |
| APP-105 | If the trainer reports a reset or the loss of control, or answers a command with Control Not Permitted, then the system shall request control again and re-send the current target and mode; the one reset the trainer reports right after granting a Request Control doesn't count. While the trainer refuses control, the system shall show this and repeat the request every 2 s for as long as the ride runs. | A trainer reset or another app can take control during a ride. Retrying until the ride ends costs nothing; giving up would leave the rider without targets. The D100 reports one reset after every granted Request Control (Phase 2, F-29); treating it as a new reset would loop. | must | T | UC-07; D-12, A-25, A-41 |
| APP-106 | While a control point procedure is pending, the system shall send no other control point command, and shall replace any waiting target with the most recent one that falls due, to send once the procedure completes. | FTMS answers each procedure with its own indication (response op code 0x80). Queued old targets would delay the current one. | must | T | UC-01; P1, A-25 |
| APP-107 | If the trainer does not answer a control point write within 3 s, then the system shall show that the trainer is not responding and log it; after the FTMS procedure timeout it shall treat the procedure as failed and re-send the current target, for as long as the ride runs. | A silent trainer must not leave the rider on a stale target without knowing. A refusal is APP-105; a lost link is APP-318. | must | T | UC-07; D-12, A-25 |
| APP-108 | The system shall read power from the Indoor Bike Data characteristic, decoding each notification according to its flags, ignoring any bytes beyond the fields the flags declare, and joining the parts of a data record that the trainer sends in several notifications. | Fields are present or absent according to the flags, and FTMS 4.1 splits a record longer than the ATT MTU over several notifications. The D100 appends 10 bytes its flags don't declare (Phase 2, F-1). | must | T | UC-01; D-18, A-25, F-1 |
| APP-109 | If the trainer doesn't declare Cadence Supported in its Fitness Machine Feature, then the system shall disregard any cadence the trainer reports. | The D100 declares no cadence (probe: feature bit 1 is 0). A trainer that does declare it can still provide cadence (APP-115). | must | T | UC-01; D-05, A-7 |
| APP-110 | When 10 minutes pass with no ride, calibration or Pre-ride screen open, the system shall disconnect from the trainer. | The D100 takes one Bluetooth connection at a time. Releasing it lets the Onelap app connect for firmware updates and the reference spin-down. | should | T | UC-06; P1 |
| APP-111 | When the system connects to the heart-rate monitor, the system shall subscribe to Heart Rate Measurement and read and subscribe to Battery Level. | Live heart rate and the battery warning. | must | T, D | UC-01; D-06, D-19 |
| APP-112 | If the heart-rate monitor's battery level is at or below the warning threshold (APP-704), then the system shall show a warning on the Pre-ride screen and a warning indicator on both ride screens. | Replaces the low-battery warning the Garmin bike computer gives outdoors. | must | T, D | UC-01; D-19, A-21 |
| APP-113 | If the heart-rate monitor reports a battery level outside 0–100, then the system shall show the battery as unknown and log the raw value. | The SIG reserves every value outside 0–100. | should | T | UC-01; A-21 |
| APP-114 | When the rider asks to choose a device, the system shall scan and list the nearby devices that advertise the Fitness Machine (0x1826), Heart Rate (0x180D) or Cycling Speed and Cadence (0x1816) service, hide every other Bluetooth device, and remember the device the rider chooses. | Setup or a replaced device without editing files on the Pi; TVs, phones and headphones stay out of the list. | should | T, D | UC-06; P1, A-32 |
| APP-115 | Where a cadence source is configured (a Bluetooth cadence sensor, or a trainer that declares Cadence Supported), the system shall show and record cadence, using the sensor when both are available. | Cadence comes from a separate sensor once one is bought; a crank sensor measures it directly. | could | D | UC-01; D-05, D-09 |
| APP-116 | If the heart-rate monitor is not connected when the rider starts a ride, then the system shall start the ride and show heart rate as missing. | A dead strap shouldn't cancel a session; heart rate isn't used for control. | should | T | UC-01; D-06 |
| APP-117 | If the rider starts a ride while the trainer is not connected, then the system shall not start it and shall show that the trainer is missing. | A ride without the trainer has no targets and no power. | must | T | UC-01, UC-03; P1 |

### 2 Workouts

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-201 | When the Home screen opens, the system shall list the planned cycling workouts for the current local day from intervals.icu. | Workouts are planned in intervals.icu. | must | T, D | UC-01; D-07, A-4 |
| APP-202 | If intervals.icu can't be reached when the Home screen opens, then the system shall list the planned and library workouts from its last download, which covers the next 7 days of the plan and the whole library, and show when that download happened. | A web or Wi-Fi outage shouldn't cancel a session. | should | T | UC-01, UC-07; P1 |
| APP-203 | When the rider selects a workout, the system shall show a preview with its steps, each target in watts at the app's FTP, and the total duration. | Lets the rider check targets before starting and choose blocks for resistance mode (APP-207). | must | T, D | UC-01; D-07, D-08 |
| APP-204 | The system shall run workout steps whose target is a percentage of FTP, absolute watts, a power zone, a range of either, a ramp between two values, or free ride, and shall run repeat blocks. | These cover the rider's sessions: 30/30s, sweet spot with surges, warm-up ramps, Z2 rides. intervals.icu supports all of them and sends repeat blocks nested (Phase 2, F-36). | must | T | UC-01; D-07, A-4, A-26, A-42 |
| APP-205 | The system shall use the midpoint of a step's power range as the step's target; for a power-zone target, the midpoint of that zone as intervals.icu defines it for the workout, in percent of FTP, applied to the app's FTP; and shall treat a step as a ramp when the workout marks it as one (APP-305). A zone without an upper bound is a target the system can't apply (APP-206). | ERG needs one number. intervals.icu rides ranges at their midpoint too (Phase 2, F-19), marks ramps apart from ranges (F-18) and sends zone targets as zone numbers together with the workout's zone bounds (F-20); its 7 zones can differ from the app's (APP-702). | must | T | UC-01; P1, A-26, F-18 to F-20 |
| APP-206 | If a workout contains a step whose target the system can't apply, such as heart rate or pace, then the system shall mark the step in the preview and run it in resistance mode at the free-ride level. | Heart rate isn't used for control; the rider sees this before starting. | must | T | UC-01; D-06, P1 |
| APP-207 | While a workout preview is shown, the system shall let the rider set any block to run in resistance mode instead of ERG. | D-11 lets a workout run a block in resistance mode. intervals.icu can express this only as free ride, which drops the targets. | should | T, D | UC-01; D-11 |
| APP-208 | The system shall store the workout as downloaded, and the FTP used, with each ride's files. | Lets a ride be reproduced and turned into a test case. | should | I | UC-05, UC-08; D-17 |
| APP-209 | While a step that has a text cue is running, the display shall show the cue. | intervals.icu steps can carry text cues. | could | D | UC-01; P1 |
| APP-210 | When the Home screen opens, the system shall also list the workouts in the rider's intervals.icu workout library. | A workout worth repeating is saved once in the intervals.icu library and ridden from there without planning it. A second library inside the app would duplicate that. | should | T, D | UC-01; P1, A-35 |
| APP-211 | The system shall offer built-in workouts stored on the Pi, including a ramp FTP test, next to the intervals.icu workouts. | A test works without intervals.icu or the network. The ramp protocol is the one Ferran defined on 11 Nov 2026 (15 min warm-up, 1-minute steps from 120 W in 20 W steps, 5 min free-ride cool-down), fixed in the ICD, IF-13. | should | T, D | UC-01; P1, P3 |

### 3 Running a ride

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-301 | When the rider presses Start, the system shall send the first step's target to the trainer and show that it is waiting for pedaling; when the trainer first reports a power above 0 W, the system shall start the ride clock and the recording. | The trainer holds the right load before the first stroke, and the ride and its file begin with the first stroke, not with clipping in; the first step keeps its full length (Ferran, 11 Nov 2026). | must | T, D | UC-01, UC-03; D-07, D-09, P3, A-60 |
| APP-302 | While a step runs in ERG mode, the system shall set the trainer's target power to the step's target in watts (a percentage of the app's FTP, or absolute watts) multiplied by the intensity, rounded to the trainer's minimum increment. | Targets use the app's FTP, not intervals.icu's. Halves round up: 162.5 W becomes 163 W, as intervals.icu shows it (Phase 2, F-20; Phase 4). | must | T | UC-01; D-07, D-13, A-20, P4 |
| APP-303 | If a target lies outside the trainer's supported power range, then the system shall send the nearest limit and show that the target was limited. | The D100 accepts 50–600 W. | must | T | UC-01; A-20 |
| APP-304 | When the next step's ERG target differs from the current one, the system shall send it the lead time (APP-703) before the step boundary, while the displayed step, lap and recorded target change at the boundary. | Compensates for the trainer's settling time on short intervals. | must | T, D | UC-01; D-11, A-12 |
| APP-305 | While a ramp step runs in ERG mode, the system shall update the target at least once per second, following the ramp shifted earlier by the lead time. | Ramps are linear, so one update a second keeps them smooth; the D100 reports at about 3.6 Hz (Phase 2, F-5). | must | T | UC-01; P1 |
| APP-306 | When a free-ride step starts, the system shall switch the trainer to resistance mode at the free-ride level. | In intervals.icu, free ride turns ERG off. | must | T | UC-01; D-11, A-27 |
| APP-307 | When the rider switches the current block between ERG and resistance mode, the system shall apply the new mode for the rest of that block, and the next block shall use its planned mode. | The rider's way out when ERG can't follow a short interval. | must | T, D | UC-02; D-13 |
| APP-308 | While in resistance mode, when the rider presses resistance up or down, the system shall change the trainer's level by 5 % of its supported range, rounded to its minimum increment and kept inside the range. | Resistance is unitless and trainer-specific, so the rider sees a percentage of the range. | must | T | UC-02, UC-03; D-13, D-14, A-20 |
| APP-309 | While a block runs in resistance mode, the system shall remember the level the rider last chose for each distinct step target and apply it whenever a step with that target starts again in the block. | With one rear cog, 330 W and 140 W need different levels. Without this the rider would have to tap every 30 s. | should | T | UC-02; P1, A-23 |
| APP-311 | While the ride is paused, the system shall stop the ride clock, hold the trainer at its lowest resistance level and mark the pause in the recording; on resume it shall re-apply the current step's target and mode. | The lowest level lets the rider stop or spin easily instead of restarting against a high ERG load. | must | T, D | UC-02; D-13, P1 |
| APP-312 | When the rider skips a step, the system shall end it at once and start the next step, sending its target without lead time. Skipping the last step ends the workout (APP-314). | A skipped step's target has to apply at once, so no lead time. | must | T | UC-02; D-13 |
| APP-313 | When the rider presses intensity up or down, the system shall change the intensity by 5 percentage points, between 50 % and 150 %, and apply it to the current and every later ERG target. | The limits keep a slip of the finger from doubling a target. | must | T | UC-02; D-13, P1 |
| APP-314 | When the last step of a workout ends, the system shall switch the trainer to resistance mode at the free-ride level, keep recording and prompt the rider to finish. | The rider can cool down for longer; an automatic stop would cut the ride short. | must | T | UC-01; P1 |
| APP-315 | When the rider confirms Finish, the system shall stop recording, write the ride files within 10 s, show the summary and, where upload to intervals.icu is on, start the upload. | One action closes the ride; the upload needs no extra step. | must | T, D | UC-05; D-09, D-10, D-15 |
| APP-316 | When the rider confirms Discard, the system shall end the ride without creating or uploading a FIT file, and keep its logs. | Test rides and false starts stay out of intervals.icu; the logs remain for debugging. | should | T | UC-05; P1 |
| APP-317 | When the rider starts a free ride, the system shall run without a workout, starting in resistance mode at the free-ride level, which the rider changes as in APP-308; when the rider switches to ERG, the system shall take the current 3 s average power, rounded to 5 W and limited to the trainer's power range, as the first target, which the rider changes in 5 W steps; and the system shall record the ride as for a workout ride. | Rides without a plan get the same file and upload as workout rides. Starting like a free-ride step, and entering ERG at the power being ridden, keeps the load from jumping (Ferran, 11 Nov 2026). | should | T, D | UC-03; D-14, P4 |
| APP-318 | If the trainer link is lost during a ride, then the system shall keep the ride clock and workout running, keep trying to reconnect for the rest of the ride and, once reconnected, request control and re-send the current target and mode. | Dropouts happen; the workout must survive them without a restart. | must | T, D | UC-07; D-12 |
| APP-319 | If the heart-rate link is lost during a ride, then the system shall keep the ride running, show heart rate as missing and keep trying to reconnect for the rest of the ride. | Heart rate is only recorded, so losing it must never stop the ride. | must | T, D | UC-07; D-06, D-12 |
| APP-320 | When a ride ends or the app shuts down in an orderly way, the system shall set the trainer to its lowest resistance level before releasing the connection. | FTMS can't store future targets on the trainer, so the system leaves it in an easy, known state whenever it lets go on purpose. What the D100 does after an unplanned link loss is checked in Phase 5 (a Phase 2 open point). | must | T, D | UC-05, UC-07; P1, A-33 |

### 4 Display and controls

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-401 | While the current step runs in ERG mode, the display shall show the ERG ride screen with the target power, current power, heart rate, time left in the step, the next step's target and duration, elapsed and remaining ride time, and intensity. | The minimum needed to ride structured intervals. | must | D | UC-01, UC-02; D-02, D-06, D-13 |
| APP-402 | The display shall show current power as a 3 s average. | Smooths trainers whose power varies within a pedal stroke; the D100's ERG power barely varies (Phase 2, F-11). The FIT file keeps the 1 s values. | should | T | UC-01; P1 |
| APP-403 | While a workout is running, the display shall show the workout profile and the current position in it. | Shows what's coming in the block at a glance. | should | D | UC-01; P1 |
| APP-404 | While less than 5 s of a step remain, the display shall count down to the next step. | 30/30s need the change to be anticipated. | should | D | UC-01; P1 |
| APP-405 | The display shall always show the link state of the trainer and the heart-rate monitor, and shall show a dropout within 3 s of its start. | The rider must know when the power or heart rate on screen is stale. A lost link shows in the next display update, within 1 s; a dropout by silence begins once 3 s have passed without data, and shows at that moment (Ferran, 11 Nov 2026). | must | T, D | UC-07; D-12, P4 |
| APP-406 | The display shall show the heart-rate monitor's battery level on the Pre-ride and ride screens. | Shows the strap's state before the warning fires. | must | D | UC-01; D-19 |
| APP-407 | Every control on the ride screens shall have a touch target of at least 60 × 60 pt. | Apple's minimum is 44 × 44 pt; sweaty fingers on a moving bike need more. | must | I | UC-02; D-13 |
| APP-408 | The display shall require a confirming action before Finish, Discard and Skip take effect. | An accidental tap must not end a ride or cut an interval. | should | D | UC-02; P1 |
| APP-409 | While a ride or calibration is running, the display shall keep the iPhone screen on. | A locked screen hides the targets mid-interval. Safari grants the screen wake lock on a tap and again when the page comes back into view, but not after a reload, which it sometimes does by itself (Phase 2, F-40, F-42, F-45); APP-416 covers that case. Auto-Lock set to Never is the fallback. | must | D | UC-01, UC-04; D-03, A-14, A-17, F-45 |
| APP-410 | The display shall work in Safari on the rider's iPhone over the home Wi-Fi, without installing an app. | The iPhone is the only display. | must | D | UC-01; D-02 |
| APP-411 | When a ride is finished, the display shall show its summary: duration, average and normalized power, IF, TSS, work, time in each zone, average and maximum heart rate, and the upload state. | Feedback right after the session; intervals.icu holds the long-term view. | must | D | UC-05; D-15 |
| APP-412 | The ERG ride screen shall show target, power, heart rate and step time left in text at least 48 pt high. | Readable at a glance during hard efforts. Phase 3C reads "high" as the height of the digits. | should | I | UC-01; P1 |
| APP-413 | When a step changes, the display shall play a short sound. | Helps when the rider isn't looking at the screen. | could | D | UC-01; P1 |
| APP-414 | While the current step runs in resistance mode, the display shall show the resistance ride screen: the resistance level in large type, + and − controls of at least 120 × 120 pt, and one line with the step's target power, current power, time left in the step and a control to return to ERG. | Holding a target by effort needs the target, the power and the time left; large + and − make level changes safe mid-effort. | must | I, D | UC-02; D-11, D-13, P1 |
| APP-415 | When the trainer changes between ERG and resistance mode, the display shall change to the matching ride screen without any action from the rider. | The right controls appear at once, also at free-ride steps and after the last step. | must | T, D | UC-02; D-11, P1 |
| APP-416 | While a ride or calibration is running, if the display doesn't hold the screen wake lock, then the display shall show a full-width prompt that requests the lock when tapped. | Safari refuses the wake lock without a tap after every page load (Phase 2, F-40) and sometimes reloads the page by itself (F-42); one tap on a prompt the rider can't miss gets it back. | must | D | UC-01, UC-04; D-03, F-40, F-42 |

### 5 Calibration

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-501 | When the rider starts a calibration from the Home screen, the system shall start the trainer's FTMS spin-down procedure. | Calibration from the app, without switching to the Onelap app. | must | T, D | UC-04; D-20, A-22, A-25 |
| APP-502 | While a spin-down is running, the display shall show the target speed band the trainer returned and the live speed, and tell the rider to speed up past the band and, when the trainer asks, to stop pedaling. | The trainer sets the speeds and asks for the stop through Fitness Machine Status. | must | T, D | UC-04; D-20, A-24, A-25 |
| APP-503 | When the trainer reports the spin-down result, the system shall show success or failure and log it with the date and time. | FTMS reports only success or error, so the "result" in D-20 is pass or fail. The D100 adds 2 undocumented bytes to Success, which the log keeps (Phase 2, F-37). | must | T, D | UC-04; D-20, A-25 |
| APP-504 | If no spin-down result arrives within 120 s of the start, then the system shall stop the procedure and show that the calibration failed. | A hung calibration must not lock the screen. | should | T | UC-04; D-20, P1 |
| APP-505 | While a ride is running, the system shall not start a spin-down. | A spin-down takes over the trainer and needs the rider to stop pedaling. | must | T | UC-04; D-20, P1 |
| APP-506 | When the trainer requests a spin-down, the system shall tell the rider and offer to start it once no ride is running. | FTMS lets a trainer ask for a spin-down. | could | T | UC-04; D-20, A-25 |

### 6 Recording, metrics and upload

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-601 | When a ride is finished, the system shall write one FIT activity file, marked as indoor cycling, that holds for every second of ride time the power, heart rate and target power in effect, and the cadence where a sensor is configured. | One file per ride serves intervals.icu, Garmin Connect and our own analysis. | must | T, D | UC-05; D-09, A-10, A-28 |
| APP-602 | The system shall record one sample per second of ride time, holding for each measurement the latest value received in the previous 2 s, and no value if none arrived. | Notifications arrive with jitter (about 3.6 Hz from the D100, Phase 2 F-5); an old value must not pass for a live one. | must | T | UC-01; D-09, P1 |
| APP-603 | The system shall record each dropout as missing values, not zeros, and log its start and end. | Zeros would distort NP and the averages. | must | T | UC-07; D-12 |
| APP-604 | The system shall mark each pause in the FIT file and leave paused time out of ride time, laps and ride metrics. | Paused time isn't training time. | must | T | UC-02; D-13 |
| APP-605 | The system shall start a new FIT lap at every step boundary and at every skip. | A lap per step lets intervals.icu and Garmin Connect show each interval. | must | T | UC-01; D-09 |
| APP-606 | When a ride is finished, the system shall compute the metrics in table M. | Per-ride numbers straight after the ride, without waiting for intervals.icu. | must | T | UC-05; D-15, A-18 |
| APP-607 | Where upload to intervals.icu is on (table S), when the ride files are written, the system shall upload the FIT file to intervals.icu without any action from the rider. | intervals.icu must see every ride to keep fitness and fatigue complete. A rider who imports rides into Garmin Connect, which passes them on to a linked intervals.icu account, turns the upload off to avoid duplicates (Phase 2, F-35). | must | T, D | UC-05; D-10, A-19, F-35 |
| APP-608 | Where upload to intervals.icu is on, if an upload fails, then the system shall keep the file, retry at least every 15 minutes for 7 days while the Pi is on, show the upload state and let the rider retry by hand. | A Wi-Fi or intervals.icu outage must not lose a ride. | must | T | UC-05; D-10, P1 |
| APP-609 | Where upload to intervals.icu is on, the system shall upload each ride to intervals.icu at most once, unless the rider asks for a new upload. | Avoids duplicate activities. | should | T | UC-05; P1 |
| APP-610 | The system shall let the rider download any ride's FIT file to the iPhone. | The rider imports it into Garmin Connect by hand; Garmin Connect accepts the file and passes it on to a linked intervals.icu account (Phase 2, F-35). | must | D | UC-05; D-10, A-10 |
| APP-611 | The system shall list past rides with date, workout name, duration, TSS and upload state. | To find a ride to download or upload again. | should | D | UC-05; P1 |
| APP-612 | The system shall keep ride files until the rider deletes them, and shall warn the rider when less than 1 GB of storage is free. | Files live on the Pi's microSD card. | should | T | UC-05; P1 |
| APP-613 | While the trainer and strap are simulated, the system shall record every ride with upload off. | Rides on the simulator must not land in the rider's training load (Phase 5, SF-37). The rider can still upload one by hand from its Summary. | must | T | UC-08; P5 |

**Table M — ride metrics.** FTP is the app's FTP at Start.

| Metric | Definition |
|----------------|--------------------------------------------------------------------------|
| Samples | One per second of ride time (APP-602). Paused time is excluded. Missing power values are left out of the power metrics; recorded zeros count. |
| Duration | Ride time in seconds: pauses excluded, dropouts included. |
| Average power | Mean of the power samples present. |
| Maximum power | Largest power sample. |
| NP | Over the power samples present: 30 s rolling average (first value at the 30th sample), each value to the 4th power, the mean of those, then the 4th root. Not shown when fewer than 30 power samples exist. |
| IF | NP / FTP. |
| TSS | (duration × NP × IF) / (FTP × 3600) × 100. |
| Work | Sum of the power samples × 1 s, in kJ. |
| Time in zone | Seconds of power samples in each zone of APP-702. |
| Heart rate | Average and maximum of the heart-rate samples present. |

### 7 Settings

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-701 | The system shall let the rider set FTP within the range and step of table S, and shall apply it to every later ride and its metrics. | Targets and metrics use the app's FTP. | must | T | UC-06; D-08 |
| APP-702 | The system shall let the rider define power zones as upper bounds in percent of FTP, in the steps of table S. | Time in zone needs them; the rider can copy his intervals.icu zones. | must | T | UC-06; D-08, D-15 |
| APP-703 | The system shall let the rider set the lead time within the range and step of table S. | Phase 2 measured 1.5 s on the D100 (F-25); other trainers and riders differ. | must | T | UC-06; D-11, A-12 |
| APP-704 | The system shall let the rider set the battery warning threshold within the range and step of table S. | D-19 left the threshold to Phase 1. | must | T | UC-06; D-19 |
| APP-705 | The system shall use the last resistance level the rider set as the free-ride level, starting from the trainer's lowest level. | Free ride resumes at the level the rider last chose. | should | T | UC-01, UC-03; D-14 |
| APP-706 | The system shall let the rider enter the intervals.icu athlete ID and API key. | Needed to read workouts and upload rides. | must | T | UC-06; D-07, D-10 |
| APP-707 | The system shall keep every setting across restarts and power cuts. | Settings entered once must survive the Pi being unplugged. | must | T | UC-06; P1 |
| APP-708 | The system shall use the defaults in table S until the rider changes them. | The app works on first start; only the devices and the intervals.icu account need entering. | must | T | UC-06; P1 |
| APP-709 | The system shall let the rider set his weight, 40 to 150 kg in steps of 1 kg, default 75 kg, and shall use it only for routes. | The route model needs the mass that moves (APP-903). | must | T | UC-06, UC-09; P5 |

**Table S — settings and defaults.** Intensity (100 % at Start, 5-point steps) and the resistance step (5 % of the range) are fixed, not settings.

| Setting | Range and step | Default | Basis |
|----------------|---------------------------|---------------------------|---------------------------|
| FTP | 100–500 W, 1 W | 250 W | The rider's FTP (project brief) |
| Power zones | Upper bounds of Z1 to Z5 in % of FTP, 1–200 %, strictly increasing, 1 % | Z1 ≤ 55, Z2 ≤ 75, Z3 ≤ 90, Z4 ≤ 105, Z5 ≤ 120, Z6 above 120 | Coggan's levels 1–6 (TrainingPeaks); range from Phase 5 (P5) |
| Lead time | 0–5 s, 0.5 s | 1.0 s | Phase 2's rule (median time to 90 % of a step, F-25) gave 1.5 s; on the first ride on the D100 the change came too early, and 1.0 s felt right (Phase 5, 12 Nov 2026; P5) |
| Battery warning | 5–50 %, 5 % | 20 % | Question 1 |
| Free-ride level | 0–100 % of the trainer's range, 5 % | The trainer's lowest level, then the last level used (APP-705) | P1 |
| Upload to intervals.icu | On or off | On | Phase 2 (F-35); off for a rider who imports into Garmin Connect |
| Rider weight, for routes | 40–150 kg, 1 kg | 75 kg | APP-709 (P5) |
| Trainer and heart-rate monitor | Chosen from a scan (APP-114) | None until chosen | — |
| intervals.icu athlete ID and API key | — | None until entered | — |

### 8 Timing, reliability, logging, security and maintainability

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-801 | When an ERG target or resistance level falls due, the system shall start writing it to the trainer within 100 ms, or within 100 ms of the pending control point procedure completing (APP-106). | The Pi's own delay must stay small next to the trainer's ~1.5 s settling time (Phase 2, F-25). The write itself takes 95–195 ms to complete (F-28). | must | T, D | UC-01; D-11, A-12, A-31 |
| APP-802 | When the rider taps a control that changes the target, level, mode or intensity, the system shall write the change to the trainer within 250 ms of the tap, or within 100 ms of the pending control point procedure completing (APP-106), for 95 % of taps, and within 1 s for every tap, over a session of at least 100 taps. | A tap must feel immediate. A tap that lands while a procedure is pending has to wait for it, because the D100 answers 186–390 ms after a write begins (F-28); APP-801 has the same clause. After the write, the trainer's own settling (~1.5 s, Phase 2 F-25) dominates what the rider feels; the 1 s ceiling covers Wi-Fi outliers. Wi-Fi round trips measured 29–34 ms at the 95th percentile (F-41, F-47). | must | T, D | UC-02; D-13, P1, P3, A-34 |
| APP-803 | When a power or heart-rate value arrives, the display shall show it within 250 ms for 95 % of values and within 1 s for every value, over a ride of at least 10 minutes. | Values arrive several times a second (Phase 2, F-5), so even a 1 s delay would show them visibly late. The 3 s power average (APP-402) smooths on top of this by design. | must | T, D | UC-01; D-06, P1, A-34 |
| APP-804 | The system shall start every step within 100 ms of its scheduled ride time, with no drift building up over a 4-hour ride. | Keeps targets and laps aligned with the plan. | must | T | UC-01; P1 |
| APP-805 | If the trainer becomes reachable again during a ride, then the system shall reconnect and re-send the current target within 10 s. | Bounds what a dropout costs: 10 s is a third of a 30 s interval. | must | T, D | UC-07; D-12 |
| APP-806 | If the heart-rate monitor becomes reachable again during a ride, then the system shall reconnect to it within 10 s. | The same bound as for the trainer. | must | T, D | UC-07; D-12 |
| APP-807 | If the display loses its connection or the page reloads during a ride, then the ride shall continue unaffected, and the display shall show the current state within 5 s of reconnecting. | The ride runs on the Pi; the phone is only a view. | must | T, D | UC-07; D-02 |
| APP-808 | If the app stops unexpectedly or the Pi loses power during a ride, then at most the last 5 s of recorded samples shall be lost. | A crash or power cut must cost seconds of data, not the ride. | must | T, D | UC-07; P1 |
| APP-809 | When the app restarts after an unexpected stop during a ride, the system shall offer to continue that ride, treating the outage as a dropout (APP-318), or to finish it. | Keeps one ride in one file; a crash becomes a gap. | should | T, D | UC-07; D-12, P1 |
| APP-810 | When the Pi is switched on, the system shall start without any manual step and be reachable from the iPhone within 90 s. | The Pi runs headless next to the trainer. | must | D | UC-01; D-01 |
| APP-811 | If the app process stops unexpectedly, then it shall be restarted automatically within 10 s. | With APP-809, a crash costs seconds, not the ride. | must | T, D | UC-07; P1 |
| APP-812 | The system shall complete a simulated 4-hour ride with every timing and recording requirement met. | Catches drift and memory growth over the longest sessions. | should | T | UC-08; P1 |
| APP-813 | The system shall log every Bluetooth read, write, notification and indication with UTC and monotonic timestamps in milliseconds, the device, the characteristic UUID, the direction and the raw bytes. | The basis for debugging and for replay tests. | must | I, T | UC-08; D-09 |
| APP-814 | The system shall log state changes, rider actions, warnings and errors with UTC timestamps, in one log per ride and one system log. | Diagnosing a bad ride afterwards. | must | I | UC-08; P1 |
| APP-815 | The system shall write its software version into every FIT file and log. | Ties each result to the code that produced it. | should | I | UC-08; P1 |
| APP-816 | The system shall serve the display over HTTPS on the home network, redirecting plain HTTP to it, with a certificate that chains to a root certificate installed and trusted on the rider's iPhone. | The Screen Wake Lock API works only in secure contexts (MDN). Safari trusts a private root limited to the Pi's name; one that also excluded IP addresses wasn't trusted (Phase 2, F-38, F-44). | must | I, D | UC-01; D-03, A-17, F-44 |
| APP-817 | The system shall store the intervals.icu API key only on the Pi, readable only by the app's own user account, and shall never write it to a log or send it to the display. | The key gives full access to the rider's intervals.icu account. | must | I, T | UC-06; D-07, D-10 |
| APP-818 | The system shall send ride data to no service other than intervals.icu. | Ride files include heart rate, which stays between the rider and intervals.icu. | should | I | UC-05; D-10 |
| APP-819 | The system shall run every function in this document against a simulated trainer and a simulated heart-rate monitor that present the same interface as the real devices. | Tests run without hardware. | must | I, T | UC-08; project instructions |
| APP-820 | The system shall replay a recorded Bluetooth log (APP-813) as the input of its device interfaces. | Turns real rides into regression tests. | should | T | UC-08; D-17 |
| APP-821 | Test inputs and expected outputs shall be kept as language-neutral data files: workouts, recorded trainer messages, expected target timelines and expected ride metrics. | A JavaScript v2 can be checked against the same set. | must | I | UC-08; D-17 |
| APP-822 | The software on the Pi shall be written in Python with every dependency pinned through uv, and shall run on the Raspberry Pi 5 under Raspberry Pi OS Trixie. The display shall be written in TypeScript and built before installation, with every dependency pinned in a lockfile; the Pi shall not need Node.js. | Platform chosen in Phase 0; the display framework chosen in Phase 3 (AD-03) needs a build, which runs on the laptop. | must | I | UC-08; D-01, A-16, P3 |
| APP-823 | The code shall pass flake8 with no findings and carry type hints. The display code shall pass its type check and linter with no findings. | Project code standards, applied to both languages. | must | I | UC-08; project instructions, P3 |
| APP-824 | If the system clock is not synchronised when a ride starts, then the system shall warn the rider. | FIT timestamps and today's workout list depend on the clock. | should | T | UC-01; A-29 |
| APP-825 | If 30 minutes pass during a ride, paused or not, with no power above 0 W and no rider action, then the system shall finish the ride as with Finish (APP-315). | A ride whose phone is lost, flat or forgotten would otherwise record all night and upload a ride hours long. A paused ride counts too: left alone, it would hold the trainer's only connection for good (Phase 4). | should | T | UC-07; P1, P4 |
| APP-826 | The system shall show its state on the Pi's green activity LED: off while the app isn't running, blinking while no trainer is connected, steady while the trainer is connected. | Shows whether the Pi and the app are up when the page doesn't load. The phone stays the status display while riding (APP-405); the Pi is out of sight. | could | D | UC-07; P1, A-36 |
| APP-830 | If the display's HTTPS certificate expires within 30 days, then the system shall show a warning on the Home screen. | The server certificate lasts 365 days and renewing it needs the laptop, where the private root's key stays (Phase 3, AD-12). Without a warning the page stops loading one evening before a ride. | should | T | UC-06; D-03, P3 |

APP-827 to APP-829 are reserved for the parked proposals on sharing the Pi.

### 9 Routes

Added with Phase 5's SL-13 and SL-14 (P5), at Ferran's request of 14 and 17 Nov 2026. Rides along a route get speed, distance, altitude and position from the ride's power; the trainer is never driven by the route (slope mode is a later version).

| ID | Requirement | Rationale | Pri. | Ver. | Traces |
|------------|------------------------------------------------------|----------------------------------------|--------|-------|---------------------|
| APP-901 | When Pre-ride opens, the system shall list the GPX files in the data directory's `routes` folder that can be used as a route, by name, each with its length and climb. | The rider picks from what is on the Pi. | must | T | UC-09; P5 |
| APP-902 | When the rider chooses a route, or no route, on Pre-ride, the system shall ride the next ride with that choice and keep it for later rides, also for a free ride. | One choice for a week of rides on the same route. | must | T | UC-09; P5 |
| APP-903 | While a ride on a route runs, the system shall work out from each ride second's recorded power, the route's grade and the rider's and bike's mass the speed, distance, altitude and position of that second, without changing the control of the trainer. | Speed and distance from the power the rider makes; the control path stays as without a route. Worked out during the ride since SL-14 (APP-910); SL-13 did it after Finish. | must | T | UC-09; P5 |
| APP-904 | When a ride on a route is finished, the system shall write the speed, distance, altitude and position of each second into the FIT file's Records, the distance and speeds into its Laps and Session, the climb into its Session, and mark it a virtual ride. | intervals.icu and Garmin Connect show the ride with its map and keep it apart from outdoor rides. For a ride on a route this takes the place of APP-601's "marked as indoor cycling". | must | T, D | UC-05, UC-09; P5 |
| APP-905 | When a ride is longer than its route, the system shall start the route again from its beginning. | Ferran, 17 Nov 2026. | should | T | UC-09; P5 |
| APP-906 | When a ride on a route is finished, the Summary and Past rides shall show the route's name, the distance ridden and the climb. | The number the rider looks for after a route ride. | should | T, D | UC-05, UC-09; P5 |
| APP-907 | When a file in the `routes` folder is larger than 10 MB, isn't GPX, declares a document type, has fewer than two points or is shorter than 100 m, the system shall leave it out of the list and log why. | A bad file must not stop the app or a ride; the rider needs the reason. | must | T | UC-09; P5 |
| APP-908 | When an interrupted ride on a route is continued or finished after a restart, the system shall keep its route. | Crash recovery (APP-809) must not lose the route. | should | T | UC-07, UC-09; P5 |
| APP-909 | While a ride on a route runs, the ride screen shall offer a route view, reached and left with one tap, showing a drawing of the route with the rider's place, the route's elevation profile with the rider's place, the speed, the grade at the rider's place, the distance ridden, and smaller the power, the heart rate and the step time left. | Ferran, 17 Nov 2026. The workout screen stays where every ride starts. | should | T, D | UC-09; P5 |
| APP-910 | While a ride on a route runs, the system shall show each ride second's speed, distance, altitude and grade with that second's view, and the FIT file and the Summary shall carry the same ride along the route. | What the rider sees during the ride is what is recorded (Phase 5, SF-43). | must | T | UC-09; P5 |

## Not in v1

### Later versions

Candidates, recorded so they aren't lost. They get APP numbers when a version plans them; until then they aren't verified.

- **Slope mode, the first V2 to-do** (Ferran, 17 Nov 2026): the trainer's resistance follows the route's grade, through FTMS Set Indoor Bike Simulation Parameters (op code 0x11). The D100 takes slope from 0 to 6 %, no descents (Phase 0); op code 0x11 has never been tried on the D100 (Phase 3A, AD-16); the live ride along the route (APP-903) already gives the grade at the rider's place every second.
- Heart-rate-controlled training. Phase 3 keeps the target calculation behind one interface (AD-11) so this can be added without touching the device code.
- Data screens the rider builds himself.
- A landscape layout of the display (Ferran, 11 Nov 2026). v1 is portrait only.
- A JavaScript v2, other trainers, several riders, sharing with friends (D-16).
- Virtual shifting.
- An FTP estimate computed from the ramp test (APP-211).
- Auto-pause and auto-start on pedaling. APP-825 only finishes abandoned rides; APP-301 only waits for the first stroke after Start.
- ERG smoothing beyond the lead time, such as overshoot boosts or ramped transitions. Phase 2 found the D100 doesn't need it: 90 % of a step in 1.5 s, overshoot at most 6 % (F-25).
- Power from the Cycling Power service or a separate power meter, and power matching. Phase 2 kept D-18: on the D100 both services carry the same value (F-4).

Simulated speed, distance and altitude, on this list until revision 7, are in v1 since revision 8, worked out from the ride's power along a route (section 9).

### Not planned

- ANT+, including FE-C: the D100 has none.
- The D100's Zwift protocol service: proprietary.
- Upload anywhere but intervals.icu: Garmin Connect has no personal write API (Phase 0), and intervals.icu is the single destination.
- Fitness and fatigue tracking over weeks: intervals.icu does that.
- Creating, editing or saving workouts in the app, and writing to the intervals.icu calendar: the intervals.icu library covers this (APP-210).
- Trainer firmware updates: the Onelap app does them.
- Displays other than Safari on the iPhone, native apps, access from outside the home network, and more than one display controlling a ride.
- User interface languages other than English.

## Assumptions

Statuses as of the Phase 2 close on 10 Nov 2026; the Phase 2 record has the evidence and the assumptions added there (A-37 to A-44). Phase 3 added A-48 to A-60 (in the Phase 3A architecture, the ICD and the display design); A-45 to A-47 are reserved for the parked shared-Pi proposals. A-60 is listed below because APP-301 relies on it. Phase 4 added A-61 to A-63 (in the test plan), Phase 5 A-64 to A-72 (in the Phase 5 document). Phase 6 brings every status up to date.

Changed in Phase 1:

| ID | Assumption | Status | Source | How it gets checked |
|------|--------------------------------|----------|---------------------------|-------------------------|
| A-11 | A person can't push activities into Garmin Connect through an official API; the personal API only reads. | Confirmed | Garmin Connect Developer Program overview: the Personal tier is "Pull only" | — |
| A-14 | Safari won't keep the screen awake for a page served over plain HTTP. | Confirmed | MDN, WakeLock.request(): available only in secure contexts (HTTPS) | — |
| A-18 | NP is the fourth root of the mean of the fourth powers of 30 s rolling-average power. | Confirmed | TrainingPeaks | — |
| A-20 | The range characteristics decode as power 50–600 W in 1 W steps, incline 0–6.0 % in 0.1 % steps and resistance 0–100 in steps of 1 (raw, unitless). | Confirmed | SIG GSS YAML (power, incline); pyftms for the 6-byte FTMS 1.0 resistance layout the D100 sends | — |
| A-21 | The HRM 200 sends its battery as a percentage from 0 to 100 (`80` shown in nRF Connect). | Confirmed | Phase 2, S1: `0x50`, 80 %, on read and in every notification | — |
| A-22 | The D100 runs a spin-down through the FTMS control point and reports progress and result through Fitness Machine Status (0x2ADA). | Confirmed | Phase 2, F-37: Success after a gentle approach to the band; an earlier sprint past it ended in Error (F-30) | — |

New:

| ID | Assumption | Status | Source | How it gets checked |
|------|--------------------------------|----------|---------------------------|-------------------------|
| A-24 | The D100 reports instantaneous speed in Indoor Bike Data, so the display can guide a spin-down. | Confirmed | Phase 2, S1: speed in every record | — |
| A-25 | Beyond op code 0x06 the FTMS details are: Start or Resume 0x07 to Set Targeted Cadence 0x14, with Spin Down Control at 0x13 (Start 0x01, Ignore 0x02); a successful start returns Target Speed Low and High (uint16, 0.01 km/h); result codes 0x01 Success to 0x05 Control Not Permitted; Fitness Machine Status uses 0x01 for a reset, 0x14 for spin-down status (0x01 Requested, 0x02 Success, 0x03 Error, 0x04 Stop Pedaling) and 0xFF for Control Permission Lost. FTMS reports no calibration value. Not yet read: the procedure timeout (4.16.4) and how a split data record is sent (4.19). | Confirmed on the D100; spec text open | Phase 2: codes, responses and statuses seen on the D100 (F-7, F-29, F-30, F-37); the D100 adds 2 bytes to spin-down Success and never splits a record (F-3) | Spec text 4.16.4 and 4.19 still unread (t19); not blocking |
| A-26 | intervals.icu delivers zone, range and ramp targets as percentages of FTP or watts the app can apply directly, and marks ramps apart from ranges. Its parsed workout is only filled once a workout has been edited in intervals.icu, so the app may need the .zwo or .erg download instead. | Refuted for zones | Phase 2, F-17 to F-20: ranges and ramps arrive marked and every ride has a parsed workout, but zone targets arrive as zone numbers | Done; APP-204 and APP-205 changed in revision 4 |
| A-27 | intervals.icu keeps free-ride steps as free-ride steps in the downloaded workout. | Confirmed | Phase 2, F-18 | — |
| A-28 | The per-second target power can be stored in the FIT file in a form intervals.icu and Garmin Connect accept. | Open | — | Phase 5, recording slice |
| A-29 | Without the optional real-time clock battery, which wasn't bought, the Pi can start with a wrong clock until it gets network time. | Open | Reported working on 5 Nov; whether that was the cold test is unconfirmed | Phase 5 (t17) |
| A-30 | The D100 follows Set Target Resistance Level across its whole raw range 0–100, and higher levels feel harder. | Confirmed | Phase 2, F-12 | — |
| A-31 | On the Pi, bleak writes a due control point command within 100 ms. | Confirmed | Phase 2, F-28: written 0–1 ms after falling due | — |
| A-32 | The D100 advertises the Fitness Machine service and the HRM 200 the Heart Rate service, so a scan can filter on them. | Confirmed | Phase 2, F-14 | — |
| A-33 | After an unplanned link loss, the D100 keeps applying the last target. | Open | Phase 2 couldn't cut the link (F-31) | Phase 5, reconnect slice (t35) |
| A-34 | On the home Wi-Fi, a message between the iPhone and the Pi takes under 100 ms one way for 95 % of messages. | Confirmed | Phase 2, F-41 and F-47: round trip at the 95th percentile 34 ms at the desk and 29 ms during a ride, so about 15–17 ms one way | — |
| A-35 | The intervals.icu API lists library workouts (`GET /api/v1/athlete/{id}/workouts`) with the same step structure as planned ones. | Confirmed | Phase 2, F-17 | — |
| A-36 | The app can drive the Pi 5's green ACT LED through `/sys/class/leds/ACT` without running as root, and the LED shows through the official case. | Open | Trigger list read on 4 Nov | Phase 5 (t17) |
| A-60 | With an ERG target set and the wheel still, the D100 reports 0 W, so the first power above 0 W marks the first pedal stroke (APP-301). | Open | Phase 2 F-11: reported ERG power sits on the target while pedaling; standstill not observed | Phase 5, first ride slice. Fallback: also require speed above 0 |

## Checks before approval

Ferran was to run these before approving Phase 1, so that fewer assumptions go into Phase 2. They ran in Phase 2, 4–6 Nov 2026; the results are in the Phase 2 record.

| Task | Check | Closes |
|------|------------------------------------------------------------|------------------------------|
| t14 | Laptop Windows version (`winver`) | A-13 |
| t04, t05 | D100 firmware update in Onelap, then one spin-down there as the reference | Reference for A-22 |
| t22 | nRF Connect session at the trainer: advertising, HRM battery, Indoor Bike Data, ERG at 200, 330 and 140 W, resistance levels, a deliberate disconnect, a spin-down | A-21, A-22, A-23, A-24, A-30, A-32, A-33; most of A-25; the data rate in A-12 |
| t23 | intervals.icu test workout, read back through the API | A-26, A-27, A-35 |
| t17 | Pi set up with Raspberry Pi OS Trixie: BlueZ version, clock without network, LED | A-16, A-29, A-36 |

Left for Phase 2, because they need code: A-10, A-15 and A-28 (FIT import and upload), A-12 (ERG settling time), A-17 (HTTPS on the iPhone), A-19 (intervals.icu's load), A-31 and A-34 (timing), and the unread FTMS sections in A-25.

## Questions answered

All five were answered on 3 Nov 2026 with the defaults: battery warning at 20 % (APP-704), pause at the lowest resistance (APP-311), recording after the last step until Finish (APP-314), one remembered level per target in resistance blocks (APP-309), intensity 50–150 % in 5-point steps (APP-313), and ranges at their midpoint (APP-205).

## Phase 0 decisions covered

| Decision | Requirements |
|----------|------------------------------------------------------------|
| D-01 | APP-810, APP-822 |
| D-02 | APP-401, APP-410, APP-807 |
| D-03 | APP-409, APP-416, APP-816, APP-830 |
| D-04 | APP-101, APP-103, APP-104 |
| D-05 | APP-109, APP-115 |
| D-06 | APP-111, APP-116, APP-206, APP-319, APP-401, APP-803 |
| D-07 | APP-201, APP-203, APP-204, APP-301, APP-302, APP-706, APP-817 |
| D-08 | APP-203, APP-701, APP-702 |
| D-09 | APP-115, APP-301, APP-315, APP-601, APP-602, APP-605, APP-813 |
| D-10 | APP-315, APP-607, APP-608, APP-610, APP-706, APP-817, APP-818 (upload optional since revision 4) |
| D-11 | APP-207, APP-304, APP-306, APP-414, APP-415, APP-703, APP-801 |
| D-12 | APP-105, APP-107, APP-318, APP-319, APP-405, APP-603, APP-805, APP-806, APP-809 |
| D-13 | APP-302, APP-307, APP-308, APP-311 to APP-313, APP-401, APP-407, APP-414, APP-604, APP-802 |
| D-14 | APP-308, APP-317, APP-705 |
| D-15 | APP-315, APP-411, APP-606, APP-702 |
| D-16 | Later-versions list |
| D-17 | APP-208, APP-820, APP-821 |
| D-18 | APP-108 |
| D-19 | APP-111, APP-112, APP-406, APP-704 |
| D-20 | APP-501 to APP-506 |

## Decisions made in Phase 1

- Requirements APP-101 to APP-826 as listed (APP-310 retired); items marked P1 are new in this phase.
- Requirements state capabilities; what v1 leaves out is in the Not in v1 lists, split into later versions and not planned.
- Resistance is shown as 0–100 % of the trainer's range, because FTMS resistance levels have no unit.
- Spin-down shows pass or fail only: FTMS returns no calibration value (pending the A-25 check).
- NP, IF, TSS, work and time in zone follow table M.
- Settings start from table S: FTP 250 W, Coggan zones, battery warning 20 %.
- Workouts come from today's plan, the intervals.icu library and built-in workouts; the app keeps no library of its own.
- Power ranges ride at their midpoint; only steps marked as ramps ramp.
- Resistance mode has its own ride screen, and the display switches to it by itself.
- Pause drops to the lowest resistance; after the last step the ride continues in resistance mode until Finish; an abandoned ride finishes after 30 idle minutes.
- Whenever the system releases the trainer on purpose, it leaves it at the lowest resistance.
- Retries after a refusal or a silent trainer continue for as long as the ride runs.
- Timing: a due target reaches the trainer within 100 ms; a tap within 250 ms (95 %) and 1 s (all); a new value reaches the display within 250 ms (95 %) and 1 s (all); a lost device reconnects within 10 s; a crash or power cut loses at most 5 s of data.
- The trainer connection is released after 10 minutes with no ride, calibration or Pre-ride screen open.
- Before approval, Ferran runs checks t14, t04, t05, t17, t22 and t23; A-25's spec text stays open.

**Changed in revision 4, from Phase 2:**

- Indoor Bike Data bytes beyond the declared fields are ignored (APP-108).
- The reset that follows a granted Request Control doesn't trigger a new Request Control (APP-105).
- Power-zone targets ride at the middle of intervals.icu's zone, applied to the app's FTP (APP-204, APP-205).
- A due target starts being written within 100 ms (APP-801).
- Lead time defaults to 1.5 s (table S).
- Uploading to intervals.icu is a setting, on by default; the FIT download for Garmin Connect stays (APP-315, APP-607 to APP-609, table S).

**Changed in revision 5, from Phase 2's S5 and S8:**

- New APP-416: whenever the display lacks the screen wake lock during a ride or calibration, it shows a prompt that gets the lock back with one tap.
- Rationales of APP-409, APP-802 and APP-816 carry the S8 results; A-34 confirmed.

**Changed in revision 6, from Phase 3 (marked P3):**

- APP-301: after Start the system sends the first target and waits; the ride clock and the recording start with the first power above 0 W. Terms "Ride" and "Ride time" follow; new A-60.
- APP-802: a tap during a pending control point procedure is written within 100 ms of it completing, as in APP-801.
- APP-822 and APP-823: the display is TypeScript, built on the laptop, with its own lockfile, type check and linter; the Pi doesn't need Node.js.
- New APP-830: warning on the Home screen 30 days before the display's certificate expires.
- APP-211: the ramp protocol is Ferran's, fixed in the ICD.
- Later versions: a landscape layout of the display.

**Changed in revision 7, from Phase 4 (marked P4):**

- APP-317: a free ride starts in resistance mode at the free-ride level; switching to ERG takes the current 3 s power, rounded to 5 W, as the first target.
- APP-825: a paused ride left alone finishes after 30 minutes too.
- APP-302, rationale: halves round up.
- APP-405, rationale: a lost link shows within 1 s, a dropout by silence 3 s after the last value.
- Verification: the display is checked by looking at it on the iPhone; no verification method changed.

**Changed in revision 8, from Phase 5 (marked P5):**

- Table S: lead time default 1.0 s instead of 1.5 s, from the first ride on the D100 (Phase 5, 13.6); zones are five strictly increasing upper bounds of 1 to 200 % of FTP (35.5); new row for the rider's weight (41.5).
- New use case UC-09, ride along a route, with the route view; new term "Route"; the Ride, route screen.
- New section 9, routes: APP-901 to APP-910, APP-903 as changed with SL-14 (worked out during the ride, not after it) (41.5, 47.5).
- New APP-613: rides on simulated devices are recorded with upload off (41.5).
- New APP-709: the rider's weight, used only for routes (41.5).
- Later versions: slope mode is the first V2 to-do; simulated speed, distance and altitude leave the list for v1 (41.5, 47.5).
- 128 requirements in all.

## Change log

| Rev. | Date | Change |
|------|-------------|------------------------------------------------------------------|
| 1 | 3 Nov 2026 | First draft. |
| 2 | 3 Nov 2026 | Ferran's review. APP-101 and APP-109 reworded as capabilities. APP-105 and APP-107 retry for as long as the ride runs. APP-108 joins split data records. APP-114 lists only fitness devices. APP-205 separates ranges from ramps. APP-401 covers the ERG screen only. APP-802 and APP-803 tightened to 250 ms. New: APP-210 and APP-211 (library and built-in workouts), APP-320 (safe release), APP-414 and APP-415 (resistance screen), APP-708 with table S (defaults), APP-825 (abandoned ride), APP-826 (LED). APP-310 retired into APP-414. Screens defined. Out-of-scope list split into later versions and not planned. A-32 to A-36 added. Questions 1–5 answered. |
| 3 | 3 Nov 2026 | Checks before approval added; A-11 and A-14 confirmed; the assumption checks point to those tasks; A-25's spec text left open. |
| 3 | 3 Nov 2026 | Approved by Ferran. |
| 4 | 8 Nov 2026 | Phase 2 changes, approved by Ferran with the Phase 2 record: APP-105, APP-108, APP-204, APP-205, APP-315, APP-607 to APP-609 and APP-801 reworded; table S lead time 1.5 s and new upload setting; rationales of APP-305, APP-320, APP-402, APP-503, APP-602, APP-607, APP-610, APP-703, APP-801 to APP-803 updated with Phase 2 numbers; UC-05 and UC-06; later-versions notes on ERG smoothing and Cycling Power; assumption statuses. |
| 5 | 10 Nov 2026 | Phase 2's S5 and S8 results, approved by Ferran when Phase 2 closed: new APP-416 (tap prompt for the wake lock); rationales of APP-409, APP-802 and APP-816; A-34 confirmed. |
| 6 | 11 Nov 2026 | Phase 3 changes, approved by Ferran with Phase 3: APP-301 (start on the first power), APP-802 (pending-procedure clause), APP-822 and APP-823 (TypeScript display), new APP-830 (certificate warning), APP-211 rationale (Ferran's ramp protocol), APP-412 rationale (digit height), landscape in the later-versions list, terms "Ride" and "Ride time", new A-60, P3 marks, D-03 coverage. |
| 7 | 11 Nov 2026 | Phase 4 changes, approved by Ferran with the Phase 4 findings: APP-317 (how a free ride starts), APP-825 (paused rides count), rationales of APP-302 (halves round up) and APP-405 (when a dropout shows), the note on verifying the display by looking at it, P4 marks, A-61 to A-63 named. |
| 8 | 18 Nov 2026 | Phase 5 changes, approved by Ferran with the slices (Phase 5 sections 13.6, 35.5, 41.5 and 47.5): table S lead time 1.0 s, zone range, rider weight; UC-09, the term "Route" and the Ride, route screen; new section 9 with APP-901 to APP-910; new APP-613 and APP-709; later-versions list with slope mode as the first V2 to-do and without simulated speed, distance and altitude; P5 marks; A-64 to A-72 named. Moved from the project into the repository as `docs/phase1-requirements.md`. |

## Sources

- Bluetooth SIG, Fitness Machine Service 1.0.1 (Table 4.15 for op codes 0x00–0x06 and the formats of Set Target Resistance Level and Set Target Power): https://files.bluetooth.com/download/ftms_v1-0-1/
- Bluetooth SIG, Fitness Machine Service 1.0.1 page: https://www.bluetooth.com/specifications/specs/fitness-machine-service-1-0-1
- Bluetooth SIG, GATT Specification Supplement page: https://www.bluetooth.com/specifications/gss/
- Bluetooth SIG, GSS YAML (Supported Power, Inclination and Resistance Level Range, Battery Level, Indoor Bike Data), read from the verbatim copies in bluetooth-sig 0.6.0: https://bitbucket.org/bluetooth-SIG/public/src/main/gss/ and https://pypi.org/project/bluetooth-sig/
- pyftms 0.4.15, FTMS client library (secondary): https://pypi.org/project/pyftms/
- TrainingPeaks, Normalized Power and how coaches use it: https://www.trainingpeaks.com/coach-blog/normalized-power-how-coaches-use/
- TrainingPeaks, estimating TSS: https://www.trainingpeaks.com/learn/articles/estimating-training-stress-score-tss/
- intervals.icu forum, workout builder syntax quick guide: https://forum.intervals.icu/t/workout-builder-syntax-quick-guide/123701
- Bluetooth SIG, Fitness Machine Service 1.0.1, sections 3.1 (advertising) and 4.1 (records split over notifications): same link as above
- TrainingPeaks, power training levels (Coggan): https://www.trainingpeaks.com/blog/the-trainingpeaks-blog/power-training-levels/
- intervals.icu forum, API access to intervals.icu (library and download endpoints): https://forum.intervals.icu/t/api-access-to-intervals-icu/609
- DC Rainmaker, Van Rysel D100 review ("Power Cable Required: Yes"): https://dcrainmaker.com/2025/02/decathlon-van-rysel-d100-smart-trainer-review.html
- Control Raspberry Pi 5 on-board LEDs (secondary): https://lstudynotes.blogspot.com/2026/01/control-raspberrypi-on-board-leds-and.html
- Apple Human Interface Guidelines, Buttons: https://developer.apple.com/design/human-interface-guidelines/buttons
- Garmin Developers, Connect Developer Program overview (Personal tier: pull only): https://developer.garmin.com/gc-developer-program/overview
- MDN, WakeLock.request(): https://developer.mozilla.org/docs/Web/API/WakeLock/request
- Phase 0 record, revision 2: `docs/phase0-discovery.md`
- Phase 2 record, revision 14 (findings F-1 to F-50, assumptions A-37 to A-44): `docs/phase2-spikes.md`
- Phase 3A architecture, revision 6: `docs/phase3-arch.md`
- Phase 3B Interface Control Document, revision 5: `docs/phase3-icd.md`
- Phase 3C display design, revision 3: `docs/phase3-display.md`
- Phase 4 test plan, revision 5: `docs/phase4-test-plan.md`
- Phase 5 implementation, revision 15 (sections 13.6, 35.5, 39, 41.5, 45, 47.5: the changes of revision 8; its sources cover GPX and the power model of the routes): `docs/phase5-implementation.md`
