<script lang="ts">
  import type { CommandName, SummaryScreen } from "../types/protocol";
  import { UPLOAD_WORDS, clock, dateTime, fixed, watts } from "../format";

  interface Props {
    screen: SummaryScreen;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, send }: Props = $props();

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
    <p class="label">{UPLOAD_WORDS[screen.upload] ?? screen.upload}</p>
  </div>
  <button class="primary" onclick={() => send("back")}>Done</button>
</div>

<style>
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
</style>
