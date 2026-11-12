// The page's connection to the Pi (3A, display/src/link; 3C, "The page's
// connection to the Pi"): last view and plan, commands, pings, reconnects.

import type { CommandName, Down, Plan, Up, View } from "../types/protocol";
import { best, recent, sample, type PingSample } from "./offset";

const BACKOFF_MS = [500, 1000, 2000, 4000];
const RETRY_MS = 5000;
const STALE_MS = 3000;
const GIVE_UP_MS = 8000;
const PING_MS = 5000;
const CHECK_MS = 500;
const PAINT_GAP_MS = 100;

export interface LinkView {
  readonly view: View | null;
  readonly plan: Plan | null;
  readonly live: boolean;
  readonly receivedAt: number;
  send(name: CommandName, args?: Record<string, unknown>): void;
}

export class Link implements LinkView {
  view = $state<View | null>(null);
  plan = $state<Plan | null>(null);
  live = $state(false);
  receivedAt = $state(0);

  private socket: WebSocket | null = null;
  private attempts = 0;
  private nextId = 0;
  private pings: PingSample[] = [];
  private pending: { id: number; sent: number }[] = [];
  private paintedData = 0;
  private paintedAt = 0;
  private openedAt = 0;
  private lastSeq = 0;

  constructor(
    private readonly url: string,
    private readonly version: string,
  ) {}

  start(): void {
    this.open();
    setInterval(() => this.check(), CHECK_MS);
    setInterval(() => this.ping(), PING_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        this.reopen();
      }
    });
  }

  send(name: CommandName, args?: Record<string, unknown>): void {
    if (!this.live) {
      return;
    }
    this.nextId += 1;
    const offset = best(this.pings, performance.now());
    const up: Up = { type: "command", id: this.nextId, name, args };
    if (offset !== null) {
      up.tap_mono_ms = Math.round((performance.now() + offset.offset_ms) * 10) / 10;
    }
    this.write(up);
  }

  private open(): void {
    const socket = new WebSocket(this.url);
    this.socket = socket;
    this.openedAt = performance.now();
    socket.onmessage = (event) => this.receive(socket, String(event.data));
    socket.onclose = () => {
      if (this.socket === socket) {
        this.socket = null;
        this.live = false;
        this.retry();
      }
    };
  }

  private retry(): void {
    const wait = BACKOFF_MS[this.attempts] ?? RETRY_MS;
    this.attempts += 1;
    setTimeout(() => {
      if (this.socket === null) {
        this.open();
      }
    }, wait);
  }

  private reopen(): void {
    const old = this.socket;
    this.socket = null;
    this.live = false;
    old?.close();
    this.attempts = 0;
    this.open();
  }

  private receive(socket: WebSocket, text: string): void {
    if (socket !== this.socket) {
      return;
    }
    const message = JSON.parse(text) as Down;
    switch (message.type) {
      case "hello":
        if (message.app_version !== this.version) {
          location.reload();
        }
        this.lastSeq = 0;
        break;
      case "plan":
        this.plan = message;
        break;
      case "view":
        if (message.seq > this.lastSeq) {
          this.lastSeq = message.seq;
          this.view = message;
          this.receivedAt = performance.now();
          this.live = true;
          this.attempts = 0;
          this.reportPaint(message);
        }
        break;
      case "pong": {
        const asked = this.pending.find((p) => p.id === message.id);
        this.pending = this.pending.filter((p) => p.id > message.id);
        if (asked !== undefined) {
          this.pings = [...recent(this.pings, performance.now()),
                        sample(asked.sent, performance.now(), message.pi_mono_ms)];
        }
        break;
      }
      case "ack":
        break;
    }
  }

  private reportPaint(view: View): void {
    const data = view.data_mono_ms;
    const now = performance.now();
    if (data === null || data <= this.paintedData || now - this.paintedAt < PAINT_GAP_MS) {
      return;
    }
    this.paintedData = data;
    this.paintedAt = now;
    requestAnimationFrame(() => {
      const offset = best(this.pings, performance.now());
      if (offset !== null) {
        this.write({ type: "painted", seq: view.seq,
                     paint_mono_ms: Math.round((performance.now() + offset.offset_ms) * 10) / 10 });
      }
    });
  }

  private ping(): void {
    this.nextId += 1;
    const now = performance.now();
    this.pending = [...this.pending.slice(-11), { id: this.nextId, sent: now }];
    this.write({ type: "ping", id: this.nextId, t_page_ms: now });
  }

  private check(): void {
    const now = performance.now();
    if (this.live && now - this.receivedAt > STALE_MS) {
      this.live = false;
    }
    if (this.socket !== null && now - Math.max(this.receivedAt, this.openedAt) > GIVE_UP_MS) {
      this.reopen();
    }
  }

  private write(message: Up): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }
}
