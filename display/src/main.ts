import "@fontsource-variable/sofia-sans";
import "@fontsource-variable/sofia-sans-condensed";
import "./theme.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { Link } from "./link/link.svelte";

const scheme = location.protocol === "https:" ? "wss" : "ws";
const link = new Link(`${scheme}://${location.host}/ws`, __APP_VERSION__);
link.start();
console.info("viewport", window.innerWidth, window.innerHeight);

export default mount(App, { target: document.getElementById("app") as HTMLElement, props: { link } });
