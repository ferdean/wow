<script lang="ts">
  import type { CommandName, FoundDevice, SettingsScreen } from "../types/protocol";
  import { dateTime } from "../format";

  interface Props {
    screen: SettingsScreen;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { screen, send }: Props = $props();

  // Table S (Phase 1): the stepper keeps a draft inside the range; the Pi
  // checks the value again when it is saved.
  type NumberKey = "ftp" | "lead_time" | "battery_warn_pct";
  interface Span { key: NumberKey; label: string; min: number; max: number; step: number; unit: string }
  const SPANS: Span[] = [
    { key: "ftp", label: "FTP", min: 100, max: 500, step: 1, unit: "W" },
    { key: "lead_time", label: "Lead time", min: 0, max: 5, step: 0.5, unit: "s" },
    { key: "battery_warn_pct", label: "Strap battery warning", min: 5, max: 50, step: 5, unit: "%" },
  ];
  const ZONE_MIN = 1;
  const ZONE_MAX = 200;
  const BIG_STEP = 10;

  let editing = $state<string | null>(null);
  let draft = $state(0);
  let zones = $state<number[]>([]);
  let athlete = $state("");
  let key = $state("");

  const choosing = $derived(screen.scan);

  function value(span: Span): number {
    return screen[span.key];
  }

  function edit(span: Span): void {
    editing = span.key;
    draft = value(span);
  }

  function nudge(span: Span, steps: number): void {
    const next = Math.round((draft + steps * span.step) / span.step) * span.step;
    draft = Math.min(span.max, Math.max(span.min, next));
  }

  function save(name: string, setting: unknown): void {
    send("settings_set", { key: name, value: setting });
    editing = null;
  }

  function editZones(): void {
    editing = "zones_pct";
    zones = [...screen.zones_pct];
  }

  function nudgeZone(index: number, steps: number): void {
    const low = index === 0 ? ZONE_MIN : (zones[index - 1] ?? ZONE_MIN) + 1;
    const high = index === zones.length - 1 ? ZONE_MAX : (zones[index + 1] ?? ZONE_MAX) - 1;
    zones[index] = Math.min(high, Math.max(low, (zones[index] ?? low) + steps));
  }

  function saveAccount(): void {
    send("intervals_account_set", { athlete_id: athlete.trim(), api_key: key.trim() });
    athlete = "";
    key = "";
    editing = null;
  }

  function deviceName(device: { address: string; name: string | null } | null): string {
    return device === null ? "None chosen" : (device.name ?? device.address);
  }

  function kindWord(found: FoundDevice): string {
    return { trainer: "Trainer", hrm: "Heart-rate strap", cadence: "Cadence sensor" }[found.kind];
  }
</script>

<div class="page fixed">
  <div class="row">
    <button class="secondary small" onclick={() => send("back")}>Back</button>
  </div>
  <h1>Settings</h1>
  <div class="scroll">
    <h2>Rider</h2>
    {#each SPANS as span (span.key)}
      <div class="panel">
        {#if editing === span.key}
          <div class="label">{span.label}</div>
          <div class="stepper">
            {#if span.step === 1}<button aria-label={`${span.label} down ${BIG_STEP}`} onclick={() => nudge(span, -BIG_STEP)}>−{BIG_STEP}</button>{/if}
            <button aria-label={`${span.label} down`} onclick={() => nudge(span, -1)}>−</button>
            <span class="number value">{draft}<span class="unit">{span.unit}</span></span>
            <button aria-label={`${span.label} up`} onclick={() => nudge(span, 1)}>+</button>
            {#if span.step === 1}<button aria-label={`${span.label} up ${BIG_STEP}`} onclick={() => nudge(span, BIG_STEP)}>+{BIG_STEP}</button>{/if}
          </div>
          <div class="row">
            <button class="primary grow" onclick={() => save(span.key, draft)}>Save</button>
            <button class="secondary" onclick={() => (editing = null)}>Cancel</button>
          </div>
        {:else}
          <button class="line" onclick={() => edit(span)}>
            <span class="grow">{span.label}</span><span class="label">{value(span)} {span.unit}</span>
          </button>
        {/if}
      </div>
    {/each}
    <div class="panel">
      {#if editing === "zones_pct"}
        <div class="label">Power zones: upper bound of each, in % of FTP</div>
        {#each zones as zone, index (index)}
          <div class="stepper">
            <span class="zone" style:background={`var(--zone-${index + 1})`}>Z{index + 1}</span>
            <button aria-label={`Zone ${index + 1} down`} onclick={() => nudgeZone(index, -1)}>−</button>
            <span class="number value">{zone}<span class="unit">%</span></span>
            <button aria-label={`Zone ${index + 1} up`} onclick={() => nudgeZone(index, 1)}>+</button>
          </div>
        {/each}
        <div class="row">
          <button class="primary grow" onclick={() => save("zones_pct", [...zones])}>Save</button>
          <button class="secondary" onclick={() => (editing = null)}>Cancel</button>
        </div>
      {:else}
        <button class="line" onclick={editZones}>
          <span class="grow">Power zones</span><span class="label">{screen.zones_pct.join(" · ")} %</span>
        </button>
      {/if}
    </div>
    <div class="panel">
      <button class="line" onclick={() => send("settings_set", { key: "upload_on", value: !screen.upload_on })}>
        <span class="grow">Upload rides to intervals.icu</span>
        <span class="switch" class:on={screen.upload_on}>{screen.upload_on ? "On" : "Off"}</span>
      </button>
    </div>

    <h2>Devices</h2>
    {#each [{ kind: "trainer" as const, label: "Trainer", device: screen.trainer },
            { kind: "hrm" as const, label: "Heart-rate strap", device: screen.hrm }] as role (role.kind)}
      <div class="panel">
        <div class="row">
          <span class="grow">{role.label}<br /><span class="label">{deviceName(role.device)}</span></span>
          <button class="small" disabled={choosing?.running} onclick={() => send("device_scan", { kind: role.kind })}>Choose</button>
        </div>
        {#if choosing && choosing.kind === role.kind}
          {#if choosing.running}
            <p class="label">Looking for devices nearby…</p>
          {:else if choosing.found.length === 0}
            <p class="label">Nothing found. Wake the device and try again.</p>
          {:else}
            {#each choosing.found as found (found.address)}
              <button class="found" disabled={found.kind !== role.kind}
                onclick={() => send("device_choose", { kind: role.kind, address: found.address })}>
                <span class="grow">{found.name ?? found.address}<br /><span class="label">{kindWord(found)} · {found.rssi_dbm} dBm</span></span>
                {#if role.device?.address === found.address}<span class="label">In use</span>{/if}
              </button>
            {/each}
          {/if}
        {/if}
      </div>
    {/each}

    <h2>intervals.icu</h2>
    <div class="panel">
      {#if editing === "account"}
        <label class="label" for="athlete">Athlete ID</label>
        <input id="athlete" bind:value={athlete} autocomplete="off" autocapitalize="off" spellcheck="false" />
        <label class="label" for="key">API key</label>
        <input id="key" type="password" bind:value={key} autocomplete="off" />
        <div class="row">
          <button class="primary grow" disabled={!athlete.trim() || !key.trim()} onclick={saveAccount}>Save</button>
          <button class="secondary" onclick={() => (editing = null)}>Cancel</button>
        </div>
      {:else}
        <button class="line" onclick={() => (editing = "account")}>
          <span class="grow">Account</span>
          <span class="label">{screen.intervals_account_set ? "Key saved" : "Not set up"}</span>
        </button>
      {/if}
    </div>

    <h2>The Pi</h2>
    <div class="panel pi">
      <span class="grow">Certificate valid until</span>
      <span class="label">{screen.cert_valid_until ? dateTime(screen.cert_valid_until) : "unknown"}</span>
    </div>
  </div>
</div>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 6px 16px;
  }
  .line,
  .found {
    display: flex;
    align-items: center;
    gap: var(--gap);
    width: 100%;
    min-height: 44px;
    padding: 0;
    background: transparent;
    text-align: left;
    font-size: 17px;
    font-weight: 550;
  }
  .found {
    padding: 8px 12px;
    background: var(--rise);
  }
  .stepper {
    display: flex;
    align-items: center;
    gap: var(--gap);
  }
  .stepper button {
    min-width: 52px;
    padding: 0 10px;
  }
  .value {
    flex: 1 1 auto;
    text-align: center;
    font-size: 40px;
  }
  .zone {
    color: var(--ink);
    border-radius: 10px;
    padding: 4px 10px;
    font-weight: 700;
  }
  .pi {
    flex-direction: row;
    align-items: center;
    min-height: 56px;
  }
  .switch {
    border-radius: 12px;
    padding: 6px 14px;
    background: var(--rise);
  }
  .switch.on {
    background: var(--ok);
    color: var(--ink);
  }
  input {
    font: inherit;
    font-size: 17px;
    min-height: 44px;
    padding: 0 12px;
    border-radius: 12px;
    border: 2px solid var(--line);
    background: var(--night);
    color: var(--moon);
    user-select: text;
    -webkit-user-select: text;
  }
  p {
    margin: 0;
  }
</style>
