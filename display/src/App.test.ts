// S-DSP-01: every golden view renders (test plan 5.16).
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen as dom } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
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
  sent: CommandName[]; send: (name: CommandName) => void } {
  const sent: CommandName[] = [];
  return { view, plan, live: true, receivedAt: performance.now(), sent, send: (name) => sent.push(name) };
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

  it("shows a free-ride step without a watt target", () => {
    render(App, { props: { link: fakeLink(golden("ride_free_ride_step")) } });
    expect(dom.getByText("Free")).toBeTruthy();
  });
});
