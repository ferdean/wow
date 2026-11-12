<script lang="ts">
  import type { CommandName, LinkState, Plan, PreRideScreen } from "../types/protocol";
  import { listDuration, percent } from "../format";
  import Profile from "../ui/Profile.svelte";
  import { holdScreen } from "../device/wake";

  interface Props {
    screen: PreRideScreen;
    plan: Plan | null;
    links: { trainer: LinkState; hrm: LinkState };
    battery: number | null;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, plan, links, battery, send }: Props = $props();

  const words: Record<LinkState, string> = {
    connected: "Connected",
    searching: "Searching…",
    not_found: "Not found, still looking",
    dropout: "Lost, reconnecting",
    not_configured: "Not set up",
  };
  const blocks = $derived(plan !== null && plan.plan_id === screen.plan_id ? plan.blocks : []);

  function start(): void {
    void holdScreen();
    send("start");
  }
</script>

<div class="page">
  <div class="row">
    <button class="secondary small" onclick={() => send("back")}>Back</button>
  </div>
  <h1>{screen.title}</h1>
  <div class="label">{listDuration(screen.duration)} · FTP {screen.ftp} W</div>
  <div class="panel devices">
    <div class="row"><span class="grow">Trainer</span><span class:ok={links.trainer === "connected"}>{words[links.trainer]}</span></div>
    <div class="row"><span class="grow">Strap</span><span class:ok={links.hrm === "connected"}>{words[links.hrm]}</span><span class="label">{percent(battery)}</span></div>
  </div>
  <div class="profile"><Profile {plan} /></div>
  <div class="blocks">
    {#each blocks as block (block.index)}
      <div class="panel">
        <div class="row">
          <span class="grow">{block.label || `Block ${block.index + 1}`}{block.repeats > 1 ? ` × ${block.repeats}` : ""}</span>
          <span class="label">{listDuration(block.duration)} · ERG</span>
        </div>
        <div class="steps label">
          {block.steps.map((s) => `${Math.round(s.duration)} s at ${s.start_power ?? "––"} W`).join(", ")}
        </div>
      </div>
    {/each}
  </div>
  <div class="start">
    {#if screen.blocked === "trainer_missing"}
      <p class="label">Trainer not connected</p>
    {/if}
    <button class="primary" disabled={!screen.can_start} onclick={start}>Start ride</button>
  </div>
</div>

<style>
  .devices {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .ok {
    color: var(--ok);
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
  .start {
    margin-top: auto;
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
