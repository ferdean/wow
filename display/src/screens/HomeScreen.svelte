<script lang="ts">
  import type { CommandName, HomeScreen, Riders, Warning, WorkoutCard } from "../types/protocol";
  import { FREE_RIDE_SHARE, dateTime, gone, listDuration, shape, sharedRider } from "../format";
  import Banner from "../ui/Banner.svelte";

  interface Props {
    screen: HomeScreen;
    warnings: Warning[];
    send: (name: CommandName, args?: Record<string, unknown>) => void;
    riders?: Riders | null;
    switchRider?: () => void;
  }
  let { screen, warnings, send, riders = null, switchRider = () => undefined }: Props = $props();

  const rider = $derived(sharedRider(riders));

  const offline = $derived(warnings.find((w) => w.kind === "workouts_offline"));
  const storage = $derived(warnings.find((w) => w.kind === "storage_low"));
  const spinDown = $derived(warnings.some((w) => w.kind === "spindown_requested"));
  const certificate = $derived(warnings.find((w) => w.kind === "cert_expiring"));
  const unsynced = $derived(warnings.some((w) => w.kind === "clock_unsynced"));
  const recovery = $derived(screen.recovery);
  const sections = $derived(
    [
      { title: "Today", cards: screen.today, empty: "Nothing planned for today." },
      { title: "Library", cards: screen.library, empty: null },
      { title: "Built in", cards: screen.builtin, empty: "No workouts." },
    ].filter((s) => s.cards.length > 0 || s.empty !== null),
  );

  function sketch(card: WorkoutCard): { points: string; zone: number }[] {
    const parts = card.sketch ?? [];
    const total = parts.reduce((sum, p) => sum + p.duration, 0) || 1;
    const top = card.max_power || 1;
    let x = 0;
    return parts.map((p) => {
      const w = (p.duration / total) * 1000;
      const free = p.zone === 0;
      const part = {
        points: shape(x, w - 2, free ? FREE_RIDE_SHARE * 40 : (p.start_power / top) * 40,
                      free ? FREE_RIDE_SHARE * 40 : (p.end_power / top) * 40, 40),
        zone: p.zone,
      };
      x += w;
      return part;
    });
  }
</script>

<div class="page fixed">
  <h1>WitchesOnWheels</h1>
  {#if rider !== null && riders}
    <div class="row rider">
      <span class="grow"><span class="who">{rider}</span> <span class="label">FTP {riders.ftp} W</span></span>
      <button class="secondary small" onclick={switchRider}>Switch rider</button>
    </div>
  {/if}
  {#if offline && offline.kind === "workouts_offline"}
    <Banner tone="warning" text={`intervals.icu out of reach. Workouts from ${dateTime(offline.downloaded_utc)}.`} />
  {/if}
  {#if storage && storage.kind === "storage_low"}
    <Banner tone="warning" text={`Only ${storage.free_mb} MB free on the Pi. Delete old rides in Past rides.`} />
  {/if}
  {#if spinDown}
    <Banner tone="warning" text="The trainer asks for a calibration." />
  {/if}
  {#if certificate && certificate.kind === "cert_expiring"}
    <Banner tone="warning" text={`The page's certificate ends in ${certificate.days_left} days. Renew it on the laptop.`} />
  {/if}
  {#if unsynced}
    <Banner tone="warning" text="The Pi's clock isn't set yet. Ride times may be off." />
  {/if}
  {#if recovery}
    <div class="panel recovery">
      <h2>A ride stopped unexpectedly</h2>
      <p class="label">
        Started {recovery.started_utc ? dateTime(recovery.started_utc) : "earlier"}.
        {recovery.outage === null
          ? "The Pi's clock wasn't set, so the gap is unknown: the ride can only be finished."
          : `The app was gone for ${gone(recovery.outage)}; continuing records that as a dropout.`}
      </p>
      <div class="row">
        {#if recovery.can_continue}
          <button class="primary grow" onclick={() => send("recovery_continue")}>Continue ride</button>
        {/if}
        <button class="grow" onclick={() => send("recovery_finish")}>Finish ride</button>
      </div>
    </div>
  {/if}
  <div class="scroll">
    {#each sections as section (section.title)}
      <h2>{section.title}</h2>
      {#each section.cards as card (card.ref)}
        <button class="card panel" disabled={!card.rideable} onclick={() => send("open_workout", { ref: card.ref })}>
          <span class="row">
            <span class="name grow">{card.name}</span>
            <span class="label duration">{card.rideable ? listDuration(card.duration) : "Can't be ridden here"}</span>
          </span>
          {#if card.sketch}
            <svg viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden="true">
              {#each sketch(card) as part, i (i)}
                <polygon points={part.points} fill={part.zone ? `var(--zone-${part.zone})` : "var(--rise)"} />
              {/each}
            </svg>
          {/if}
        </button>
      {:else}
        <p class="label">{section.empty}</p>
      {/each}
    {/each}
  </div>
  <div class="more">
    <button onclick={() => send("open_free_ride")}>Free ride</button>
    <button onclick={() => send("open_history")}>Past rides</button>
    <button class:primary={spinDown} onclick={() => send("open_calibration")}>Calibrate</button>
    <button onclick={() => send("open_settings")}>Settings</button>
  </div>
</div>

<style>
  .card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    text-align: left;
    width: 100%;
    min-height: 96px;
    padding: 14px 16px;
  }
  .duration {
    white-space: nowrap;
  }
  .name {
    font-size: 20px;
    font-weight: 700;
  }
  svg {
    width: 100%;
    height: 32px;
  }
  .more {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--gap);
  }
  .more button {
    min-width: 0;
  }
  .recovery {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .recovery h2,
  .recovery p {
    margin: 0;
  }
  .who {
    font-size: 20px;
    font-weight: 700;
  }
</style>
