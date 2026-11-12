// Display WebSocket messages, ICD IF-06 (4.6.3 and 4.6.5), as the Pi sends
// and reads them.

export type LinkState = "not_configured" | "searching" | "connected" | "not_found" | "dropout";
export type Mode = "erg" | "resistance";
export type StepKind = "erg" | "free_ride" | "unsupported";
export type UploadState =
  | "off" | "pending" | "uploading" | "done" | "retrying" | "failed" | "auth_error";

export interface Hello { type: "hello"; app_version: string; protocol: 1 }
export interface Ack { type: "ack"; id: number; ok: boolean; error?: string }
export interface Pong { type: "pong"; id: number; t_page_ms: number; pi_mono_ms: number }

export interface PlanSegment {
  start: number; end: number; block: number; step: number;
  mode: Mode; kind: StepKind;
  start_power: number | null; end_power: number | null; zone: number | null; text: string | null;
}
export interface PlanBlock {
  index: number; label: string; repeats: number; duration: number; mode: Mode;
  steps: { duration: number; kind: StepKind;
           start_power: number | null; end_power: number | null; zone: number | null }[];
}
export interface Plan { type: "plan"; plan_id: string; segments: PlanSegment[]; blocks: PlanBlock[] }

export type Warning =
  | { kind: "hrm_battery_low"; battery_pct: number }
  | { kind: "trainer_not_responding" }
  | { kind: "control_refused" }
  | { kind: "target_limited"; requested_power: number; sent_power: number }
  | { kind: "clock_unsynced" }
  | { kind: "storage_low"; free_mb: number }
  | { kind: "cert_expiring"; days_left: number }
  | { kind: "spindown_requested" }
  | { kind: "workouts_offline"; downloaded_utc: string };

export interface View {
  type: "view"; seq: number; sent_mono_ms: number;
  data_mono_ms: number | null;
  links: { trainer: LinkState; hrm: LinkState };
  hrm_battery_pct: number | null;
  warnings: Warning[];
  screen: Screen;
}

export type Screen =
  | HomeScreen | PreRideScreen | RideScreen | SummaryScreen
  | HistoryScreen | CalibrationScreen | SettingsScreen;

export interface WorkoutCard {
  ref: string; source: "plan" | "library" | "builtin";
  name: string; duration: number | null; rideable: boolean; max_power: number | null;
  sketch: { duration: number; start_power: number; end_power: number; zone: number }[] | null;
}
export interface HomeScreen {
  name: "home";
  today: WorkoutCard[]; library: WorkoutCard[]; builtin: WorkoutCard[];
  recovery: { ride_id: string; started_utc: string; outage: number | null; can_continue: boolean } | null;
}

export interface PreRideScreen {
  name: "pre_ride";
  title: string; free_ride: boolean; ftp: number; duration: number | null;
  plan_id: string | null; block_modes: Mode[];
  can_start: boolean; blocked: "trainer_missing" | null;
}

export interface RideScreen {
  name: "ride";
  waiting_for_power: boolean;
  mode: Mode;
  paused: boolean; workout_done: boolean;
  elapsed: number; remaining: number | null;
  step: { index: number; count: number; left: number; text: string | null } | null;
  target: number | null; target_zone: number | null; target_limited: boolean;
  power: number | null;
  hr_bpm: number | null;
  next: { kind: "erg" | "free_ride"; target: number | null; zone: number | null; duration: number } | null;
  intensity_pct: number;
  resistance_pct: number | null;
  free_ride_target: number | null;
}

export interface Metrics {
  duration: number; avg_power: number | null; max_power: number | null;
  np: number | null; intensity_factor: number | null; tss: number | null; work_kj: number;
  time_in_zone: number[]; avg_hr_bpm: number | null; max_hr_bpm: number | null;
}
export interface SummaryScreen {
  name: "summary"; ride_id: string; title: string; start_utc: string; metrics: Metrics; upload: UploadState;
}

export interface HistoryScreen {
  name: "history";
  rides: { ride_id: string; start_utc: string; title: string; duration: number; tss: number | null; upload: UploadState }[];
  free_mb: number;
}

export interface CalibrationScreen {
  name: "calibration";
  phase: "idle" | "starting" | "speed_up" | "stop_pedaling" | "success" | "error" | "timeout";
  band_kmh: [number, number] | null; speed_kmh: number | null; elapsed: number;
  last: { utc: string; ok: boolean } | null;
  blocked: "ride_running" | "trainer_missing" | null;
}

export interface SettingsScreen {
  name: "settings";
  ftp: number; zones_pct: number[]; lead_time: number; battery_warn_pct: number;
  upload_on: boolean; intervals_account_set: boolean; cert_valid_until: string | null;
  trainer: { address: string; name: string | null } | null;
  hrm: { address: string; name: string | null } | null;
  scan: { kind: "trainer" | "hrm"; running: boolean;
          found: { address: string; name: string | null; rssi_dbm: number }[] } | null;
}

export type Down = Hello | Plan | View | Ack | Pong;

export type CommandName =
  | "open_workout" | "open_free_ride" | "set_block_mode" | "start" | "cancel_start"
  | "pause" | "resume" | "skip" | "intensity" | "switch_mode" | "resistance"
  | "free_ride_power" | "finish" | "discard" | "back" | "open_history" | "open_ride"
  | "upload_retry" | "delete_ride" | "open_calibration" | "calibration_start"
  | "calibration_cancel" | "open_settings" | "settings_set" | "intervals_account_set"
  | "device_scan" | "device_choose" | "recovery_continue" | "recovery_finish";

export interface Command {
  type: "command"; id: number; name: CommandName; args?: Record<string, unknown>;
  tap_mono_ms?: number;
}
export interface Ping { type: "ping"; id: number; t_page_ms: number }
export interface Painted { type: "painted"; seq: number; paint_mono_ms: number }

export type Up = Command | Ping | Painted;
