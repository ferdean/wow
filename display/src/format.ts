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
  failed: "Upload failed. Tap to try again.",
  auth_error: "intervals.icu refused the key. Check Settings.",
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
