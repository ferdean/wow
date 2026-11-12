// Keeps the screen on during a ride (APP-409). Slice SL-02 requests the lock
// on the Start tap and again when the page becomes visible during a ride;
// the full-width prompt of APP-416 follows in SL-11.

let lock: WakeLockSentinel | null = null;

export async function holdScreen(): Promise<void> {
  if (lock !== null || !("wakeLock" in navigator)) {
    return;
  }
  try {
    lock = await navigator.wakeLock.request("screen");
    lock.addEventListener("release", () => {
      lock = null;
    });
  } catch {
    lock = null;
  }
}

export async function releaseScreen(): Promise<void> {
  const held = lock;
  lock = null;
  await held?.release();
}
