<script lang="ts">
  import type { Riders } from "../types/protocol";
  import { sharedRider } from "../format";

  interface Props {
    connected: boolean;
    riders?: Riders | null;
    start: () => void;
    choose?: (rider: string) => void;
  }
  let { connected, riders = null, start, choose = () => undefined }: Props = $props();

  const shared = $derived(sharedRider(riders) !== null);

  function ride(rider: string): void {
    if (rider !== riders?.active) {
      choose(rider);
    }
    start();
  }
</script>

<div class="page start">
  <div class="grow"></div>
  <h1>WitchesOnWheels</h1>
  <p class="label">{connected ? (shared ? "Who's riding?" : "Connected to the Pi.") : "Connecting to the Pi…"}</p>
  <div class="grow"></div>
  {#if shared && riders}
    {#each riders.list as rider (rider.id)}
      <button class="go rider" class:primary={rider.id === riders.active} onclick={() => ride(rider.id)}>
        {rider.name}
      </button>
    {/each}
  {:else}
    <button class="primary go" onclick={start}>Start</button>
  {/if}
</div>

<style>
  .start {
    text-align: center;
  }
  h1 {
    font-size: 40px;
  }
  .go {
    min-height: 120px;
    font-size: 32px;
  }
  .rider {
    min-height: 96px;
  }
</style>
