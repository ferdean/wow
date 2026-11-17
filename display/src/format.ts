// Formatting rules of Phase 3C ("Rules for the whole page").

export const MISSING = "––";

export function watts(value: number | null | undefined): string {
  return value === null || value === undefined ? MISSING : String(Math.round(value));
}

export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = String(whole % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function listDuration(seconds: number | null): string {
  if (seconds === null) {
    return "";
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

export function percent(value: number | null): string {
  return value === null ? "?" : `${Math.round(value)} %`;
}

export function zoneColour(zone: number | null | undefined): string {
  return zone ? `var(--zone-${zone})` : "var(--rise)";
}

// Time left counts up to the next whole second, so 0:06 is followed by
// the countdown's 5 rather than by 0:05 and then 5.
export function timeLeft(seconds: number): string {
  return clock(Math.ceil(seconds - 0.001));
}

// Advance widths of Sofia Sans Condensed at weight 800 with tabular
// digits, measured in Chrome: digits 0.526 em, colon 0.239 em.
const DIGIT_EM = 0.53;
const COLON_EM = 0.25;
const OTHER_EM = 0.55;
export const HEART_EM = 0.42;

export function textEm(text: string): number {
  return [...text].reduce(
    (sum, c) => sum + (c >= "0" && c <= "9" ? DIGIT_EM : c === ":" ? COLON_EM : OTHER_EM),
    0,
  );
}

export function countdown(left: number): string | null {
  return left > 0 && left <= 5 ? String(Math.ceil(left)) : null;
}

// Free ride has no target; its bar sits at a quarter of the profile.
export const FREE_RIDE_SHARE = 0.25;

export function shape(x: number, width: number, startHeight: number, endHeight: number, base: number): string {
  const w = Math.max(1, width);
  return `${x},${base} ${x},${base - startHeight} ${x + w},${base - endHeight} ${x + w},${base}`;
}

export function stepText(step: { duration: number; kind: string; start_power: number | null; end_power: number | null }): string {
  const time = step.duration % 60 === 0 && step.duration >= 60 ? `${step.duration / 60} min` : `${Math.round(step.duration)} s`;
  if (step.kind === "free_ride") {
    return `${time} free ride`;
  }
  if (step.kind === "unsupported" || step.start_power === null) {
    return `${time} not supported`;
  }
  const end = step.end_power ?? step.start_power;
  return end === step.start_power ? `${time} at ${step.start_power} W` : `${time} ${step.start_power}→${end} W`;
}

export const UPLOAD_WORDS: Record<string, string> = {
  off: "Not uploaded",
  pending: "Waiting to upload",
  uploading: "Uploading…",
  done: "Uploaded to intervals.icu",
  retrying: "Retrying",
  failed: "Upload failed",
  auth_error: "intervals.icu refused the key",
};

export function dateTime(utc: string): string {
  const moment = new Date(utc);
  return Number.isNaN(moment.getTime())
    ? MISSING
    : moment.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fixed(value: number | null, digits: number): string {
  return value === null ? MISSING : value.toFixed(digits);
}

export function gone(seconds: number): string {
  const whole = Math.round(seconds);
  if (whole < 60) {
    return `${whole} s`;
  }
  if (whole < 3600) {
    return `${Math.floor(whole / 60)} min ${whole % 60} s`;
  }
  return `${Math.floor(whole / 3600)} h ${Math.floor((whole % 3600) / 60)} min`;
}

export function speed(kmh: number | null): string {
  return kmh === null ? MISSING : kmh.toFixed(0);
}

export function km(metres: number | null): string {
  return metres === null ? MISSING : `${(metres / 1000).toFixed(1)} km`;
}

export function routeLine(length_m: number, ascent_m: number): string {
  return `${km(length_m)} · ${Math.round(ascent_m)} m up`;
}

export function speedText(kmh: number | null | undefined): string {
  return kmh === null || kmh === undefined ? MISSING : kmh.toFixed(1);
}

export function gradeText(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) {
    return MISSING;
  }
  const text = Math.abs(pct).toFixed(1);
  return pct < 0 && text !== "0.0" ? `−${text}` : text;
}
