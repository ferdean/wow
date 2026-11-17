import type { View } from "../types/protocol";

const PREFIX = "#gallery/";

export interface StateGroup {
  screen: string;
  names: string[];
}

export function nameOf(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1).replace(/\.view\.json$/, "");
}

export function galleryStates(views: Record<string, View>): StateGroup[] {
  const groups = new Map<string, string[]>();
  for (const name of Object.keys(views).sort()) {
    const screen = views[name]?.screen.name ?? "";
    groups.set(screen, [...(groups.get(screen) ?? []), name]);
  }
  return [...groups].map(([screen, names]) => ({ screen, names }));
}

export function stateOf(hash: string, views: Record<string, View>): View | null {
  if (!hash.startsWith(PREFIX)) {
    return null;
  }
  return views[decodeURIComponent(hash.slice(PREFIX.length))] ?? null;
}
