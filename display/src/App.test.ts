// S-DSP-01: every golden view renders (test plan 5.16).
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen as dom } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.svelte";
import type { CommandName, Plan, View } from "./types/protocol";

const GOLDEN = join(process.cwd(), "..", "testdata", "display");
const names = readdirSync(GOLDEN).filter((n) => n.endsWith(".view.json")).sort();

const plan: Plan = {
  type: "plan",
  plan_id: "builtin:test-3030@250",
  segments: [
    { start: 0, end: 60, block: 0, step: 0, mode: "erg", kind: "erg", start_power: 140, end_power: 140, zone: 2, text: "Warm-up" },
    { start: 60, end: 90, block: 1, step: 1, mode: "erg", kind: "erg", start_power: 220, end_power: 220, zone: 3, text: null },
  ],
  blocks: [
    { index: 0, label: "", repeats: 1, duration: 60, mode: "erg",
      steps: [{ duration: 60, kind: "erg", start_power: 140, end_power: 140, zone: 2 }] },
  ],
};

function fakeLink(view: View): { view: View; plan: Plan; live: boolean; receivedAt: number;
  sent: CommandName[]; args: (Record<string, unknown> | undefined)[];
  send: (name: CommandName, args?: Record<string, unknown>) => void } {
  const sent: CommandName[] = [];
  const args: (Record<string, unknown> | undefined)[] = [];
  return { view, plan, live: true, receivedAt: performance.now(), sent, args,
    send: (name, a) => { sent.push(name); args.push(a); } };
}

describe("S-DSP-01 golden views", () => {
  it("has golden views to render", () => {
    expect(names.length).toBeGreaterThan(5);
  });

  it.each(names)("renders %s", (name) => {
    const view = JSON.parse(readFileSync(join(GOLDEN, name), "utf-8")) as View;
    const { container, unmount } = render(App, { props: { link: fakeLink(view) } });
    expect(container.querySelector("main")).not.toBeNull();
    expect(container.textContent).not.toContain("Connecting to the Pi");
    expect(container.textContent).not.toContain("undefined");
    expect(container.textContent).not.toContain("NaN");
    unmount();
  });

  it("shows the ERG numbers of ride_erg", () => {
    const view = JSON.parse(readFileSync(join(GOLDEN, "ride_erg.view.json"), "utf-8")) as View;
    render(App, { props: { link: fakeLink(view) } });
    expect(dom.getByText("Step 2 of 7")).toBeTruthy();
    expect(dom.getByText("158")).toBeTruthy();
    expect(dom.getByText("Pause")).toBeTruthy();
  });

  it("asks to start pedaling while armed", () => {
    const view = JSON.parse(readFileSync(join(GOLDEN, "ride_waiting_for_power.view.json"), "utf-8")) as View;
    render(App, { props: { link: fakeLink(view) } });
    expect(dom.getByText("Start pedaling")).toBeTruthy();
    expect(dom.getByText("Cancel")).toBeTruthy();
  });
});

function golden(name: string): View {
  return JSON.parse(readFileSync(join(GOLDEN, `${name}.view.json`), "utf-8")) as View;
}

describe("S-DSP-01 SL-03 and SL-04 screens", () => {
  it("lists today, the library and the built-ins with the offline banner", () => {
    render(App, { props: { link: fakeLink(golden("home_offline_with_lists")) } });
    expect(dom.getByText("Today")).toBeTruthy();
    expect(dom.getByText("Library")).toBeTruthy();
    expect(dom.getByText(/intervals.icu out of reach/)).toBeTruthy();
    const notes = dom.getByText("Notes only").closest("button");
    expect(notes?.disabled).toBe(true);
    expect(dom.getByText("Can't be ridden here")).toBeTruthy();
  });

  it("shows the summary with the upload state", () => {
    const link = fakeLink(golden("summary"));
    render(App, { props: { link } });
    expect(dom.getByText("Normalized power")).toBeTruthy();
    expect(dom.getByText("219 W")).toBeTruthy();
    expect(dom.getByText("0.88")).toBeTruthy();
    expect(dom.getByText("Waiting to upload")).toBeTruthy();
    dom.getByText("Done").click();
    expect(link.sent).toEqual(["back"]);
  });

  it("shows a free-ride step on the resistance layout", () => {
    render(App, { props: { link: fakeLink(golden("ride_free_ride_step")) } });
    expect(dom.getByText("Free ride")).toBeTruthy();
    expect(dom.getByText("Level")).toBeTruthy();
  });
});

describe("S-DSP-01 long numbers fit their cells", () => {
  it("sizes step time left and heart rate to their cells", () => {
    const { container } = render(App, { props: { link: fakeLink(golden("ride_long_step_left")) } });
    const fitted = [...container.querySelectorAll<HTMLElement>(".fit")];
    expect(fitted.map((e) => e.textContent)).toEqual(["155", "10:14"]);
    expect(fitted.every((e) => Number(e.style.getPropertyValue("--em")) > 1.5)).toBe(true);
  });

  it("shows a ride time over an hour when the workout is done", () => {
    render(App, { props: { link: fakeLink(golden("ride_workout_done_after_an_hour")) } });
    expect(dom.getByText("1:45:07")).toBeTruthy();
  });
});

describe("S-DSP-02 confirmations and the SL-05 controls", () => {
  beforeEach(() => {
    cleanup();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("sends skip only from the sheet, which closes after 5 s", async () => {
    vi.useFakeTimers();
    const link = fakeLink(golden("ride_erg"));
    render(App, { props: { link } });
    await fireEvent.click(dom.getByText("Skip step"));
    expect(link.sent).toEqual([]);
    expect(dom.getByText("Skip the rest of this step?")).toBeTruthy();
    await vi.advanceTimersByTimeAsync(5000);
    expect(dom.queryByText("Skip the rest of this step?")).toBeNull();
    await fireEvent.click(dom.getByText("Skip step"));
    const [, confirmSkip] = dom.getAllByText("Skip step");
    if (confirmSkip) {
      await fireEvent.click(confirmSkip);
    }
    expect(link.sent).toEqual(["skip"]);
  });

  it("finishes or discards only after confirming", async () => {
    const link = fakeLink(golden("ride_erg"));
    render(App, { props: { link } });
    await fireEvent.click(dom.getByText("Finish"));
    await fireEvent.click(dom.getByText("Discard ride"));
    expect(link.sent).toEqual([]);
    await fireEvent.click(dom.getByText("Discard"));
    expect(link.sent).toEqual(["discard"]);
    await fireEvent.click(dom.getByText("Finish"));
    await fireEvent.click(dom.getByText("Finish and save"));
    expect(link.sent).toEqual(["discard", "finish"]);
  });

  it("pauses, resumes and changes the intensity", async () => {
    const link = fakeLink(golden("ride_erg"));
    render(App, { props: { link } });
    await fireEvent.click(dom.getByText("Pause"));
    await fireEvent.click(dom.getByLabelText("Intensity up"));
    await fireEvent.click(dom.getByText("Ride by resistance"));
    expect(link.sent).toEqual(["pause", "intensity", "switch_mode"]);
    expect(link.args[1]).toEqual({ step: 1 });
  });

  it("shows a paused ride with Resume", () => {
    render(App, { props: { link: fakeLink(golden("ride_paused")) } });
    expect(dom.getByText("Resume")).toBeTruthy();
    expect(dom.getAllByText("Paused").length).toBeGreaterThan(0);
  });

  it("rides a block by resistance and goes back to ERG", async () => {
    const link = fakeLink(golden("ride_resistance_block"));
    render(App, { props: { link } });
    expect(dom.getByText("5")).toBeTruthy();
    await fireEvent.click(dom.getByLabelText("Resistance up"));
    await fireEvent.click(dom.getByText("Back to ERG"));
    expect(link.sent).toEqual(["resistance", "switch_mode"]);
    expect(link.args).toEqual([{ step: 1 }, { mode: "erg" }]);
  });

  it("moves a free ride's power in 5 W steps", async () => {
    const link = fakeLink(golden("ride_free_ride_by_power"));
    render(App, { props: { link } });
    expect(dom.getAllByText("185").length).toBe(2);
    await fireEvent.click(dom.getByLabelText("Power up"));
    expect(link.sent).toEqual(["free_ride_power"]);
  });

  it("sets a block to resistance on Pre-ride and opens a free ride from Home", async () => {
    const pre = fakeLink(golden("pre_ride_block_in_resistance"));
    const { unmount } = render(App, { props: { link: pre } });
    await fireEvent.click(dom.getByText("ERG"));
    expect(pre.sent).toEqual(["set_block_mode"]);
    expect(pre.args[0]).toEqual({ block: 0, mode: "resistance" });
    unmount();
    const home = fakeLink(golden("home"));
    render(App, { props: { link: home } });
    await fireEvent.click(dom.getByText("Free ride"));
    expect(home.sent).toEqual(["open_free_ride"]);
  });
});

describe("S-DSP-03 a page that lost the Pi", () => {
  it("dims the values and blocks the controls", () => {
    const link = { ...fakeLink(golden("ride_erg")), live: false };
    const { container } = render(App, { props: { link } });
    expect(container.querySelector("main")?.classList.contains("stale")).toBe(true);
    expect(dom.getByText("Lost the Pi. Reconnecting…")).toBeTruthy();
    cleanup();
  });
});

describe("S-DSP-02 the profile after a skip", () => {
  it("places the marker at the plan time, not the ride time", () => {
    const view = golden("ride_erg");
    if (view.screen.name !== "ride") {
      throw new Error("ride_erg is not a ride view");
    }
    const skipped: View = { ...view, screen: { ...view.screen, elapsed: 30, remaining: 30 } };
    const { container } = render(App, { props: { link: { ...fakeLink(skipped), receivedAt: performance.now() } } });
    const marker = container.querySelector("rect.marker");
    expect(Number(marker?.getAttribute("x"))).toBeCloseTo((60 / 90) * 1000 - 2, 0);
    cleanup();
  });
});

describe("S-DSP-06 SL-07 to SL-09 screens", () => {
  beforeEach(() => {
    cleanup();
  });

  it("offers an interrupted ride on Home", async () => {
    const link = fakeLink(golden("home_recovery"));
    render(App, { props: { link } });
    expect(dom.getByText("A ride stopped unexpectedly")).toBeTruthy();
    expect(dom.getByText(/Only 812 MB free/)).toBeTruthy();
    expect(dom.getByText("The trainer asks for a calibration.")).toBeTruthy();
    await fireEvent.click(dom.getByText("Continue ride"));
    await fireEvent.click(dom.getByText("Finish ride"));
    await fireEvent.click(dom.getByText("Past rides"));
    await fireEvent.click(dom.getByText("Calibrate"));
    expect(link.sent).toEqual(["recovery_continue", "recovery_finish", "open_history", "open_calibration"]);
  });

  it("offers only Finish when the gap is unknown", () => {
    render(App, { props: { link: fakeLink(golden("home_recovery_finish_only")) } });
    expect(dom.queryByText("Continue ride")).toBeNull();
    expect(dom.getByText("Finish ride")).toBeTruthy();
  });

  it("lists past rides and opens one", async () => {
    const link = fakeLink(golden("history"));
    render(App, { props: { link } });
    expect(dom.getByText("31.5 GB free on the Pi")).toBeTruthy();
    expect(dom.getByText("Upload failed")).toBeTruthy();
    await fireEvent.click(dom.getByText("ERG check"));
    expect(link.args[0]).toEqual({ ride_id: "2026-11-12T162426Z" });
  });

  it("downloads, retries and deletes a past ride only after confirming", async () => {
    const link = fakeLink(golden("summary_past"));
    render(App, { props: { link } });
    const download = dom.getByText("Download FIT file");
    expect(download.getAttribute("href")).toBe("/rides/2026-11-12T162426Z/ride.fit");
    await fireEvent.click(dom.getByText("Try again"));
    await fireEvent.click(dom.getByText("Delete ride"));
    expect(link.sent).toEqual(["upload_retry"]);
    await fireEvent.click(dom.getByText("Delete"));
    expect(link.sent).toEqual(["upload_retry", "delete_ride"]);
  });

  it("guides a calibration", async () => {
    const link = fakeLink(golden("calibration_idle"));
    const { unmount } = render(App, { props: { link } });
    await fireEvent.click(dom.getByText("Start calibration"));
    expect(link.sent).toEqual(["calibration_start"]);
    unmount();
    render(App, { props: { link: fakeLink(golden("calibration_speed_up")) } });
    expect(dom.getByText("Speed up gently past 40 km/h. No sprint.")).toBeTruthy();
    expect(dom.getByText("34")).toBeTruthy();
    cleanup();
    render(App, { props: { link: fakeLink(golden("calibration_blocked")) } });
    expect((dom.getByText("Start calibration") as HTMLButtonElement).disabled).toBe(true);
  });

  it("greets with a Start button unless a ride runs", async () => {
    render(App, { props: { link: fakeLink(golden("home")), greet: true } });
    await fireEvent.click(dom.getByText("Start"));
    expect(dom.getByText("WitchesOnWheels")).toBeTruthy();
    expect(dom.getByText("Free ride")).toBeTruthy();
    cleanup();
    render(App, { props: { link: fakeLink(golden("ride_erg")), greet: true } });
    expect(dom.queryByText("Start")).toBeNull();
  });
});
