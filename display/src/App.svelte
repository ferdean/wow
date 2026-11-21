<script lang="ts">
  import { onMount } from "svelte";
  import type { LinkView } from "./link/link.svelte";
  import CalibrationScreen from "./screens/CalibrationScreen.svelte";
  import HistoryScreen from "./screens/HistoryScreen.svelte";
  import HomeScreen from "./screens/HomeScreen.svelte";
  import PreRideScreen from "./screens/PreRideScreen.svelte";
  import RideScreen from "./screens/RideScreen.svelte";
  import SettingsScreen from "./screens/SettingsScreen.svelte";
  import StartScreen from "./screens/StartScreen.svelte";
  import SummaryScreen from "./screens/SummaryScreen.svelte";
  import { holdScreen, supported, wake } from "./device/wake.svelte";
  import { unlockSound } from "./device/sound";

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
  const prompt = $derived(busy && !wake.held && link.live);

  $effect(() => {
    if (busy) {
      started = true;
    }
  });

  onMount(() => {
    const timer = setInterval(() => (now = performance.now()), tick);
    const visible = (): void => {
      if (document.visibilityState === "visible" && busy) {
        void holdScreen();
      }
    };
    const tapped = (): void => {
      unlockSound();
      if (busy && !wake.held) {
        void holdScreen();
      }
    };
    document.addEventListener("visibilitychange", visible);
    document.addEventListener("pointerdown", tapped, true);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
      document.removeEventListener("pointerdown", tapped, true);
    };
  });
</script>

{#if prompt}
  <button class="wake" onclick={() => void holdScreen()}>
    {supported() ? "Tap to keep the screen on" : "This browser can't keep the screen on: set Auto-Lock to Never"}
  </button>
{/if}
<main class:stale={!link.live && !greeting} class:prompted={prompt}>
  {#if greeting}
    <StartScreen connected={view !== null} riders={view?.riders ?? null} start={() => (started = true)}
      choose={(rider) => link.send("rider_choose", { rider })} />
  {:else if view === null}
    <div class="page"><p class="label">Connecting to the Pi…</p></div>
  {:else if view.screen.name === "home"}
    <HomeScreen screen={view.screen} warnings={view.warnings} send={(n, a) => link.send(n, a)}
      riders={view.riders ?? null} switchRider={() => (started = false)} />
  {:else if view.screen.name === "pre_ride"}
    <PreRideScreen screen={view.screen} plan={link.plan} links={view.links} battery={view.hrm_battery_pct}
      warnings={view.warnings} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "ride"}
    <RideScreen screen={view.screen} plan={link.plan} links={view.links} battery={view.hrm_battery_pct}
      warnings={view.warnings} since={link.live ? since : 0} route={link.route ?? null}
      send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "summary"}
    <SummaryScreen screen={view.screen} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "history"}
    <HistoryScreen screen={view.screen} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "calibration"}
    <CalibrationScreen screen={view.screen} send={(n, a) => link.send(n, a)} />
  {:else if view.screen.name === "settings"}
    <SettingsScreen screen={view.screen} send={(n, a) => link.send(n, a)} riders={view.riders ?? null} />
  {/if}
</main>
{#if view !== null && !link.live && !greeting}
  <div class="lost" role="status">Lost the Pi. Reconnecting…</div>
{/if}

<style>
  .wake {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 30;
    width: 100%;
    min-height: calc(var(--prompt) + env(safe-area-inset-top));
    padding: env(safe-area-inset-top) 16px 0;
    border-radius: 0;
    background: var(--moon);
    color: var(--ink);
    font-size: 20px;
    font-weight: 700;
  }
  .prompted {
    padding-top: var(--prompt);
  }
  .prompted :global(.page) {
    min-height: calc(100dvh - var(--prompt));
  }
  .prompted :global(.page.fixed) {
    height: calc(100dvh - var(--prompt));
  }
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
