<script lang="ts">
  import type { RouteMap } from "../types/protocol";
  import { PROFILE_HEIGHT, PROFILE_WIDTH, heightOf, placeAt, profileArea, profileX } from "../route";

  interface Props {
    map: RouteMap;
    at: number;
  }
  let { map, at }: Props = $props();

  const area = $derived(profileArea(map));
  const x = $derived(profileX(map, at));
  const y = $derived(heightOf(map, placeAt(map, at).ele));
</script>

<div class="elevation">
  <svg viewBox={`0 0 ${PROFILE_WIDTH} ${PROFILE_HEIGHT}`} preserveAspectRatio="none" role="img"
    aria-label="Elevation profile">
    <defs>
      <clipPath id="route-done"><rect x="0" y="0" width={x} height={PROFILE_HEIGHT} /></clipPath>
    </defs>
    <polygon points={area} class="ahead" />
    <polygon points={area} class="behind" clip-path="url(#route-done)" />
    <line x1={x} x2={x} y1="0" y2={PROFILE_HEIGHT} class="marker" />
  </svg>
  <span class="here" style:left={`${(x / PROFILE_WIDTH) * 100}%`} style:top={`${(y / PROFILE_HEIGHT) * 100}%`}></span>
  <span class="label top">{Math.round(map.ele_max)} m</span>
  <span class="label bottom">{Math.round(map.ele_min)} m</span>
</div>

<style>
  .elevation {
    position: relative;
    height: 100%;
  }
  svg {
    width: 100%;
    height: 100%;
    display: block;
  }
  .ahead {
    fill: var(--rise);
  }
  .behind {
    fill: var(--line);
  }
  .marker {
    stroke: var(--moon);
    stroke-width: 4;
    vector-effect: non-scaling-stroke;
  }
  .here {
    position: absolute;
    width: 16px;
    height: 16px;
    margin: -8px 0 0 -8px;
    border-radius: 50%;
    background: var(--zone-2);
    border: 3px solid var(--moon);
  }
  .top,
  .bottom {
    position: absolute;
    left: 8px;
    font-size: 13px;
  }
  .top {
    top: 4px;
  }
  .bottom {
    bottom: 4px;
  }
</style>
