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

/** Easy view switch for the desktop header. aria-pressed carries the state; the label names the mode. */
export function EasyToggle() {
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
        "h-9 shrink-0 gap-1.5 rounded-full px-3 font-medium shadow-ring hover:bg-raised dark:hover:bg-raised",
        easy && "bg-foreground text-background hover:bg-foreground dark:hover:bg-foreground",
      )}
    >
      <Type aria-hidden="true" className="size-4" />
      <span>{t.easy.toggle}</span>
    </Button>
  );
}

/** The same switch as a row in the compact header menu. `onDone` runs after the switch, to close the menu. */
export function EasyMenuItem({ onDone }: { onDone?: () => void }) {
  const { t } = useI18n();
  const { easy, setEasy } = useEasyView();
  return (
    <button
      type="button"
      data-testid="easy-toggle"
      aria-pressed={easy}
      className={cn(
        "flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-[14px] hover:bg-raised",
        easy && "bg-raised font-medium",
      )}
      onClick={() => {
        setEasy(!easy);
        onDone?.();
      }}
    >
      <span aria-hidden="true" className="flex w-5 shrink-0 justify-center">
        <Type className="size-4" />
      </span>
      <span className="min-w-0 truncate">{t.easy.toggle}</span>
    </button>
  );
}

/** The status kinds that easy view names with an icon and a word. */
export type EasyStatusKind = "live" | "finished" | "failed" | "stopped" | "reconnecting";

const GLYPH: Record<EasyStatusKind, string> = {
  live: "●",
  finished: "✓",
  failed: "✕",
  stopped: "■",
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
