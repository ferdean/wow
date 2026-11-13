<script lang="ts">
  import type { CommandName, LinkState, Plan, RideScreen, Warning } from "../types/protocol";
  import { clock, countdown, watts, zoneColour } from "../format";
  import Banner from "../ui/Banner.svelte";
  import Heart from "../ui/Heart.svelte";
  import Profile from "../ui/Profile.svelte";
  import Sheet from "../ui/Sheet.svelte";
  import StatusLine from "../ui/StatusLine.svelte";
  import { releaseScreen } from "../device/wake";

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

  let confirming = $state(false);

  const running = $derived(!screen.waiting_for_power && !screen.paused);
  const elapsed = $derived(screen.elapsed + (running ? since : 0));
  const left = $derived(screen.step === null ? 0 : Math.max(0, screen.step.left - (running ? since : 0)));
  const remaining = $derived(screen.remaining === null ? null : Math.max(0, screen.remaining - (running ? since : 0)));
  const count = $derived(countdown(left));
  const lost = $derived(links.trainer === "dropout");
  const banners = $derived(
    [
      lost ? { tone: "fault" as const, text: "Trainer lost. Reconnecting; the ride carries on." } : null,
      warnings.some((w) => w.kind === "trainer_not_responding")
        ? { tone: "warning" as const, text: "Trainer isn't answering. Still trying." }
        : null,
      warnings.some((w) => w.kind === "control_refused")
        ? { tone: "warning" as const, text: "Another app has the trainer. Taking control back." }
        : null,
    ].filter((b) => b !== null),
  );

  function finish(): void {
    confirming = false;
    void releaseScreen();
    send("finish");
  }
</script>

<div class="page fixed">
  <StatusLine trainer={links.trainer} hrm={links.hrm} {battery} />
  {#each banners as banner (banner.text)}
    <Banner tone={banner.tone} text={banner.text} />
  {/each}

  {#if screen.waiting_for_power}
    <div class="band neutral waiting">
      <div class="title">Start pedaling</div>
      <div class="label">The trainer is set to</div>
      <div class="number key">{watts(screen.target)}<span class="unit">W</span></div>
    </div>
    <p class="explain">Recording and the ride clock start with your first pedal stroke.</p>
    <div class="times"><span class="number small">{clock(0)}</span><span class="label">ridden</span></div>
    <div class="grow"></div>
    <button class="secondary" onclick={() => send("cancel_start")}>Cancel</button>
  {:else if screen.workout_done}
    <div class="band neutral done">
      <div class="title">Workout done</div>
      <div class="number hero">{watts(screen.power)}<span class="unit">W</span></div>
      <div class="label">Keep spinning as long as you like, or finish the ride.</div>
    </div>
    <div class="cells">
      <div class="cell"><span class="label">Heart rate</span><span class="number key">{watts(screen.hr_bpm)}<Heart /></span></div>
      <div class="cell"><span class="label">Ride time</span><span class="number key">{clock(elapsed)}</span></div>
    </div>
    <div class="profile grow"><Profile {plan} {elapsed} /></div>
    <button class="primary" onclick={() => (confirming = true)}>Finish ride</button>
  {:else}
    <div class="band" class:lost style:background={lost ? "var(--rise)" : zoneColour(screen.target_zone)}>
      <div class="power">
        <span class="label">Power</span>
        <span class="number hero">{lost ? "––" : watts(screen.power)}<span class="unit">W</span></span>
      </div>
      <div class="target">
        <span class="label">Target</span>
        <span class="number key">{watts(screen.target)}</span>
        {#if screen.target_limited}<span class="limit">limit</span>{/if}
      </div>
    </div>
    <div class="cue label">
      <span class="grow">{screen.step?.text ?? ""}</span>
      {#if screen.step}<span>Step {screen.step.index + 1} of {screen.step.count}</span>{/if}
    </div>
    <div class="cells">
      <div class="cell"><span class="label">Heart rate</span><span class="number key">{watts(screen.hr_bpm)}<Heart /></span></div>
      <div class="cell" class:counting={count !== null}>
        <span class="label">Step left</span>
        <span class="number key">{count ?? clock(left)}</span>
      </div>
    </div>
    {#if screen.next}
      <div class="next">
        <span class="label">Next</span>
        <span class="chip" style:background={zoneColour(screen.next.zone)}>{watts(screen.next.target)} W</span>
        <span class="label">for {clock(screen.next.duration)}</span>
      </div>
    {/if}
    <div class="profile grow"><Profile {plan} {elapsed} /></div>
    <div class="times label">
      <span><span class="number small">{clock(elapsed)}</span> ridden</span>
      {#if remaining !== null}<span><span class="number small">{clock(remaining)}</span> to go</span>{/if}
    </div>
    <div class="row">
      <button disabled aria-label="Intensity down">−</button>
      <span class="grow intensity"><span class="number small">{screen.intensity_pct}</span> %</span>
      <button disabled aria-label="Intensity up">+</button>
      <button class="secondary" disabled>Ride by resistance</button>
    </div>
    <div class="row controls">
      <button class="primary grow" disabled>Pause</button>
      <button class="grow" disabled>Skip step</button>
      <button class="grow" onclick={() => (confirming = true)}>Finish</button>
    </div>
  {/if}
</div>

{#if confirming}
  <Sheet title="Finish the ride?" text="The trainer goes to its easiest setting.">
    <button class="primary" onclick={finish}>Finish and save</button>
    <button class="secondary" onclick={() => (confirming = false)}>Keep riding</button>
  </Sheet>
{/if}

<style>
  .band {
    border-radius: 22px;
    padding: 14px 18px;
    color: var(--ink);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    transition: background-color 200ms;
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
    font-size: 132px;
  }
  .key {
    font-size: 74px;
  }
  .small {
    font-size: 30px;
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
    grid-template-columns: 1fr 1fr;
    gap: var(--gap);
  }
  .cell {
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
    min-height: 44px;
  }
  .times {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .intensity {
    text-align: center;
    white-space: nowrap;
  }
  .explain {
    margin: 0;
    color: var(--mist);
  }
</style>
