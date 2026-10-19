import { Moon, Sun } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Connection } from "@/hooks/use-live-feed";
import type { Theme } from "@/hooks/use-theme";
import { formatTimeOfDay } from "@/lib/format";
import { FOLLOW_NEWEST, RUN_STATUS_WORD, runName } from "@/lib/live-view";
import type { RunSummary } from "@/lib/live-types";
import { cn } from "@/lib/utils";

const CONNECTION_TEXT: Record<Connection, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
};

export interface TopBarProps {
  runs: RunSummary[];
  runParam: string;
  onRunChange: (runParam: string) => void;
  connection: Connection;
  theme: Theme;
  onToggleTheme: () => void;
}

export function TopBar({ runs, runParam, onRunChange, connection, theme, onToggleTheme }: TopBarProps) {
  const chosen = runs.find((run) => run.run_id === runParam);
  const connectionText = CONNECTION_TEXT[connection];
  // The trigger shows a shorter label on narrow screens so it never clips to "Follow newest r".
  const triggerLabel =
    runParam === FOLLOW_NEWEST ? (
      <>
        <span className="sm:hidden">Follow newest</span>
        <span className="hidden sm:inline">Follow newest run</span>
      </>
    ) : chosen ? (
      runName(chosen)
    ) : (
      runParam
    );

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
          <Select value={runParam} onValueChange={onRunChange}>
            <SelectTrigger
              aria-label="Choose a run"
              className="h-8 w-[150px] rounded-full border-transparent bg-raised px-3.5 text-[13px] shadow-ring hover:bg-raised dark:bg-raised dark:hover:bg-raised sm:w-[260px]"
            >
              <SelectValue>{triggerLabel}</SelectValue>
            </SelectTrigger>
            <SelectContent position="popper" align="end" className="min-w-[260px] rounded-[14px]">
              <SelectItem value={FOLLOW_NEWEST}>Follow newest run</SelectItem>
              {runs.map((run) => (
                <SelectItem key={run.run_id} value={run.run_id}>
                  <span className="flex w-full min-w-0 items-center gap-3">
                    <span className="min-w-0 flex-1 truncate">{runName(run)}</span>
                    <span className="shrink-0 text-ink-2">{RUN_STATUS_WORD[run.status]}</span>
                    <span className="shrink-0 tabular-nums text-ink-3">{formatTimeOfDay(run.started_t)}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div role="status" className="flex items-center gap-2 text-[13px] text-ink-2">
            <span
              aria-hidden="true"
              className={cn("size-1.5 rounded-full", connection === "live" ? "bg-foreground" : "animate-pulse bg-ink-3")}
            />
            <span className="sr-only sm:not-sr-only">{connectionText}</span>
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
