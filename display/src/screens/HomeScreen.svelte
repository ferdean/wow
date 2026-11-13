<script lang="ts">
  import type { CommandName, HomeScreen, WorkoutCard } from "../types/protocol";
  import { listDuration } from "../format";

  interface Props {
    screen: HomeScreen;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, send }: Props = $props();

  function sketch(card: WorkoutCard): { x: number; w: number; h: number; zone: number }[] {
    const parts = card.sketch ?? [];
    const total = parts.reduce((sum, p) => sum + p.duration, 0) || 1;
    const top = card.max_power ?? 1;
    let x = 0;
    return parts.map((p) => {
      const part = { x, w: (p.duration / total) * 1000, h: (p.start_power / top) * 40, zone: p.zone };
      x += part.w;
      return part;
    });
  }
</script>

<div class="page fixed">
  <h1>WitchesOnWheels</h1>
  <div class="scroll">
    <h2>Built in</h2>
    {#each screen.builtin as card (card.ref)}
      <button class="card panel" disabled={!card.rideable} onclick={() => send("open_workout", { ref: card.ref })}>
        <span class="row"><span class="name grow">{card.name}</span><span class="label">{listDuration(card.duration)}</span></span>
        <svg viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden="true">
          {#each sketch(card) as part, i (i)}
            <rect x={part.x} width={Math.max(1, part.w - 2)} y={40 - part.h} height={part.h} fill={`var(--zone-${part.zone})`} />
          {/each}
        </svg>
      </button>
    {:else}
      <p class="label">No workouts.</p>
    {/each}
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
</style>
