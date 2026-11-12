<script lang="ts">
  interface Props {
    tone: "warning" | "fault";
    text: string;
  }
  let { tone, text }: Props = $props();
</script>

<div class="banner {tone}" role="status">{text}</div>

<style>
  .banner {
    border-radius: 14px;
    padding: 10px 14px;
    color: var(--ink);
    font-weight: 650;
  }
  .warning {
    background: var(--warning);
  }
  .fault {
    background: var(--fault);
  }
</style>
