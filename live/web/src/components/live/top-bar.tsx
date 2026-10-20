import { Moon, Sun } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { RunPicker } from "@/components/live/run-picker";
import { Button } from "@/components/ui/button";
import type { Connection } from "@/hooks/use-live-feed";
import type { Theme } from "@/hooks/use-theme";
import type { RunState } from "@/lib/live-state";
import { runStateBadge } from "@/lib/live-view";
import type { RunSummary } from "@/lib/live-types";
import { cn } from "@/lib/utils";

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
  const badge = runStateBadge(run);
  // "Live" only while the run is live and the feed is connected. Otherwise the badge says why not.
  // data-state keeps the run status either way.
  let badgeText = badge?.text ?? null;
  if (badge?.status === "running" && connection !== "live") {
    badgeText = connection === "connecting" ? "Connecting…" : "Reconnecting…";
  }

  return (
    <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center border-b border-hairline bg-background/80 backdrop-blur-xl">
      <div className="flex w-full items-center justify-between gap-3 px-4 min-[1100px]:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <span aria-hidden="true" className="flex shrink-0">
            <Orb variant="G1" size={18} />
          </span>
          <span className="truncate text-[15px] font-medium tracking-[-0.01em]">noScribe Live</span>
        </div>

        <div className="flex shrink-0 items-center gap-3 sm:gap-5">
          {otherLive && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="other-live-run"
              onClick={() => onRunChange(otherLive.run_id)}
              className="h-8 rounded-full bg-raised px-3 text-[13px] text-foreground shadow-ring hover:bg-raised dark:bg-raised dark:hover:bg-raised"
            >
              <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-foreground" />
              另一個轉錄正在進行 → 切換
            </Button>
          )}

          <RunPicker runs={runs} value={runParam} onChange={onRunChange} />

          <div role="status" className="flex items-center gap-3 text-[13px] text-ink-2">
            <span data-testid="conn-state" data-state={connection} className="flex items-center gap-2">
              {connection === "live" ? (
                <span className="sr-only">Connected</span>
              ) : (
                <>
                  <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-ink-3" />
                  {connection === "reconnecting" ? (
                    <span>重新連線中…</span>
                  ) : (
                    <span className="sr-only sm:not-sr-only">Connecting</span>
                  )}
                </>
              )}
            </span>
            {badge && (
              <span data-testid="run-state" data-state={badge.status} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={cn(
                    "size-1.5 rounded-full",
                    badge.status === "running" && connection === "live" ? "bg-foreground" : "bg-ink-3",
                    badge.status === "running" && connection !== "live" && "animate-pulse",
                  )}
                />
                {badgeText}
              </span>
            )}
          </div>

          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className="rounded-full shadow-ring hover:bg-raised dark:hover:bg-raised"
          >
            {theme === "dark" ? <Sun /> : <Moon />}
          </Button>
        </div>
      </div>
    </header>
  );
}
