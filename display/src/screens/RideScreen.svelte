<script lang="ts">
  import type { CommandName, LinkState, Plan, RideScreen, Warning } from "../types/protocol";
  import { HEART_EM, clock, countdown, textEm, timeLeft, watts, zoneColour } from "../format";
  import Banner from "../ui/Banner.svelte";
  import Heart from "../ui/Heart.svelte";
  import Profile from "../ui/Profile.svelte";
  import Sheet from "../ui/Sheet.svelte";
  import StatusLine from "../ui/StatusLine.svelte";
  import { releaseScreen } from "../device/wake.svelte";
  import { tone } from "../device/sound";

  interface Props {
    screen: RideScreen;
    plan: Plan | null;
    links: { trainer: LinkState; hrm: LinkState };
    battery: number | null;
    warnings: Warning[];
    since: number;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, plan, links, battery, warnings, since, send }: Props = $props();

  const SKIP_SHEET_MS = 5000;
  let sheet = $state<"finish" | "discard" | "skip" | null>(null);
  let skipTimer: ReturnType<typeof setTimeout> | undefined;

  const running = $derived(!screen.waiting_for_power && !screen.paused);
  const elapsed = $derived(screen.elapsed + (running ? since : 0));
  const left = $derived(screen.step === null ? 0 : Math.max(0, screen.step.left - (running ? since : 0)));
  const remaining = $derived(screen.remaining === null ? null : Math.max(0, screen.remaining - (running ? since : 0)));
  const planEnd = $derived(plan?.segments.at(-1)?.end ?? 0);
  const position = $derived(remaining === null ? elapsed : planEnd - remaining);
  const count = $derived(countdown(left));
  const lost = $derived(links.trainer === "dropout");
  const free = $derived(!screen.waiting_for_power && !screen.workout_done && screen.step === null);
  const segment = $derived(plan?.segments.find((s) => s.step === screen.step?.index) ?? null);
  const canErg = $derived(free || segment?.kind === "erg");
  const banners = $derived(
    [
      lost ? { tone: "fault" as const, text: "Trainer lost. Reconnecting; the ride carries on." } : null,
      warnings.some((w) => w.kind === "trainer_not_responding")
        ? { tone: "warning" as const, text: "Trainer isn't answering. Still trying." }
        : null,
      warnings.some((w) => w.kind === "control_refused")
        ? { tone: "warning" as const, text: "Another app has the trainer. Taking control back." }
        : null,
      warnings.some((w) => w.kind === "clock_unsynced")
        ? { tone: "warning" as const, text: "The Pi's clock wasn't set at Start. Ride times may be off." }
        : null,
    ].filter((b) => b !== null),
  );
  const batteryLow = $derived(warnings.some((w) => w.kind === "hrm_battery_low"));
  const stepKey = $derived(screen.workout_done ? -1 : (screen.step?.index ?? null));
  let lastStep: number | null | undefined;

  $effect(() => {
    const current = stepKey;
    if (lastStep !== undefined && current !== lastStep && !screen.waiting_for_power && !screen.paused) {
      tone();
    }
    lastStep = current;
  });

  function nextText(next: NonNullable<RideScreen["next"]>): string {
    if (next.kind === "free_ride") {
      return "Free ride";
    }
    return next.target === null ? "Resistance" : `${watts(next.target)} W`;
  }

  function askSkip(): void {
    sheet = "skip";
    clearTimeout(skipTimer);
    skipTimer = setTimeout(() => {
      if (sheet === "skip") {
        sheet = null;
      }
    }, SKIP_SHEET_MS);
  }

  function close(): void {
    clearTimeout(skipTimer);
    sheet = null;
  }

  function confirm(name: "skip" | "finish" | "discard"): void {
    close();
    if (name !== "skip") {
      void releaseScreen();
    }
    send(name);
  }
</script>

<div class="page fixed">
  <StatusLine trainer={links.trainer} hrm={links.hrm} {battery} {batteryLow} />
  {#each banners as banner (banner.text)}
    <Banner tone={banner.tone} text={banner.text} />
  {/each}

  {#if screen.waiting_for_power}
    <div class="band neutral waiting">
      <div class="title">Start pedaling</div>
      <div class="label">The trainer is set to</div>
      <div class="number key">{screen.mode === "resistance" ? `${screen.resistance_pct ?? 0} %` : watts(screen.target)}<span class="unit">{screen.mode === "resistance" ? "level" : "W"}</span></div>
    </div>
    <p class="explain">Recording and the ride clock start with your first pedal stroke.</p>
    <div class="times"><span class="number small">{clock(0)}</span><span class="label">ridden</span></div>
    <div class="grow"></div>
    <button class="secondary" onclick={() => send("cancel_start")}>Cancel</button>
  {:else if screen.mode === "resistance" || screen.workout_done}
    {#if screen.workout_done}
      <div class="band neutral done">
        <div class="title">Workout done</div>
        <div class="label">Keep spinning as long as you like, or finish the ride.</div>
      </div>
    {:else if screen.paused}
      <div class="band neutral"><div class="title">Paused</div></div>
    {/if}
    <div class="info label">
      <span>Power <b class="number">{lost ? "––" : watts(screen.power)}</b> W</span>
      <span>Heart <b class="number">{watts(screen.hr_bpm)}</b></span>
      {#if screen.cadence_rpm !== null}<span>Cadence <b class="number">{screen.cadence_rpm}</b></span>{/if}
      {#if screen.step}<span>Step <b class="number">{count ?? timeLeft(left)}</b></span>{/if}
      {#if segment && segment.kind !== "erg"}<span>Free ride</span>{:else if segment}<span>Plan <b class="number">{watts(segment.start_power)}</b> W</span>{/if}
    </div>
    <div class="number levelnum"><span class="label">Level</span>{screen.resistance_pct ?? 0}<span class="unit">%</span></div>
    <div class="pair">
      <button class="big" aria-label="Resistance down" disabled={screen.paused} onclick={() => send("resistance", { step: -1 })}>−</button>
      <button class="big" aria-label="Resistance up" disabled={screen.paused} onclick={() => send("resistance", { step: 1 })}>+</button>
    </div>
    {#if screen.workout_done}
      <button class="primary" onclick={() => (sheet = "finish")}>Finish ride</button>
    {:else if canErg}
      <button class="primary" disabled={screen.paused} onclick={() => send("switch_mode", { mode: "erg" })}>{free ? "Ride by power" : "Back to ERG"}</button>
    {/if}
    <div class="profile grow"><Profile {plan} elapsed={position} resistanceBlocks={screen.resistance_blocks} /></div>
    <div class="times label">
      <span><span class="number small">{clock(elapsed)}</span> ridden</span>
      {#if remaining !== null}<span><span class="number small">{timeLeft(remaining)}</span> to go</span>{/if}
    </div>
    {#if !screen.workout_done}
      <div class="controls">
        <button class="primary" onclick={() => send(screen.paused ? "resume" : "pause")}>{screen.paused ? "Resume" : "Pause"}</button>
        <button disabled={free || screen.paused} onclick={askSkip}>Skip step</button>
        <button onclick={() => (sheet = "finish")}>Finish</button>
      </div>
    {/if}
  {:else}
    <div class="band" class:lost class:paused={screen.paused} style:background={lost || screen.paused ? "var(--rise)" : zoneColour(screen.target_zone)}>
      <div class="power">
        <span class="label">{screen.paused ? "Paused" : "Power"}</span>
        <span class="number hero">{lost ? "––" : watts(screen.power)}<span class="unit">W</span></span>
      </div>
      <div class="target">
        <span class="label">Target</span>
        <span class="number key">{watts(screen.target)}</span>
        {#if screen.target_limited}<span class="limit">limit</span>{/if}
      </div>
    </div>
    <div class="cue label">
      <span class="grow">{screen.step?.text ?? (free ? "Free ride by power" : "")}</span>
      {#if screen.cadence_rpm !== null}<span>Cadence <b class="number">{screen.cadence_rpm}</b></span>{/if}
      {#if screen.step}<span>Step {screen.step.index + 1} of {screen.step.count}</span>{/if}
    </div>
    <div class="cells">
      <div class="cell"><span class="label">Heart rate</span><span class="number key fit" style:--em={textEm(watts(screen.hr_bpm)) + HEART_EM}>{watts(screen.hr_bpm)}<Heart /></span></div>
      {#if screen.step}
        <div class="cell" class:counting={count !== null}>
          <span class="label">Step left</span>
          <span class="number key fit" style:--em={textEm(count ?? timeLeft(left))}>{count ?? timeLeft(left)}</span>
        </div>
      {:else}
        <div class="cell"><span class="label">Ride time</span><span class="number key fit" style:--em={textEm(clock(elapsed))}>{clock(elapsed)}</span></div>
      {/if}
    </div>
    {#if screen.next}
      <div class="next">
        <span class="label">Next</span>
        <span class="chip" style:background={zoneColour(screen.next.zone)}>{nextText(screen.next)}</span>
        <span class="label">for {clock(screen.next.duration)}</span>
      </div>
    {/if}
    <div class="profile grow"><Profile {plan} elapsed={position} resistanceBlocks={screen.resistance_blocks} /></div>
    <div class="times label">
      <span><span class="number small">{clock(elapsed)}</span> ridden</span>
      {#if remaining !== null}<span><span class="number small">{timeLeft(remaining)}</span> to go</span>{/if}
    </div>
    <div class="adjust">
      {#if free}
        <button aria-label="Power down" onclick={() => send("free_ride_power", { step: -1 })}>−</button>
        <span class="intensity"><span class="number small">{watts(screen.free_ride_target)}</span> W</span>
        <button aria-label="Power up" onclick={() => send("free_ride_power", { step: 1 })}>+</button>
      {:else}
        <button aria-label="Intensity down" disabled={screen.paused} onclick={() => send("intensity", { step: -1 })}>−</button>
        <span class="intensity"><span class="number small">{screen.intensity_pct}</span> %</span>
        <button aria-label="Intensity up" disabled={screen.paused} onclick={() => send("intensity", { step: 1 })}>+</button>
      {/if}
      <button class="secondary" disabled={screen.paused} onclick={() => send("switch_mode", { mode: "resistance" })}>Ride by resistance</button>
    </div>
    <div class="controls">
      <button class="primary" onclick={() => send(screen.paused ? "resume" : "pause")}>{screen.paused ? "Resume" : "Pause"}</button>
      <button disabled={free || screen.paused} onclick={askSkip}>Skip step</button>
      <button onclick={() => (sheet = "finish")}>Finish</button>
    </div>
  {/if}
</div>

{#if sheet === "finish"}
  <Sheet title="Finish the ride?" text="The trainer goes to its easiest setting.">
    <button class="primary" onclick={() => confirm("finish")}>Finish and save</button>
    <button onclick={() => (sheet = "discard")}>Discard ride</button>
    <button class="secondary" onclick={close}>Keep riding</button>
  </Sheet>
{:else if sheet === "discard"}
  <Sheet title="Discard this ride?" text="Nothing is saved or uploaded; the logs stay for debugging.">
    <button class="danger" onclick={() => confirm("discard")}>Discard</button>
    <button class="secondary" onclick={close}>Keep riding</button>
  </Sheet>
{:else if sheet === "skip"}
  <Sheet title="Skip the rest of this step?" text="The next step starts at once.">
    <button class="primary" onclick={() => confirm("skip")}>Skip step</button>
    <button class="secondary" onclick={close}>Keep riding</button>
  </Sheet>
{/if}

<style>
  .page.fixed {
    container-type: size;
  }
  .info {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
  }
  .info b {
    font-size: 26px;
    color: var(--moon);
  }
  .levelnum {
    font-size: clamp(80px, calc((100cqb - 510px) / 0.86), 168px);
    display: flex;
    align-items: baseline;
    justify-content: center;
    position: relative;
  }
  .levelnum .label {
    position: absolute;
    left: 0;
    top: 12px;
    font-size: 15px;
  }
  .big {
    min-height: 120px;
    font-size: 48px;
  }
  button.danger {
    background: var(--fault);
    color: var(--ink);
  }
  .band {
    border-radius: 22px;
    padding: 14px 18px;
    color: var(--ink);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    transition: background-color 200ms;
    container-type: inline-size;
  }
  .band .label {
    color: inherit;
    opacity: 0.8;
  }
  .band.lost {
    color: var(--moon);
    border: 2px dashed var(--line);
  }
  .band.neutral {
    background: var(--dusk);
    color: var(--moon);
    border: 2px solid var(--line);
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .title {
    font-size: 30px;
    font-weight: 780;
  }
  .power,
  .target {
    display: flex;
    flex-direction: column;
  }
  .target {
    align-items: flex-end;
  }
  .hero {
    font-size: clamp(74px, min(calc((100cqi - 141px) / 1.578), calc((100cqb - 505px) / 0.86)), 132px);
  }
  .key {
    font-size: 74px;
  }
  .small {
    font-size: 30px;
  }
  .fit {
    white-space: nowrap;
    font-size: min(74px, calc(100cqi / var(--em)));
  }
  .limit {
    font-size: 15px;
    font-weight: 650;
  }
  .cue {
    display: flex;
    gap: var(--gap);
  }
  .cells {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--gap);
  }
  .cell {
    min-width: 0;
    container-type: inline-size;
    background: var(--dusk);
    border-radius: 18px;
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .cell.counting {
    background: var(--moon);
    color: var(--ink);
  }
  .cell.counting .label {
    color: var(--ink);
  }
  .next {
    display: flex;
    gap: 10px;
    align-items: center;
  }
  .chip {
    color: var(--ink);
    border-radius: 10px;
    padding: 4px 10px;
    font-weight: 700;
  }
  .profile {
    min-height: 0;
    flex-basis: 0;
    overflow: hidden;
  }
  @media (max-height: 700px) {
    .page {
      gap: 6px;
    }
    .band {
      padding: 10px 16px;
    }
    .cell {
      padding: 8px 12px;
      gap: 4px;
    }
  }
  .times {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .adjust {
    display: grid;
    grid-template-columns: 62px minmax(0, 1fr) 62px minmax(0, 1.6fr);
    gap: var(--gap);
    align-items: center;
  }
  .controls {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--gap);
  }
  .pair {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--gap);
  }
  .controls button,
  .adjust button {
    min-width: 0;
    padding: 0 8px;
  }
  .intensity {
    text-align: center;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .explain {
    margin: 0;
    color: var(--mist);
  }
</style>
