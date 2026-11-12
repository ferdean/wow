<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    title: string;
    text: string;
    children: Snippet;
  }
  let { title, text, children }: Props = $props();
</script>

<div class="scrim">
  <div class="sheet" role="dialog" aria-modal="true" aria-label={title}>
    <h1>{title}</h1>
    <p>{text}</p>
    {@render children()}
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: rgb(10 6 18 / 0.6);
    display: flex;
    align-items: flex-end;
    z-index: 10;
  }
  .sheet {
    width: 100%;
    background: var(--dusk);
    border-radius: 22px 22px 0 0;
    padding: 20px var(--margin) max(var(--margin), env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    gap: var(--gap);
    animation: up 180ms ease-out;
  }
  .sheet :global(button) {
    min-height: 66px;
    width: 100%;
  }
  p {
    margin: 0 0 8px;
    color: var(--mist);
  }
  @keyframes up {
    from {
      transform: translateY(100%);
    }
  }
</style>
