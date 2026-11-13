import { describe, expect, it } from "vitest";
import { clock, countdown, listDuration, percent, shape, stepText, watts, zoneColour } from "./format";
import { best, sample } from "./link/offset";

describe("formatting (3C)", () => {
  it("formats values and missing values", () => {
    expect(watts(331.4)).toBe("331");
    expect(watts(null)).toBe("––");
    expect(clock(65)).toBe("1:05");
    expect(clock(3725)).toBe("1:02:05");
    expect(listDuration(2100)).toBe("35 min");
    expect(listDuration(3900)).toBe("1 h 05");
    expect(listDuration(null)).toBe("");
    expect(percent(null)).toBe("?");
    expect(percent(45)).toBe("45 %");
    expect(zoneColour(3)).toBe("var(--zone-3)");
    expect(zoneColour(null)).toBe("var(--rise)");
    expect(countdown(4.2)).toBe("5");
    expect(countdown(6)).toBeNull();
    expect(countdown(0)).toBeNull();
  });

  it("takes the clock offset from the shortest round trip of the last minute", () => {
    const old = sample(0, 10, 1000);
    const slow = sample(70_000, 70_080, 71_000);
    const fast = sample(71_000, 71_020, 72_000);
    expect(fast.offset_ms).toBe(72_000 - 71_010);
    expect(best([old, slow, fast], 72_000)).toEqual(fast);
    expect(best([old], 72_000)).toBeNull();
  });
});

describe("step text and shapes (SL-04)", () => {
  it("writes ramps, free ride and unsupported steps", () => {
    expect(stepText({ duration: 60, kind: "erg", start_power: 120, end_power: 120 })).toBe("1 min at 120 W");
    expect(stepText({ duration: 90, kind: "erg", start_power: 120, end_power: 200 })).toBe("90 s 120→200 W");
    expect(stepText({ duration: 300, kind: "free_ride", start_power: null, end_power: null })).toBe("5 min free ride");
    expect(stepText({ duration: 30, kind: "unsupported", start_power: null, end_power: null })).toBe("30 s not supported");
    expect(shape(10, 20, 40, 80, 100)).toBe("10,100 10,60 30,20 30,100");
  });
});
