<script lang="ts">
  import type { Plan } from "../types/protocol";
  import { FREE_RIDE_SHARE, shape } from "../format";

  interface Props {
    plan: Plan | null;
    elapsed?: number | null;
  }
  let { plan, elapsed = null }: Props = $props();

  const total = $derived(plan?.segments.at(-1)?.end ?? 0);
  const top = $derived(Math.max(1, ...(plan?.segments.map((s) => Math.max(s.start_power ?? 0, s.end_power ?? 0)) ?? [1])));
  const position = $derived(elapsed === null || total === 0 ? null : Math.min(1, elapsed / total) * 1000);
</script>

{#if plan && total > 0}
  <svg class="profile" viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label="Workout profile">
    {#each plan.segments as s (s.step)}
      <polygon
        points={shape(
          (s.start / total) * 1000,
          ((s.end - s.start) / total) * 1000 - 1.5,
          s.kind === "erg" ? ((s.start_power ?? 0) / top) * 96 : FREE_RIDE_SHARE * 96,
          s.kind === "erg" ? ((s.end_power ?? s.start_power ?? 0) / top) * 96 : FREE_RIDE_SHARE * 96,
          100,
        )}
        fill={s.zone ? `var(--zone-${s.zone})` : "var(--rise)"}
        opacity={position !== null && (s.end / total) * 1000 <= position ? 0.35 : 1}
      />
    {/each}
    {#if position !== null}
      <rect class="marker" x={position - 2} width="4" y="0" height="100" />
    {/if}
  </svg>
{/if}

<style>
  .profile {
    display: block;
    width: 100%;
    height: 100%;
    min-height: 44px;
  }
  .marker {
    fill: var(--moon);
  }
</style>
