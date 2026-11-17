// S-DSP-07 and S-DSP-08 for SL-13 (test plan 5.16): the route on
// Pre-ride and the Summary, the rider's weight, and the gallery of the
// golden views that DS-8 walks through.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen as dom } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.svelte";
import { km, routeLine } from "./format";
import Gallery from "./gallery/Gallery.svelte";
import { GOLDEN_PLANS, GOLDEN_VIEWS } from "./gallery/load";
import { galleryStates, nameOf, stateOf } from "./gallery/states";
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

afterEach(() => {
  cleanup();
  location.hash = "";
  vi.unstubAllGlobals();
});

describe("S-DSP-07 routes", () => {
  it("formats distances and climbs", () => {
    expect(km(24312)).toBe("24.3 km");
    expect(km(null)).toBe("––");
    expect(routeLine(5000, 410.4)).toBe("5.0 km · 410 m up");
  });

  it("shows the chosen route on Pre-ride and sends the choice", async () => {
    const link = fakeLink(golden("pre_ride_routes"));
    render(App, { props: { link } });
    const row = dom.getByText("Route").closest("button") as HTMLButtonElement;
    expect(row.textContent).toContain("Lake loop");
    expect(row.textContent).toContain("24.3 km · 313 m up");
    await fireEvent.click(row);
    expect(dom.getByRole("dialog", { name: "Route" })).toBeTruthy();
    await fireEvent.click(dom.getByText("Test climb"));
    expect(link.sent).toEqual(["set_route"]);
    expect(link.args).toEqual([{ file: "test-climb.gpx" }]);
    expect(dom.queryByRole("dialog")).toBeNull();
    await fireEvent.click(row);
    await fireEvent.click(dom.getByText("No route"));
    expect(link.args[1]).toEqual({ file: null });
  });

  it("hides the route row when there are no routes", () => {
    render(App, { props: { link: fakeLink(golden("pre_ride")) } });
    expect(dom.queryByText("Route")).toBeNull();
  });

  it("shows the ride along the route on the Summary", () => {
    render(App, { props: { link: fakeLink(golden("summary_route_working")) } });
    expect(dom.getByText("Route: Lake loop")).toBeTruthy();
    expect(dom.getByText(/Working out the ride/)).toBeTruthy();
    cleanup();
    render(App, { props: { link: fakeLink(golden("summary_route")) } });
    expect(dom.getByText("32.5 km · 402 m up")).toBeTruthy();
    cleanup();
    render(App, { props: { link: fakeLink(golden("summary")) } });
    expect(dom.queryByText(/Route:/)).toBeNull();
  });

  it("edits the rider's weight in Settings", async () => {
    const link = fakeLink(golden("settings_defaults"));
    render(App, { props: { link } });
    await fireEvent.click(dom.getByText("Weight, for routes"));
    await fireEvent.click(dom.getByLabelText("Weight, for routes down"));
    await fireEvent.click(dom.getByText("Save"));
    expect(link.args).toEqual([{ key: "rider_kg", value: 74 }]);
  });
});

describe("S-DSP-08 gallery", () => {
  const files = readdirSync(GOLDEN).filter((n) => n.endsWith(".view.json"));

  it("holds every golden view and the plans of the Pre-ride states", () => {
    expect(Object.keys(GOLDEN_VIEWS).sort()).toEqual(files.map(nameOf).sort());
    expect(Object.keys(GOLDEN_PLANS)).toContain("builtin:test-3030@250");
    const groups = galleryStates(GOLDEN_VIEWS);
    expect(groups.map((g) => g.screen)).toEqual(
      ["calibration", "history", "home", "pre_ride", "ride", "settings", "summary"]);
    expect(groups.flatMap((g) => g.names)).toHaveLength(files.length);
  });

  it("finds a state by its hash", () => {
    expect(stateOf("#gallery", GOLDEN_VIEWS)).toBeNull();
    expect(stateOf("#gallery/nope", GOLDEN_VIEWS)).toBeNull();
    expect(stateOf("#gallery/ride_erg", GOLDEN_VIEWS)?.screen.name).toBe("ride");
  });

  it("lists the states, shows one through the real screens and sends nothing", async () => {
    const socket = vi.fn();
    vi.stubGlobal("WebSocket", socket);
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    location.hash = "#gallery";
    render(Gallery, { props: { views: GOLDEN_VIEWS, plans: GOLDEN_PLANS } });
    expect(dom.getByText("ride_battery_low").getAttribute("href")).toBe("#gallery/ride_battery_low");
    location.hash = "#gallery/pre_ride_routes";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await vi.waitFor(() => expect(dom.getByText("Start ride")).toBeTruthy());
    expect(dom.getByText("Warm-up and 3 x 30/30")).toBeTruthy();
    await fireEvent.click(dom.getByText("Back"));
    expect(info).toHaveBeenCalledWith("gallery: not sent", "back");
    expect(socket).not.toHaveBeenCalled();
  });
});
