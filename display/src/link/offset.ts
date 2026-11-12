// The Pi's clock seen from the page (ICD 4.6.7): the offset from the ping
// with the shortest round trip in the last 60 s.

export const OFFSET_WINDOW_MS = 60_000;

export interface PingSample {
  received_ms: number;
  rtt_ms: number;
  offset_ms: number;
}

export function sample(sent_ms: number, received_ms: number, pi_mono_ms: number): PingSample {
  const rtt_ms = received_ms - sent_ms;
  return { received_ms, rtt_ms, offset_ms: pi_mono_ms - (sent_ms + rtt_ms / 2) };
}

export function best(samples: readonly PingSample[], now_ms: number): PingSample | null {
  let found: PingSample | null = null;
  for (const s of samples) {
    if (now_ms - s.received_ms <= OFFSET_WINDOW_MS && (found === null || s.rtt_ms < found.rtt_ms)) {
      found = s;
    }
  }
  return found;
}

export function recent(samples: readonly PingSample[], now_ms: number): PingSample[] {
  return samples.filter((s) => now_ms - s.received_ms <= OFFSET_WINDOW_MS);
}
