/**
 * Which AI-planner screens a panel account sees. UI only — Django checks the same codes on every call
 * (apps/event_planner/admin_views.py). Pure module (type imports only) so `node --test` can run it.
 */
import type { Me, PermissionCode } from "../../lib/api/types";

export type AiTab = "dashboard" | "usage" | "reports" | "conversations" | "control" | "settings" | "prompts" | "audit";

export const AI_TABS: { key: AiTab; label: string; requires: PermissionCode | "super" }[] = [
  { key: "dashboard", label: "Dashboard", requires: "ai.view" },
  { key: "usage", label: "So'rovlar va xatolar", requires: "ai.view" },
  { key: "reports", label: "Shikoyatlar", requires: "ai.reports" },
  { key: "conversations", label: "Suhbatlar", requires: "ai.conversations" },
  { key: "control", label: "Favqulodda o'chirish", requires: "ai.disable" },
  { key: "settings", label: "Sozlamalar", requires: "super" },
  { key: "prompts", label: "Prompt versiyalari", requires: "super" },
  { key: "audit", label: "Audit", requires: "super" },
];

export const AI_CODES: PermissionCode[] = ["ai.view", "ai.reports", "ai.conversations", "ai.disable"];

export function visibleAiTabs(me: Pick<Me, "role" | "permissions"> | undefined): AiTab[] {
  if (!me || (me.role !== "ADMIN" && me.role !== "SUPER_ADMIN")) return [];
  return AI_TABS.filter((t) => (t.requires === "super" ? me.role === "SUPER_ADMIN" : me.permissions.includes(t.requires))).map(
    (t) => t.key,
  );
}

/** Config fields whose change switches the AI on/off or changes what it runs on — they need a confirmation. */
export const CRITICAL_FIELDS = ["provider", "model_name", "enabled", "maintenance_mode", "feature_flags"] as const;

export function criticalChanges(before: Record<string, unknown>, after: Record<string, unknown>): string[] {
  return CRITICAL_FIELDS.filter((key) => key in after && JSON.stringify(after[key]) !== JSON.stringify(before[key]));
}
