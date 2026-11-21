// S-RDR-12: riders who share the trainer (riders.md): who rides, chosen on
// the start screen, named on Home and Settings; one rider sees no change.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen as dom } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App.svelte";
import { sharedRider } from "./format";
import Gallery from "./gallery/Gallery.svelte";
import { GOLDEN_PLANS, GOLDEN_VIEWS } from "./gallery/load";
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
});

describe("S-RDR-12 riders", () => {
  it("names the rider riding now only when there are several", () => {
    const riders = golden("home_riders").riders;
    expect(sharedRider(riders)).toBe("Anna");
    expect(sharedRider(undefined)).toBeNull();
    expect(sharedRider({ active: "ferran", ftp: 250, list: [{ id: "ferran", name: "Ferran" }] })).toBeNull();
    expect(sharedRider({ active: "bob", ftp: 250, list: [{ id: "a", name: "A" }, { id: "b", name: "B" }] }))
      .toBeNull();
  });

  it("asks who rides and sends the choice when it changes", async () => {
    const link = fakeLink(golden("start_riders"));
    render(App, { props: { link, greet: true } });
    expect(dom.getByText("Who's riding?")).toBeTruthy();
    expect(dom.queryByText("Start")).toBeNull();
    await fireEvent.click(dom.getByText("Ferran"));
    expect(link.sent).toEqual(["rider_choose"]);
    expect(link.args).toEqual([{ rider: "ferran" }]);
    expect(dom.getByText("Free ride")).toBeTruthy();
  });

  it("sends nothing when the rider riding now taps their name", async () => {
    const link = fakeLink(golden("start_riders"));
    render(App, { props: { link, greet: true } });
    await fireEvent.click(dom.getByText("Anna"));
    expect(link.sent).toEqual([]);
    expect(dom.getByText("FTP 205 W")).toBeTruthy();
  });

  it("names the rider on Home and goes back to the choice", async () => {
    render(App, { props: { link: fakeLink(golden("home_riders")), greet: true } });
    await fireEvent.click(dom.getByText("Anna"));
    await fireEvent.click(dom.getByText("Switch rider"));
    expect(dom.getByText("Who's riding?")).toBeTruthy();
  });

  it("names the rider on Settings", () => {
    render(App, { props: { link: fakeLink(golden("settings_riders")) } });
    expect(dom.getByText("Settings for Anna")).toBeTruthy();
    expect(dom.getByText("Sign in once on the Pi: wow-garmin --rider anna login.")).toBeTruthy();
  });

  it("shows one rider's pages as before", async () => {
    render(App, { props: { link: fakeLink(golden("home")), greet: true } });
    expect(dom.getByText("Connected to the Pi.")).toBeTruthy();
    await fireEvent.click(dom.getByText("Start"));
    expect(dom.queryByText("Switch rider")).toBeNull();
    cleanup();
    render(App, { props: { link: fakeLink(golden("settings_defaults")) } });
    expect(dom.getByText("Settings")).toBeTruthy();
    expect(dom.getByText("Sign in once on the Pi: wow-garmin login.")).toBeTruthy();
  });

  it("opens the gallery's start states on the start screen", () => {
    location.hash = "#gallery/start_riders";
    render(Gallery, { props: { views: GOLDEN_VIEWS, plans: GOLDEN_PLANS } });
    expect(dom.getByText("Who's riding?")).toBeTruthy();
    cleanup();
    location.hash = "#gallery/home_riders";
    render(Gallery, { props: { views: GOLDEN_VIEWS, plans: GOLDEN_PLANS } });
    expect(dom.getByText("Switch rider")).toBeTruthy();
  });
});
