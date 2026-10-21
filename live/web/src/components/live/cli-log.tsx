// The run's CLI log (LogLine): an inline panel above the stage card, expanded by default and collapsible. The
// open or closed choice and the transcript-line switch are remembered in localStorage. Transcript echo lines are
// hidden here only; the feed keeps them. Renders nothing without log lines.
import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useI18n } from "@/i18n";
import type { LogLine } from "@/lib/live-state";
import { cn } from "@/lib/utils";

/** localStorage key for the panel's choice: "open" or "closed". */
export const CLI_LOG_KEY = "noscribe-live-cli-log";
/** localStorage key for the transcript-line switch: "1" shows the echo lines, "0" hides them. Unset hides them. */
export const CLI_LOG_TRANSCRIPT_KEY = "noscribe-live-cli-log-transcript";

/** The CLI echoes each transcript segment on stdout, as in "S00: [00:00:02]This is …". */
const TRANSCRIPT_LINE = /^S\d+:\s*\[\d{1,2}:\d{2}:\d{2}\]/;

/** Pixels from the bottom within which the log still counts as "at the bottom" and keeps following the newest line. */
const FOLLOW_SLACK = 8;

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

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable; the choice still applies for this page view.
  }
}

/**
 * The saved choice wins. With none, the panel opens on desktop and starts collapsed in Easy view, where its
 * text is large and the stage should stay clear.
 */
function initialOpen(easy: boolean): boolean {
  const saved = readStored(CLI_LOG_KEY);
  if (saved === "open") return true;
  if (saved === "closed") return false;
  return !easy;
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
  const [open, setOpen] = useState<boolean>(() => initialOpen(easy));
  const [showTranscripts, setShowTranscripts] = useState<boolean>(
    () => readStored(CLI_LOG_TRANSCRIPT_KEY) === "1",
  );
  const bodyId = useId();
  const scrollRef = useRef<HTMLDivElement>(null);
  // While the reader is at the bottom, each new line scrolls into view. Scrolling up stops that until they return.
  const following = useRef(true);

  const shown = useMemo(
    () => (showTranscripts ? logs : logs.filter((line) => !TRANSCRIPT_LINE.test(line.msg))),
    [logs, showTranscripts],
  );
  const hiddenCount = logs.length - shown.length;

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [open, shown]);

  if (logs.length === 0) return null;

  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    writeStored(CLI_LOG_KEY, next ? "open" : "closed");
    if (next) following.current = true;
  };

  const toggleTranscripts = () => {
    const next = !showTranscripts;
    setShowTranscripts(next);
    writeStored(CLI_LOG_TRANSCRIPT_KEY, next ? "1" : "0");
  };

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) following.current = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_SLACK;
  };

  return (
    <div
      data-testid="cli-log"
      className={cn(
        "w-full min-w-0",
        easy ? "border-y border-hairline" : "overflow-hidden rounded-2xl bg-raised shadow-ring",
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={toggleOpen}
        className={cn(
          "flex w-full items-center justify-between gap-3 px-3 text-left font-medium text-foreground",
          easy ? "min-h-12 text-xl" : "h-9 text-[13px]",
        )}
      >
        <span>{t.topbar.cliLog}</span>
        <ChevronDown
          aria-hidden="true"
          className={cn(
            "shrink-0 text-ink-2 transition-transform motion-reduce:transition-none",
            easy ? "size-6" : "size-4",
            !open && "-rotate-90",
          )}
        />
      </button>

      {open ? (
        <div id={bodyId} className="border-t border-hairline">
          <div
            className={cn(
              "flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-1",
              easy ? "text-xl" : "text-[12px]",
            )}
          >
            <button
              type="button"
              role="switch"
              aria-checked={showTranscripts}
              data-testid="cli-log-transcript-toggle"
              onClick={toggleTranscripts}
              className="inline-flex min-h-8 items-center gap-2 rounded-full text-ink-2"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "relative inline-flex h-4 w-7 shrink-0 rounded-full transition-colors motion-reduce:transition-none",
                  showTranscripts ? "bg-foreground" : "bg-ink-3/40",
                )}
              >
                <span
                  className={cn(
                    "absolute top-0.5 left-0.5 size-3 rounded-full bg-raised transition-transform motion-reduce:transition-none",
                    showTranscripts && "translate-x-3",
                  )}
                />
              </span>
              {t.topbar.cliLogTranscripts}
            </button>
            {hiddenCount > 0 ? (
              <span data-testid="cli-log-hidden" className="text-ink-3">
                {t.topbar.cliLogHidden(hiddenCount)}
              </span>
            ) : null}
          </div>
          <div
            ref={scrollRef}
            onScroll={onScroll}
            role="region"
            aria-label={t.topbar.cliLog}
            tabIndex={0}
            className={cn(
              "max-h-[160px] overflow-y-auto px-3 pb-2 font-mono sm:max-h-[220px]",
              easy ? "text-xl leading-8" : "text-[13px] leading-6",
            )}
          >
            {shown.map((line) => (
              <div key={line.first} className={cn("break-words whitespace-pre-wrap", !easy && LEVEL_TEXT[line.level])}>
                <span className={cn(!easy && "text-ink-3")}>
                  {startedT === null ? clockText(line.t) : offsetText(line.t, startedT)}
                </span>{" "}
                <span>[{line.source}]</span>{" "}
                <span>{line.msg}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
