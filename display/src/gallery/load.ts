import type { Plan, View } from "../types/protocol";
import { nameOf } from "./states";
import plans from "../../../testdata/display/plans.json";

const files = import.meta.glob<View>("../../../testdata/display/*.view.json", { eager: true, import: "default" });

export const GOLDEN_VIEWS: Record<string, View> = Object.fromEntries(
  Object.entries(files).map(([path, view]) => [nameOf(path), view]),
);

export const GOLDEN_PLANS = plans as unknown as Record<string, Plan>;
