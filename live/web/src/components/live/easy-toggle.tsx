import type { ReactNode } from "react";
import { Type } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EasyViewContext, useEasyViewState, useEasyView } from "@/hooks/use-easy-view";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

/** Holds the easy-view flag for the whole page. main.tsx mounts it once; components read it with useEasyView(). */
export function EasyViewProvider({ children }: { children: ReactNode }) {
  const value = useEasyViewState();
  return <EasyViewContext.Provider value={value}>{children}</EasyViewContext.Provider>;
}

/**
 * Easy view switch in the header, rendered on every width (data-testid stays unique). The phone header uses
 * `compact`: the same icon with a short label. aria-pressed carries the state; the label names the mode.
 */
export function EasyToggle({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const { easy, setEasy } = useEasyView();
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      data-testid="easy-toggle"
      aria-pressed={easy}
      onClick={() => setEasy(!easy)}
      className={cn(
        "h-9 shrink-0 gap-1.5 rounded-full font-medium shadow-ring hover:bg-raised dark:hover:bg-raised",
        compact ? "px-2.5" : "px-3",
        easy && "bg-foreground text-background hover:bg-foreground dark:hover:bg-foreground",
      )}
    >
      <Type aria-hidden="true" className="size-4" />
      <span>{compact ? t.easy.toggleShort : t.easy.toggle}</span>
    </Button>
  );
}

/** The status kinds that easy view names with an icon and a word. */
export type EasyStatusKind = "live" | "loading" | "finished" | "failed" | "stopped" | "canceled" | "reconnecting";

const GLYPH: Record<EasyStatusKind, string> = {
  live: "●",
  loading: "◐",
  finished: "✓",
  failed: "✕",
  stopped: "■",
  canceled: "○",
  reconnecting: "⟳",
};

/** A status word with its icon glyph. The glyph is decorative: the word carries the meaning for screen readers. */
export function EasyStatus({ kind, className }: { kind: EasyStatusKind; className?: string }) {
  const { t } = useI18n();
  return (
    <span className={cn("flex min-w-0 items-center gap-2 font-medium", className)}>
      <span aria-hidden="true" className="shrink-0">
        {GLYPH[kind]}
      </span>
      <span className="min-w-0 truncate">{t.easy.status[kind]}</span>
    </span>
  );
}
