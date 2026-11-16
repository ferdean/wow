<script lang="ts">
  interface Props {
    connected: boolean;
    start: () => void;
  }
  let { connected, start }: Props = $props();
</script>

<div class="page start">
  <div class="grow"></div>
  <h1>WitchesOnWheels</h1>
  <p class="label">{connected ? "Connected to the Pi." : "Connecting to the Pi…"}</p>
  <div class="grow"></div>
  <button class="primary go" onclick={start}>Start</button>
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
</style>
