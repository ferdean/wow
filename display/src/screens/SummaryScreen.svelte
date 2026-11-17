<script lang="ts">
  import type { CommandName, SummaryScreen } from "../types/protocol";
  import { UPLOAD_WORDS, clock, dateTime, fixed, km, watts } from "../format";
  import Sheet from "../ui/Sheet.svelte";

  interface Props {
    screen: SummaryScreen;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, send }: Props = $props();

  const RETRY_WORDS: Record<string, string> = {
    off: "Upload now", failed: "Try again", auth_error: "Try again", retrying: "Try now", done: "Upload again",
  };
  let deleting = $state(false);
  const retry = $derived(RETRY_WORDS[screen.upload] ?? null);

  const m = $derived(screen.metrics);
  const zoneTotal = $derived(m.time_in_zone.reduce((a, b) => a + b, 0) || 1);
  const cells = $derived([
    ["Ride time", clock(m.duration)],
    ["Average power", `${watts(m.avg_power)} W`],
    ["Normalized power", `${watts(m.np)} W`],
    ["Highest power", `${watts(m.max_power)} W`],
    ["Intensity factor", fixed(m.intensity_factor, 2)],
    ["TSS", fixed(m.tss, 0)],
    ["Work", `${fixed(m.work_kj, 0)} kJ`],
    ["Heart rate", `${watts(m.avg_hr_bpm)} / ${watts(m.max_hr_bpm)}`],
  ]);
</script>

<div class="page fixed">
  <div class="scroll">
    <h1>{screen.title}</h1>
    <div class="label">{dateTime(screen.start_utc)}</div>
    {#if screen.route !== null}
      <div class="panel route">
        <span class="label">Route: {screen.route.name}</span>
        {#if screen.route.distance_m === null}
          <span>The route couldn't be read, so this ride has no distance.</span>
        {:else}
          <span class="number small">{km(screen.route.distance_m)} · {screen.route.ascent_m ?? 0} m up</span>
        {/if}
      </div>
    {/if}
    <div class="grid">
      {#each cells as [label, value] (label)}
        <div class="panel cell"><span class="label">{label}</span><span class="number small">{value}</span></div>
      {/each}
    </div>
    <div class="label">Time in zones</div>
    <div class="zones" role="img" aria-label="Time in zones">
      {#each m.time_in_zone as seconds, i (i)}
        <span style:flex-grow={seconds / zoneTotal} style:background={`var(--zone-${i + 1})`}></span>
      {/each}
    </div>
    <div class="row upload">
      <span class="label grow">{UPLOAD_WORDS[screen.upload] ?? screen.upload}</span>
      {#if retry}
        <button class="small" onclick={() => send("upload_retry", { ride_id: screen.ride_id })}>{retry}</button>
      {/if}
    </div>
    <a class="button" href={`/rides/${screen.ride_id}/ride.fit`} download>Download FIT file</a>
    {#if screen.past}
      <button class="secondary" onclick={() => (deleting = true)}>Delete ride</button>
    {/if}
  </div>
  <button class="primary" onclick={() => send("back")}>{screen.past ? "Back" : "Done"}</button>
</div>

{#if deleting}
  <Sheet title="Delete this ride?" text="Its FIT file and logs go; intervals.icu keeps what it already has.">
    <button class="danger" onclick={() => { deleting = false; send("delete_ride", { ride_id: screen.ride_id }); }}>Delete</button>
    <button class="secondary" onclick={() => (deleting = false)}>Keep</button>
  </Sheet>
{/if}

<style>
  .route {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--gap);
  }
  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .zones {
    display: flex;
    height: 24px;
    border-radius: 8px;
    overflow: hidden;
  }
  .zones span {
    flex-basis: 0;
  }
  .upload {
    align-items: center;
  }
  a.button {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 62px;
    border-radius: 16px;
    border: 2px solid var(--line);
    color: var(--moon);
    text-decoration: none;
    font-weight: 650;
    font-size: 20px;
  }
  button.danger {
    background: var(--fault);
    color: var(--ink);
  }
</style>
