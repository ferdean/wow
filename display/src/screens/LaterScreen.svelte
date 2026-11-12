<script lang="ts">
  import type { CommandName } from "../types/protocol";

  interface Props {
    name: string;
    send: (name: CommandName, args?: Record<string, unknown>) => void;
  }
  let { name, send }: Props = $props();
</script>

<div class="page">
  <h1>Not built yet</h1>
  <p class="label">The {name} screen comes in a later slice.</p>
  <button class="secondary" onclick={() => send("back")}>Back</button>
</div>
