// Geometry of the route screen (SL-14): the place at a distance along the
// route, the map's path up to there, and the elevation profile's outline.
import type { RouteMap } from "./types/protocol";

type Point = RouteMap["points"][number];

export interface Place {
  x: number;
  y: number;
  ele: number;
}

function index(points: Point[], at: number): number {
  let low = 0;
  let high = points.length - 1;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if ((points[middle]?.[0] ?? 0) <= at) {
      low = middle;
    } else {
      high = middle;
    }
  }
  return low;
}

export function placeAt(map: RouteMap, at: number): Place {
  const points = map.points;
  const first = points[0];
  if (first === undefined) {
    return { x: 0, y: 0, ele: 0 };
  }
  const i = index(points, at);
  const a = points[i] ?? first;
  const b = points[i + 1] ?? a;
  const span = b[0] - a[0];
  const part = span <= 0 ? 0 : Math.min(1, Math.max(0, (at - a[0]) / span));
  return { x: a[1] + (b[1] - a[1]) * part, y: a[2] + (b[2] - a[2]) * part, ele: a[3] + (b[3] - a[3]) * part };
}

export function pathOf(points: { x: number; y: number }[]): string {
  return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
}

export function wholePath(map: RouteMap): string {
  return pathOf(map.points.map((p) => ({ x: p[1], y: p[2] })));
}

export function donePath(map: RouteMap, at: number): string {
  const before = map.points.filter((p) => p[0] < at).map((p) => ({ x: p[1], y: p[2] }));
  return before.length === 0 ? "" : pathOf([...before, placeAt(map, at)]);
}

export const PROFILE_WIDTH = 1000;
export const PROFILE_HEIGHT = 200;

export function heightOf(map: RouteMap, ele: number): number {
  const range = Math.max(1, map.ele_max - map.ele_min);
  return PROFILE_HEIGHT - 12 - ((ele - map.ele_min) / range) * (PROFILE_HEIGHT - 30);
}

export function profileArea(map: RouteMap): string {
  const length = Math.max(1, map.length_m);
  const top = map.points.map((p) => `${((p[0] / length) * PROFILE_WIDTH).toFixed(1)},${heightOf(map, p[3]).toFixed(1)}`);
  return [`0,${PROFILE_HEIGHT}`, ...top, `${PROFILE_WIDTH},${PROFILE_HEIGHT}`].join(" ");
}

export function profileX(map: RouteMap, at: number): number {
  return (Math.min(Math.max(at, 0), map.length_m) / Math.max(1, map.length_m)) * PROFILE_WIDTH;
}
