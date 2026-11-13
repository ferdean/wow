<script lang="ts">
  import type { CommandName, HomeScreen, Warning, WorkoutCard } from "../types/protocol";
  import { FREE_RIDE_SHARE, dateTime, listDuration, shape } from "../format";
  import Banner from "../ui/Banner.svelte";

  interface Props {
    screen: HomeScreen;
    warnings: Warning[];
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, warnings, send }: Props = $props();

  const offline = $derived(warnings.find((w) => w.kind === "workouts_offline"));
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
  {#if offline && offline.kind === "workouts_offline"}
    <Banner tone="warning" text={`intervals.icu out of reach. Workouts from ${dateTime(offline.downloaded_utc)}.`} />
  {/if}
  <div class="scroll">
    {#each sections as section (section.title)}
      <h2>{section.title}</h2>
      {#each section.cards as card (card.ref)}
        <button class="card panel" disabled={!card.rideable} onclick={() => send("open_workout", { ref: card.ref })}>
          <span class="row">
            <span class="name grow">{card.name}</span>
            <span class="label">{card.rideable ? listDuration(card.duration) : "Can't be ridden here"}</span>
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
  <div class="row more">
    <button class="grow" disabled>Free ride</button>
    <button class="grow" disabled>Past rides</button>
    <button class="grow" disabled>Settings</button>
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
  .name {
    font-size: 20px;
    font-weight: 700;
  }
  svg {
    width: 100%;
    height: 32px;
  }
  .more button {
    min-width: 0;
  }
</style>
