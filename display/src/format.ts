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
