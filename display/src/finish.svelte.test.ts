// S-DSP-04, S-DSP-05 and S-DSP-06 for SL-10 and SL-11 (test plan 5.16):
// the wake-lock prompt, the countdown between views, the clock offset,
// the step tone and the Settings screen.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen as dom } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.svelte";
import { releaseScreen } from "./device/wake.svelte";
import { best, sample } from "./link/offset";
import type { CommandName, View } from "./types/protocol";

const GOLDEN = join(process.cwd(), "..", "testdata", "display");

function golden(name: string): View {
  return JSON.parse(readFileSync(join(GOLDEN, `${name}.view.json`), "utf-8")) as View;
}

function fakeLink(view: View): { view: View; plan: null; live: boolean; receivedAt: number;
  sent: CommandName[]; args: (Record<string, unknown> | undefined)[];
  send: (name: CommandName, args?: Record<string, unknown>) => void } {
  const sent: CommandName[] = [];
  const args: (Record<string, unknown> | undefined)[] = [];
  return { view, plan: null, live: true, receivedAt: performance.now(), sent, args,
    send: (name, a) => { sent.push(name); args.push(a); } };
}

class FakeSentinel extends EventTarget {
  released = false;
  async release(): Promise<void> {
    this.released = true;
    this.dispatchEvent(new Event("release"));
  }
}

function mockWakeLock(answers: ("grant" | "refuse")[]): { asked: number; sentinels: FakeSentinel[] } {
  const state = { asked: 0, sentinels: [] as FakeSentinel[] };
  vi.stubGlobal("navigator", {
    ...navigator,
    wakeLock: {
      request: vi.fn(async () => {
        state.asked += 1;
        if ((answers.shift() ?? "grant") === "refuse") {
          throw new DOMException("not allowed", "NotAllowedError");
        }
        const sentinel = new FakeSentinel();
        state.sentinels.push(sentinel);
        return sentinel;
      }),
    },
  });
  return state;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve();
  }
}

describe("S-DSP-04 the wake lock and its prompt", () => {
  afterEach(async () => {
    cleanup();
    await releaseScreen();
    vi.unstubAllGlobals();
  });

  it("shows the prompt during a ride after a reload, and a tap gets the lock", async () => {
    const lock = mockWakeLock(["grant"]);
    render(App, { props: { link: fakeLink(golden("ride_erg")) } });
    const prompt = dom.getByText("Tap to keep the screen on");
    await fireEvent.click(prompt);
    await settle();
    expect(lock.asked).toBeGreaterThanOrEqual(1);
    expect(dom.queryByText("Tap to keep the screen on")).toBeNull();
    await lock.sentinels[0]?.release();
    await settle();
    expect(dom.getByText("Tap to keep the screen on")).toBeTruthy();
  });

  it("asks again on any tap and when the page is visible", async () => {
    const lock = mockWakeLock(["refuse", "grant", "grant"]);
    render(App, { props: { link: fakeLink(golden("ride_erg")) } });
    await fireEvent.pointerDown(dom.getByText("Pause"));
    await settle();
    expect(lock.asked).toBe(1);
    expect(dom.getByText("Tap to keep the screen on")).toBeTruthy();
    await fireEvent.pointerDown(dom.getByText("Pause"));
    await settle();
    expect(lock.asked).toBe(2);
    expect(dom.queryByText("Tap to keep the screen on")).toBeNull();
    await lock.sentinels[0]?.release();
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(lock.asked).toBe(3);
  });

  it("asks on the Start tap and shows no prompt outside a ride", async () => {
    const lock = mockWakeLock(["grant"]);
    const link = fakeLink(golden("pre_ride"));
    render(App, { props: { link } });
    expect(dom.queryByText("Tap to keep the screen on")).toBeNull();
    await fireEvent.click(dom.getByText("Start ride"));
    await settle();
    expect(lock.asked).toBe(1);
    expect(link.sent).toEqual(["start"]);
    cleanup();
    await lock.sentinels[0]?.release();
    render(App, { props: { link: fakeLink(golden("home")) } });
    expect(dom.queryByText("Tap to keep the screen on")).toBeNull();
  });

  it("tells a browser without the API to set Auto-Lock to Never", () => {
    vi.stubGlobal("navigator", { userAgent: "old" });
    render(App, { props: { link: fakeLink(golden("calibration_speed_up")) } });
    expect(dom.getByText(/set Auto-Lock to Never/)).toBeTruthy();
  });
});

describe("S-DSP-05 time between views and the clock offset", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("counts the step down by itself, to the 5-second countdown", async () => {
    const { container } = render(App, { props: { link: fakeLink(golden("ride_erg")), tick: 100 } });
    const left = (): string | null | undefined =>
      [...container.querySelectorAll(".cell")].find((c) => c.textContent?.includes("Step left"))
        ?.querySelector(".number")?.textContent;
    expect(left()).toBe("0:20");
    await vi.advanceTimersByTimeAsync(4000);
    expect(left()).toBe("0:16");
    await vi.advanceTimersByTimeAsync(12000);
    expect(left()).toBe("4");
    expect(container.querySelector(".cell.counting")).not.toBeNull();
  });

  it("takes the offset from the shortest round trip of the last minute", () => {
    const pings = [sample(0, 40, 1_000_020), sample(100, 112, 1_000_106), sample(200, 225, 1_000_212)];
    const chosen = best(pings, 300);
    expect(chosen?.rtt_ms).toBe(12);
    expect(chosen?.offset_ms).toBe(1_000_106 - 106);
    expect(best(pings, 70_000)).toBeNull();
  });
});

describe("S-DSP-06 the step tone and the Settings screen", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("plays one tone when the step changes", async () => {
    const started: number[] = [];
    class FakeContext {
      state = "running";
      currentTime = 0;
      destination = {};
      createOscillator(): object {
        return { frequency: { value: 0 }, connect: (n: object) => n, start: (t: number) => started.push(t), stop: () => undefined };
      }
      createGain(): object {
        return { gain: { setValueAtTime: () => undefined, linearRampToValueAtTime: () => undefined },
                 connect: (n: object) => n };
      }
      resume(): Promise<void> {
        return Promise.resolve();
      }
    }
    vi.stubGlobal("AudioContext", FakeContext);
    const view = golden("ride_erg");
    const link = $state(fakeLink(view));
    const { container } = render(App, { props: { link } });
    await fireEvent.pointerDown(container);
    expect(started).toEqual([]);
    if (view.screen.name !== "ride" || view.screen.step === null) {
      throw new Error("ride_erg has a step");
    }
    link.view = { ...view, seq: 2, screen: { ...view.screen, step: { ...view.screen.step, index: 2, left: 30 } } };
    await settle();
    expect(started.length).toBe(1);
  });

  it("edits FTP, zones, the account and a device", async () => {
    const link = fakeLink(golden("settings_defaults"));
    render(App, { props: { link } });
    await fireEvent.click(dom.getByText("FTP"));
    await fireEvent.click(dom.getByLabelText("FTP up 10"));
    await fireEvent.click(dom.getByLabelText("FTP down"));
    await fireEvent.click(dom.getByText("Save"));
    expect(link.args[0]).toEqual({ key: "ftp", value: 259 });
    await fireEvent.click(dom.getByText("Power zones"));
    await fireEvent.click(dom.getByLabelText("Zone 5 up"));
    await fireEvent.click(dom.getByText("Save"));
    expect(link.args[1]).toEqual({ key: "zones_pct", value: [55, 75, 90, 105, 121] });
    await fireEvent.click(dom.getByText("Account"));
    await fireEvent.input(dom.getByLabelText("Athlete ID"), { target: { value: "i1" } });
    await fireEvent.input(dom.getByLabelText("API key"), { target: { value: " k " } });
    await fireEvent.click(dom.getByText("Save"));
    expect(link.args[2]).toEqual({ athlete_id: "i1", api_key: "k" });
    const [chooseTrainer] = dom.getAllByText("Choose");
    if (chooseTrainer) {
      await fireEvent.click(chooseTrainer);
    }
    expect(link.sent).toEqual(["settings_set", "settings_set", "intervals_account_set", "device_scan"]);
    expect(link.args[3]).toEqual({ kind: "trainer" });
  });

  it("lists the scan and lets only the right kind be chosen", async () => {
    const link = fakeLink(golden("settings_scan"));
    render(App, { props: { link } });
    expect(dom.getByText("Key saved")).toBeTruthy();
    const strap = dom.getAllByText("HRM200:739158").map((e) => e.closest<HTMLButtonElement>("button.found"))
      .find((b) => b !== null);
    const cadence = dom.getByText("CADENCE-1816").closest("button");
    expect(cadence?.disabled).toBe(true);
    expect(strap?.disabled).toBe(false);
    if (strap) {
      await fireEvent.click(strap);
    }
    expect(link.args[0]).toEqual({ kind: "hrm", address: "E0:E2:EF:63:14:BC" });
  });
});

describe("S-GAR-16 Garmin Connect on the display", () => {
  afterEach(() => cleanup());

  it("switches the Garmin upload and says how to sign in", async () => {
    const link = fakeLink(golden("settings_garmin_signed_out"));
    render(App, { props: { link } });
    expect(dom.getByText("Not signed in")).toBeTruthy();
    expect(dom.getByText("Sign in once on the Pi: wow-garmin login.")).toBeTruthy();
    expect(dom.queryByText(/may get each ride twice/)).toBeNull();
    await fireEvent.click(dom.getByText("Upload rides to Garmin Connect"));
    expect(link.sent).toEqual(["settings_set"]);
    expect(link.args[0]).toEqual({ key: "garmin_upload_on", value: false });
  });

  it("warns about doubles with both uploads on", () => {
    render(App, { props: { link: fakeLink(golden("settings_garmin_both_on")) } });
    expect(dom.getByText("Signed in on the Pi")).toBeTruthy();
    expect(dom.getByText(/may get each ride twice/)).toBeTruthy();
  });

  it("shows the Garmin state on the Summary and retries it alone", async () => {
    const link = fakeLink(golden("summary_garmin_auth_error"));
    render(App, { props: { link } });
    expect(dom.getByText("Uploaded to intervals.icu")).toBeTruthy();
    expect(dom.getByText("Garmin sign-in needed")).toBeTruthy();
    const [again, garmin] = dom.getAllByRole("button").filter((b) => /again|now/i.test(b.textContent ?? ""));
    expect(again?.textContent).toBe("Upload again");
    if (garmin) {
      await fireEvent.click(garmin);
    }
    expect(link.sent).toEqual(["garmin_upload_retry"]);
    expect(link.args[0]).toEqual({ ride_id: "2026-11-18T171500Z" });
  });

  it("leaves Garmin out where it isn't set up", () => {
    render(App, { props: { link: fakeLink(golden("summary_done")) } });
    expect(dom.queryByText(/Garmin/)).toBeNull();
  });

  it("lists the Garmin state in Past rides", () => {
    render(App, { props: { link: fakeLink(golden("history_garmin")) } });
    expect(dom.getByText("Uploaded to Garmin Connect")).toBeTruthy();
    expect(dom.getByText("Garmin upload failed").classList.contains("bad")).toBe(true);
    expect(dom.getAllByText(/Garmin/)).toHaveLength(2);
  });
});
