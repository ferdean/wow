<script lang="ts">
  import type { RouteMap } from "../types/protocol";
  import { donePath, placeAt, wholePath } from "../route";

  interface Props {
    map: RouteMap;
    at: number;
  }
  let { map, at }: Props = $props();

  const PAD = 70;
  const width = $derived(Math.max(map.width, 1) + 2 * PAD);
  const height = $derived(Math.max(map.height, 1) + 2 * PAD);
  const road = $derived(wholePath(map));
  const done = $derived(donePath(map, at));
  const here = $derived(placeAt(map, at));
  const start = $derived(map.points[0]);
</script>

<svg class="map" viewBox={`${-PAD} ${-PAD} ${width} ${height}`} preserveAspectRatio="xMidYMid meet" role="img"
  aria-label={`Map of ${map.name}`}>
  <defs>
    <pattern id="route-dots" width="60" height="60" patternUnits="userSpaceOnUse">
      <circle cx="30" cy="30" r="3" class="dot-grid" />
    </pattern>
  </defs>
  <rect x={-PAD} y={-PAD} {width} {height} fill="url(#route-dots)" />
  <path d={road} class="verge" />
  <path d={road} class="road" />
  {#if done}<path d={done} class="done" />{/if}
  {#if start}<rect x={start[1] - 14} y={start[2] - 14} width="28" height="28" rx="6" class="start" />{/if}
  <circle cx={here.x} cy={here.y} r="40" class="halo" />
  <circle cx={here.x} cy={here.y} r="20" class="rider" />
</svg>

<style>
  .map {
    width: 100%;
    height: 100%;
    display: block;
  }
  .dot-grid {
    fill: var(--rise);
  }
  path {
    fill: none;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .verge {
    stroke: var(--rise);
    stroke-width: 44;
  }
  .road {
    stroke: var(--line);
    stroke-width: 14;
  }
  .done {
    stroke: var(--moon);
    stroke-width: 16;
  }
  .start {
    fill: var(--night);
    stroke: var(--moon);
    stroke-width: 6;
  }
  .halo {
    fill: var(--zone-2);
    opacity: 0.3;
  }
  .rider {
    fill: var(--zone-2);
    stroke: var(--moon);
    stroke-width: 6;
  }
</style>
