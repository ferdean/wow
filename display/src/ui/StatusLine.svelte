<script lang="ts">
  import type { LinkState } from "../types/protocol";
  import { percent } from "../format";

  interface Props {
    trainer: LinkState;
    hrm: LinkState;
    battery: number | null;
    batteryLow?: boolean;
  }
  let { trainer, hrm, battery, batteryLow = false }: Props = $props();

  const words: Record<LinkState, string> = {
    connected: "connected",
    searching: "searching",
    not_found: "not found",
    dropout: "lost",
    not_configured: "not set up",
  };
</script>

<div class="status">
  <span class="link {trainer}"><i aria-hidden="true"></i>Trainer {words[trainer]}</span>
  <span class="link {hrm}"><i aria-hidden="true"></i>Strap {words[hrm]}</span>
  <span class="battery" class:low={batteryLow}>
    <svg viewBox="0 0 20 10" aria-hidden="true"><rect x="0.5" y="0.5" width="16" height="9" rx="2" /><rect class="tip" x="17" y="3" width="2" height="4" /><path
        class="heart" d="M8.5 8 L5.7 5.2 A1.6 1.6 0 0 1 8.5 3.4 A1.6 1.6 0 0 1 11.3 5.2 Z" /></svg>
    {percent(battery)}{batteryLow ? " low" : ""}
  </span>
</div>

<style>
  .status {
    display: flex;
    gap: 14px;
    align-items: center;
    font-size: 15px;
    color: var(--mist);
    min-height: 24px;
  }
  .link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  i {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--ok);
    display: inline-block;
  }
  .searching i,
  .not_found i,
  .not_configured i {
    background: transparent;
    border: 2px solid var(--mist);
  }
  .dropout {
    color: var(--fault);
  }
  .dropout i {
    border-radius: 0;
    width: 0;
    height: 0;
    background: transparent;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 11px solid var(--fault);
  }
  .battery {
    margin-left: auto;
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }
  .battery svg {
    width: 20px;
    height: 10px;
    fill: none;
    stroke: currentColor;
  }
  .battery svg .tip {
    fill: currentColor;
    stroke: none;
  }
  .battery svg .heart {
    fill: var(--moon);
    stroke: none;
  }
  .low {
    color: var(--warning);
  }
</style>
