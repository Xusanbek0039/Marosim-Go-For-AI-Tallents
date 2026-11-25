"use client";

import { useState } from "react";

import { PageHeader } from "@/components/common";
import { RequirePermission } from "@/components/layout/require-permission";
import { PageTransition } from "@/components/motion/page-transition";
import { useMe } from "@/features/auth/hooks";
import { AI_CODES, AI_TABS, type AiTab, visibleAiTabs } from "@/features/ai-planner/access";
import {
  AuditPanel,
  ControlPanel,
  ConversationsPanel,
  DashboardPanel,
  PromptsPanel,
  ReportsPanel,
  SettingsPanel,
  UsagePanel,
} from "@/features/ai-planner/panels";
import { cn } from "@/lib/utils";

const PANELS: Record<AiTab, () => React.ReactNode> = {
  dashboard: DashboardPanel,
  usage: UsagePanel,
  reports: ReportsPanel,
  conversations: ConversationsPanel,
  control: ControlPanel,
  settings: SettingsPanel,
  prompts: PromptsPanel,
  audit: AuditPanel,
};

function AiPlannerContent() {
  const { data: me } = useMe();
  const tabs = visibleAiTabs(me);
  const [picked, setPicked] = useState<AiTab | null>(null);
  const active = picked && tabs.includes(picked) ? picked : tabs[0];
  const Panel = active ? PANELS[active] : null;
  return (
    <>
      <PageHeader title="AI maslahatchi" crumb="Boshqaruv / AI marosim rejalashtiruvchisi" />
      <div role="tablist" aria-label="AI bo'limlari" className="glass flex gap-1 overflow-x-auto rounded-2xl p-1 [scrollbar-width:none]">
        {AI_TABS.filter((t) => tabs.includes(t.key)).map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={active === t.key}
            onClick={() => setPicked(t.key)}
            className={cn("shrink-0 rounded-xl px-3 py-2 text-sm font-semibold whitespace-nowrap", active === t.key ? "brand-gradient text-white" : "text-muted-foreground hover:text-foreground")}
          >
            {t.label}
          </button>
        ))}
      </div>
      {Panel && <Panel />}
    </>
  );
}

export default function AiPlannerPage() {
  return (
    <RequirePermission requires={AI_CODES}>
      <PageTransition>
        <AiPlannerContent />
      </PageTransition>
    </RequirePermission>
  );
}
