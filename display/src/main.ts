import "@fontsource-variable/sofia-sans";
import "@fontsource-variable/sofia-sans-condensed";
import "./theme.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { Link } from "./link/link.svelte";

const target = document.getElementById("app") as HTMLElement;

function ride(): void {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const link = new Link(`${scheme}://${location.host}/ws`, __APP_VERSION__);
  link.start();
  console.info("viewport", window.innerWidth, window.innerHeight);
  mount(App, { target, props: { link, greet: true } });
}

async function gallery(): Promise<void> {
  const [{ default: Gallery }, { GOLDEN_PLANS, GOLDEN_VIEWS }] = await Promise.all([
    import("./gallery/Gallery.svelte"), import("./gallery/load")]);
  mount(Gallery, { target, props: { views: GOLDEN_VIEWS, plans: GOLDEN_PLANS } });
}

if (location.hash.startsWith("#gallery")) {
  void gallery();
} else {
  ride();
}
