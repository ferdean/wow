// Keeps the screen on during a ride or calibration (APP-409, APP-416; 3C,
// "Screen wake lock"). The lock is asked for on the Start tap, again when
// the page becomes visible, and on any tap while it isn't held (A-57).

let lock: WakeLockSentinel | null = null;

export const wake = $state({ held: false });

export function supported(): boolean {
  return typeof navigator !== "undefined" && "wakeLock" in navigator;
}

export async function holdScreen(): Promise<void> {
  if (lock !== null || !supported()) {
    return;
  }
  try {
    const got = await navigator.wakeLock.request("screen");
    lock = got;
    wake.held = true;
    got.addEventListener("release", () => {
      if (lock === got) {
        lock = null;
        wake.held = false;
      }
    });
  } catch {
    lock = null;
    wake.held = false;
  }
}

export async function releaseScreen(): Promise<void> {
  const held = lock;
  lock = null;
  wake.held = false;
  await held?.release();
}
