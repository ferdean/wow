// S-DSP-03: the page's connection to the Pi (3C).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Link } from "./link.svelte";

class FakeSocket {
  static readonly OPEN = 1;
  static made: FakeSocket[] = [];
  readyState = FakeSocket.OPEN;
  sent: string[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.made.push(this);
  }

  send(text: string): void {
    this.sent.push(text);
  }

  close(): void {
    this.onclose?.();
  }

  deliver(message: object): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function view(seq: number): object {
  return { type: "view", seq, sent_mono_ms: 0, data_mono_ms: null,
           links: { trainer: "connected", hrm: "connected" },
           hrm_battery_pct: null, warnings: [], screen: { name: "home" } };
}

describe("S-DSP-03 the page's connection", () => {
  let reload: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.made = [];
    vi.stubGlobal("WebSocket", FakeSocket);
    reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("goes stale after 3 s without a view and reconnects with backoff", () => {
    const link = new Link("wss://wow.local/ws", "1.0.0");
    link.start();
    const first = FakeSocket.made[0];
    first?.deliver({ type: "hello", app_version: "1.0.0", protocol: 1 });
    first?.deliver(view(1));
    expect(link.live).toBe(true);
    vi.advanceTimersByTime(3500);
    expect(link.live).toBe(false);
    const opened: number[] = [];
    let elapsed = 0;
    FakeSocket.made.at(-1)?.close();
    for (let step = 0; step < 5; step += 1) {
      const before = FakeSocket.made.length;
      while (FakeSocket.made.length === before) {
        vi.advanceTimersByTime(100);
        elapsed += 100;
      }
      opened.push(elapsed);
      elapsed = 0;
      FakeSocket.made.at(-1)?.close();
    }
    expect(opened).toEqual([500, 1000, 2000, 4000, 5000]);
  });

  it("reloads when the Pi runs another version", () => {
    const link = new Link("wss://wow.local/ws", "1.0.0");
    link.start();
    FakeSocket.made[0]?.deliver({ type: "hello", app_version: "1.1.0", protocol: 1 });
    expect(reload).toHaveBeenCalledOnce();
  });
});
