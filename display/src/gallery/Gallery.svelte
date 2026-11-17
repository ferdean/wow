<script lang="ts">
  import { onMount } from "svelte";
  import App from "../App.svelte";
  import type { LinkView } from "../link/link.svelte";
  import type { Plan, RouteMap, View } from "../types/protocol";
  import { galleryStates, stateOf } from "./states";

  interface Props {
    views: Record<string, View>;
    plans: Record<string, Plan>;
    routes?: Record<string, RouteMap>;
  }
  let { views, plans, routes = {} }: Props = $props();

  let hash = $state(location.hash);
  const states = $derived(galleryStates(views));
  const shown = $derived(stateOf(hash, views));

  function still(view: View): LinkView {
    const planId = "plan_id" in view.screen ? view.screen.plan_id : null;
    const plan = plans[planId ?? ""] ?? Object.values(plans)[0] ?? null;
    const routeId = view.screen.name === "ride" ? view.screen.route?.route_id : undefined;
    return {
      view,
      plan,
      route: routes[routeId ?? ""] ?? null,
      live: true,
      get receivedAt(): number {
        return performance.now();
      },
      send: (name) => console.info("gallery: not sent", name),
    };
  }

  onMount(() => {
    const changed = (): void => {
      hash = location.hash;
    };
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  });
</script>

{#if shown === null}
  <div class="page fixed">
    <h1>Gallery</h1>
    <div class="label">Every screen state of test plan 3.1, as the Pi would show it. Swipe back to return here.</div>
    <div class="scroll">
      {#each states as group (group.screen)}
        <h2>{group.screen}</h2>
        {#each group.names as name (name)}
          <a class="panel state" href={`#gallery/${name}`}>{name}</a>
        {/each}
      {/each}
    </div>
  </div>
{:else}
  {#key shown}
    <App link={still(shown)} />
  {/key}
{/if}

<style>
  .state {
    display: block;
    color: var(--moon);
    text-decoration: none;
    font-size: 17px;
    padding: 12px 16px;
  }
  h2 {
    margin: 12px 0 0;
    font-size: 18px;
  }
</style>
