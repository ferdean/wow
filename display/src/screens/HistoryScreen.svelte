<script lang="ts">
  import type { CommandName, HistoryScreen } from "../types/protocol";
  import { GARMIN_WORDS, MISSING, UPLOAD_WORDS, clock, dateTime, fixed } from "../format";

  const BAD = ["failed", "auth_error"];

  interface Props {
    screen: HistoryScreen;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, send }: Props = $props();
</script>

<div class="page fixed">
  <div class="row">
    <button class="secondary small" onclick={() => send("back")}>Back</button>
  </div>
  <h1>Past rides</h1>
  <p class="label">{(screen.free_mb / 1000).toFixed(1)} GB free on the Pi</p>
  <div class="scroll">
    {#each screen.rides as ride (ride.ride_id)}
      <button class="panel ride" onclick={() => send("open_ride", { ride_id: ride.ride_id })}>
        <span class="row">
          <span class="name grow">{ride.title}</span>
          <span class="label">{ride.start_utc ? dateTime(ride.start_utc) : ride.ride_id}</span>
        </span>
        <span class="row label">
          <span>{ride.duration === null ? MISSING : clock(ride.duration)}</span>
          <span>TSS {fixed(ride.tss, 0)}</span>
          <span class="grow upload" class:bad={BAD.includes(ride.upload)}>
            {UPLOAD_WORDS[ride.upload] ?? ride.upload}
          </span>
        </span>
        {#if ride.garmin_upload !== null}
          <span class="row label">
            <span class="grow upload" class:bad={BAD.includes(ride.garmin_upload)}>
              {GARMIN_WORDS[ride.garmin_upload] ?? ride.garmin_upload}
            </span>
          </span>
        {/if}
      </button>
    {:else}
      <p class="label">No rides yet.</p>
    {/each}
  </div>
</div>

<style>
  .ride {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
    text-align: left;
    padding: 12px 16px;
  }
  .name {
    font-size: 20px;
    font-weight: 700;
  }
  .upload {
    text-align: right;
  }
  .bad {
    color: var(--warning);
  }
</style>
