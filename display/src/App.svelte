<script lang="ts">
  import { onMount } from "svelte";
  import type { LinkView } from "./link/link.svelte";
  import CalibrationScreen from "./screens/CalibrationScreen.svelte";
  import HistoryScreen from "./screens/HistoryScreen.svelte";
  import HomeScreen from "./screens/HomeScreen.svelte";
  import LaterScreen from "./screens/LaterScreen.svelte";
  import PreRideScreen from "./screens/PreRideScreen.svelte";
  import RideScreen from "./screens/RideScreen.svelte";
  import StartScreen from "./screens/StartScreen.svelte";
  import SummaryScreen from "./screens/SummaryScreen.svelte";
  import { holdScreen } from "./device/wake";

  interface Props {
    link: LinkView;
    tick?: number;
    greet?: boolean;
  }
  let { link, tick = 250, greet = false }: Props = $props();

  let started = $state(false);

  let now = $state(performance.now());
  const view = $derived(link.view);
  const since = $derived(Math.max(0, (now - link.receivedAt) / 1000));
  const busy = $derived(view?.screen.name === "ride" || (view?.screen.name === "calibration" &&
    ["starting", "speed_up", "stop_pedaling"].includes(view.screen.phase)));
  const greeting = $derived(greet && !started && !busy);

  $effect(() => {
    if (busy) {
      started = true;
    }
  });

  onMount(() => {
    const timer = setInterval(() => (now = performance.now()), tick);
    const visible = (): void => {
      if (document.visibilityState === "visible" && view?.screen.name === "ride") {
        void holdScreen();
      }
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  });
</script>

<main class:stale={!link.live && !greeting}>
  {#if greeting}
    <StartScreen connected={view !== null} start={() => (started = true)} />
  {:else if view === null}
    <div class="page"><p class="label">Connecting to the Pi…</p></div>
  {:else if view.screen.name === "home"}
    <HomeScreen screen={view.screen} warnings={view.warnings} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "pre_ride"}
    <PreRideScreen screen={view.screen} plan={link.plan} links={view.links} battery={view.hrm_battery_pct}
      send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "ride"}
    <RideScreen screen={view.screen} plan={link.plan} links={view.links} battery={view.hrm_battery_pct}
      warnings={view.warnings} since={link.live ? since : 0} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "summary"}
    <SummaryScreen screen={view.screen} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "history"}
    <HistoryScreen screen={view.screen} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "calibration"}
    <CalibrationScreen screen={view.screen} send={(n, a) => link.send(n, a)} />
  {:else}
    <LaterScreen name={view.screen.name} send={(n, a) => link.send(n, a)} />
  {/if}
</main>
{#if view !== null && !link.live && !greeting}
  <div class="lost" role="status">Lost the Pi. Reconnecting…</div>
{/if}

<style>
  .stale {
    opacity: 0.45;
    pointer-events: none;
  }
  .lost {
    position: fixed;
    top: max(16px, env(safe-area-inset-top));
    left: 16px;
    right: 16px;
    background: var(--warning);
    color: var(--ink);
    border-radius: 14px;
    padding: 12px 14px;
    font-weight: 650;
    z-index: 20;
  }
</style>
