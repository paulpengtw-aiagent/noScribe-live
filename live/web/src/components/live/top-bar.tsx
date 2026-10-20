import { lazy, Suspense } from "react";
import { Moon, Sun } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { LocaleToggle } from "@/components/live/locale-toggle";
import { Button } from "@/components/ui/button";
import type { Connection } from "@/hooks/use-live-feed";
import type { Theme } from "@/hooks/use-theme";
import { useI18n } from "@/i18n";
import type { RunState } from "@/lib/live-state";
import { runStateBadge } from "@/lib/live-view";
import type { RunSummary } from "@/lib/live-types";
import { cn } from "@/lib/utils";

// The run picker (popover + cmdk command palette) is its own chunk, fetched on first render.
const RunPicker = lazy(() =>
  import("@/components/live/run-picker").then((mod) => ({ default: mod.RunPicker })),
);

export interface TopBarProps {
  runs: RunSummary[];
  runParam: string;
  onRunChange: (runParam: string) => void;
  /** The shown run, or null when none is shown. */
  run: RunState | null;
  /** A still-running run other than the shown one; offers a switch. Null when there is none. */
  otherLive: RunSummary | null;
  connection: Connection;
  theme: Theme;
  onToggleTheme: () => void;
}

export function TopBar({
  runs,
  runParam,
  onRunChange,
  run,
  otherLive,
  connection,
  theme,
  onToggleTheme,
}: TopBarProps) {
  const { t } = useI18n();
  const badge = runStateBadge(run);
  const live = badge?.status === "running";
  // Only "live" counts as connected. Any other state (including the legacy "stale") reads as reconnecting.
  const link = connection === "live" ? "live" : connection === "connecting" ? "connecting" : "reconnecting";
  // A live run whose feed is not connected: the run badge carries the connection text, so the
  // connection text is kept for screen readers only. data-state keeps the raw link state either way.
  const feedDown = live && link !== "live";
  const cutOff = feedDown && link === "reconnecting";
  const badgeText = badge
    ? feedDown
      ? cutOff
        ? t.topbar.runDisconnected
        : t.topbar.connConnecting
      : t.topbar.runStatus[badge.status]
    : null;
  const dotClass = cutOff
    ? "bg-amber-500 animate-pulse"
    : live && link === "live"
      ? "bg-foreground"
      : live
        ? "bg-ink-3 animate-pulse"
        : "bg-ink-3";
  const connText =
    link === "live"
      ? t.topbar.connConnected
      : link === "connecting"
        ? t.topbar.connConnecting
        : t.topbar.connReconnecting;

  return (
    <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center border-b border-hairline bg-background/80 backdrop-blur-xl">
      <div className="flex w-full items-center justify-between gap-3 px-4 min-[1100px]:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <span aria-hidden="true" className="flex shrink-0">
            <Orb variant="G1" size={18} />
          </span>
          <span className="truncate text-[15px] font-medium tracking-[-0.01em]">{t.topbar.appName}</span>
        </div>

        <div className="flex min-w-0 items-center gap-2 sm:gap-4">
          {otherLive && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="other-live-run"
              onClick={() => onRunChange(otherLive.run_id)}
              className="h-8 min-w-0 max-w-[140px] rounded-full bg-raised px-3 text-[13px] text-foreground shadow-ring hover:bg-raised sm:max-w-none dark:bg-raised dark:hover:bg-raised"
            >
              <span aria-hidden="true" className="size-1.5 shrink-0 animate-pulse rounded-full bg-foreground" />
              <span className="truncate">{t.topbar.otherLive}</span>
            </Button>
          )}

          <Suspense fallback={null}>
            <RunPicker runs={runs} value={runParam} onChange={onRunChange} />
          </Suspense>

          <div role="status" className="flex shrink-0 items-center gap-2 text-[13px] text-ink-2">
            <span
              data-testid="conn-state"
              data-state={link}
              className={cn("flex items-center gap-1.5", feedDown && "sr-only")}
            >
              {link !== "live" && !feedDown && (
                <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-ink-3" />
              )}
              <span className={link === "live" ? "sr-only" : undefined}>{connText}</span>
            </span>
            {badge && (
              <span
                data-testid="run-state"
                data-state={badge.status}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-full bg-raised px-2.5 py-0.5 text-[12px] font-medium shadow-ring",
                  cutOff ? "text-amber-700 dark:text-amber-400" : "text-foreground",
                )}
              >
                <span aria-hidden="true" className={cn("size-1.5 rounded-full", dotClass)} />
                {badgeText}
              </span>
            )}
          </div>

          <LocaleToggle />

          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? t.topbar.switchTheme.light : t.topbar.switchTheme.dark}
            className="shrink-0 rounded-full shadow-ring hover:bg-raised dark:hover:bg-raised"
          >
            {theme === "dark" ? <Sun /> : <Moon />}
          </Button>
        </div>
      </div>
    </header>
  );
}
