<script lang="ts">
  import type { CommandName, LinkState, Plan, PreRideScreen, Warning } from "../types/protocol";
  import { listDuration, percent, routeLine, stepText } from "../format";
  import Banner from "../ui/Banner.svelte";
  import Profile from "../ui/Profile.svelte";
  import Sheet from "../ui/Sheet.svelte";
  import { holdScreen } from "../device/wake.svelte";

  interface Props {
    screen: PreRideScreen;
    plan: Plan | null;
    links: { trainer: LinkState; hrm: LinkState };
    battery: number | null;
    warnings?: Warning[];
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, plan, links, battery, warnings = [], send }: Props = $props();
  const low = $derived(warnings.some((w) => w.kind === "hrm_battery_low"));
  const unsynced = $derived(warnings.some((w) => w.kind === "clock_unsynced"));

  const words: Record<LinkState, string> = {
    connected: "Connected",
    searching: "Searching…",
    not_found: "Not found, still looking",
    dropout: "Lost, reconnecting",
    not_configured: "Not set up",
  };
  const blocks = $derived(plan !== null && plan.plan_id === screen.plan_id ? plan.blocks : []);
  const chosen = $derived(screen.routes.find((r) => r.file === screen.route) ?? null);
  let choosing = $state(false);

  function choose(file: string | null): void {
    choosing = false;
    send("set_route", { file });
  }

  function start(): void {
    void holdScreen();
    send("start");
  }
</script>

<div class="page fixed">
  <div class="row">
    <button class="secondary small" onclick={() => send("back")}>Back</button>
  </div>
  <div class="scroll">
    <h1>{screen.title}</h1>
    {#if screen.free_ride}
      <div class="label">Starts at the free-ride level. Switch to riding by power, and back, at any time.</div>
    {:else}
      <div class="label">{listDuration(screen.duration)} · FTP {screen.ftp} W</div>
    {/if}
    <div class="panel devices">
      <div class="row"><span class="grow">Trainer</span><span class:ok={links.trainer === "connected"}>{words[links.trainer]}</span></div>
      <div class="row"><span class="grow">Strap</span><span class:ok={links.hrm === "connected"}>{words[links.hrm]}</span><span class="label" class:low>{percent(battery)}{low ? " low" : ""}</span></div>
    </div>
    {#if screen.routes.length > 0}
      <button class="panel route" onclick={() => (choosing = true)}>
        <span class="grow">Route</span>
        {#if chosen === null}
          <span class="label">None</span>
        {:else}
          <span class="pick"><span>{chosen.name}</span><span class="label">{routeLine(chosen.length_m, chosen.ascent_m)}</span></span>
        {/if}
      </button>
    {/if}
    {#if low}
      <Banner tone="warning" text="The strap's battery is low. Replace it soon." />
    {/if}
    {#if unsynced}
      <Banner tone="warning" text="The Pi's clock isn't set yet. Ride times may be off." />
    {/if}
    {#if !screen.free_ride}<div class="profile"><Profile {plan} /></div>{/if}
    <div class="blocks">
      {#each blocks as block (block.index)}
        <div class="panel">
          <div class="row">
            <span class="grow">{block.label || `Block ${block.index + 1}`}{block.repeats > 1 ? ` × ${block.repeats}` : ""}</span>
            <span class="label">{listDuration(block.duration)}</span>
            {#if block.steps.some((s) => s.kind === "erg")}
              <button class="small mode" class:resistance={screen.block_modes[block.index] === "resistance"}
                onclick={() => send("set_block_mode", { block: block.index,
                  mode: screen.block_modes[block.index] === "resistance" ? "erg" : "resistance" })}>
                {screen.block_modes[block.index] === "resistance" ? "Resistance" : "ERG"}
              </button>
            {:else}
              <span class="label">Free ride</span>
            {/if}
          </div>
          <div class="steps label">
            {block.steps.map(stepText).join(", ")}
          </div>
        </div>
      {/each}
    </div>
  </div>
  <div class="start">
    {#if screen.blocked === "trainer_missing"}
      <p class="label">Trainer not connected</p>
    {/if}
    <button class="primary" disabled={!screen.can_start} onclick={start}>Start ride</button>
  </div>
</div>

{#if choosing}
  <Sheet title="Route" text="Speed, distance, height and position come from your power along it, after the ride.">
    <div class="choices">
      <button class:picked={chosen === null} onclick={() => choose(null)}>No route</button>
      {#each screen.routes as route (route.file)}
        <button class:picked={route.file === screen.route} onclick={() => choose(route.file)}>
          <span class="grow">{route.name}</span><span class="label line">{routeLine(route.length_m, route.ascent_m)}</span>
        </button>
      {/each}
    </div>
    <button class="secondary" onclick={() => (choosing = false)}>Cancel</button>
  </Sheet>
{/if}

<style>
  .route {
    display: flex;
    align-items: center;
    gap: var(--gap);
    width: 100%;
    min-height: 62px;
    text-align: left;
    font-size: 17px;
    font-weight: 550;
  }
  .pick {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    text-align: right;
  }
  .line {
    white-space: nowrap;
  }
  .choices {
    display: flex;
    flex-direction: column;
    gap: var(--gap);
    max-height: 50dvh;
    overflow-y: auto;
  }
  .choices button {
    display: flex;
    align-items: center;
    gap: var(--gap);
    text-align: left;
  }
  .picked {
    border-color: var(--moon);
  }
  .devices {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .ok {
    color: var(--ok);
  }
  .low {
    color: var(--warning);
  }
  .profile {
    height: 80px;
  }
  .blocks {
    display: flex;
    flex-direction: column;
    gap: var(--gap);
  }
  .steps {
    margin-top: 4px;
  }
  .mode {
    min-height: 40px;
    min-width: 0;
    font-size: 15px;
  }
  .mode.resistance {
    background: var(--zone-4);
    color: var(--ink);
  }
  .start {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .start p {
    margin: 0;
    text-align: center;
  }
  .start button {
    width: 100%;
  }
</style>
