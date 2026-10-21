// The run's CLI log lines (LogLine), opened from a small header button into a dialog. Renders nothing without lines.
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useI18n } from "@/i18n";
import type { LogLine } from "@/lib/live-state";
import { cn } from "@/lib/utils";

/** Muted for info (and debug), the existing yellow and red status inks for warnings and errors. */
const LEVEL_TEXT: Record<LogLine["level"], string> = {
  debug: "text-ink-2",
  info: "text-ink-2",
  warning: "text-status-loading-ink",
  error: "text-status-failed-ink",
};

const pad = (n: number) => String(n).padStart(2, "0");

/** mm:ss since the run started. A line stamped before the start reads 00:00. */
function offsetText(t: number, startedT: number): string {
  const s = Math.max(0, Math.floor(t - startedT));
  return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
}

/** HH:MM:SS of the absolute time, in the reader's time zone, for a run with no start time. */
function clockText(t: number): string {
  const d = new Date(t * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function CliLogDisclosure({
  logs,
  startedT,
  easy,
}: {
  logs: readonly LogLine[];
  startedT: number | null;
  easy: boolean;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  if (logs.length === 0) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          data-testid="cli-log"
          className={cn(!easy && "rounded-full text-ink-2 shadow-ring hover:bg-raised dark:hover:bg-raised")}
        >
          {t.topbar.cliLog}
        </Button>
      </DialogTrigger>
      <DialogContent aria-describedby={undefined} className="gap-3 sm:max-w-2xl">
        <DialogTitle>{t.topbar.cliLog}</DialogTitle>
        <div
          role="region"
          aria-label={t.topbar.cliLog}
          tabIndex={0}
          className="font-mono text-[13px] leading-6 max-h-[70vh] overflow-y-auto"
        >
          {logs.map((line) => (
            <div
              key={line.first}
              className={cn("break-words whitespace-pre-wrap", !easy && LEVEL_TEXT[line.level])}
            >
              <span className={cn(!easy && "text-ink-3")}>
                {startedT === null ? clockText(line.t) : offsetText(line.t, startedT)}
              </span>{" "}
              <span>[{line.source}]</span>{" "}
              <span>{line.msg}</span>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
