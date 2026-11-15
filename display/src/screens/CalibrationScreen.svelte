<script lang="ts">
  import type { CalibrationScreen, CommandName } from "../types/protocol";
  import { clock, dateTime, speed } from "../format";
  import { holdScreen } from "../device/wake.svelte";

  interface Props {
    screen: CalibrationScreen;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, send }: Props = $props();

  const running = $derived(["starting", "speed_up", "stop_pedaling"].includes(screen.phase));
  const top = $derived(screen.band_kmh?.[1] ?? null);
  const instruction = $derived.by(() => {
    switch (screen.phase) {
      case "starting":
        return "Asking the trainer…";
      case "speed_up":
        return top === null ? "Speed up gently." : `Speed up gently past ${top.toFixed(0)} km/h. No sprint.`;
      case "stop_pedaling":
        return "Stop pedaling. Let the wheel run down.";
      case "success":
        return "Calibration done.";
      case "error":
        return "The trainer reported a failed calibration. Try again, with a gentler speed-up.";
      case "timeout":
        return "No result within 2 minutes: calibration failed.";
      default:
        return "Warm up for 10 minutes first. Then the trainer guides you: speed up, then stop pedaling.";
    }
  });
  const blocked = $derived(
    screen.blocked === "ride_running"
      ? "Finish the ride first."
      : screen.blocked === "trainer_missing"
        ? "Waiting for the trainer…"
        : null,
  );
</script>

<div class="page fixed">
  <div class="row">
    <button class="secondary small" disabled={running} onclick={() => send("back")}>Back</button>
  </div>
  <h1>Calibration</h1>
  <div class="band" class:stop={screen.phase === "stop_pedaling"} class:good={screen.phase === "success"}
       class:bad={screen.phase === "error" || screen.phase === "timeout"}>
    <p class="title">{instruction}</p>
    {#if running && screen.phase !== "starting"}
      <span class="number hero">{speed(screen.speed_kmh)}<span class="unit">km/h</span></span>
      <span class="label">{clock(screen.elapsed)}</span>
    {/if}
  </div>
  {#if screen.last}
    <p class="label">Last calibration {dateTime(screen.last.utc)}: {screen.last.ok ? "done" : "failed"}</p>
  {/if}
  <div class="grow"></div>
  {#if blocked}
    <p class="label">{blocked}</p>
  {/if}
  {#if running}
    <button class="secondary" onclick={() => send("calibration_cancel")}>Cancel</button>
  {:else}
    <button class="primary" disabled={blocked !== null} onclick={() => { void holdScreen(); send("calibration_start"); }}>
      {screen.phase === "idle" ? "Start calibration" : "Calibrate again"}
    </button>
  {/if}
</div>

<style>
  .band {
    border-radius: 22px;
    padding: 18px;
    background: var(--dusk);
    border: 2px solid var(--line);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .band.stop {
    background: var(--warning);
    color: var(--ink);
  }
  .band.good {
    background: var(--zone-2);
    color: var(--ink);
  }
  .band.bad {
    background: var(--fault);
    color: var(--ink);
  }
  .title {
    margin: 0;
    font-size: 24px;
    font-weight: 750;
  }
  .hero {
    font-size: 120px;
  }
</style>
