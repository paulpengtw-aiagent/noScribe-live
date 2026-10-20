import { useMemo, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useNow } from "@/hooks/use-now";
import { DASH, formatDateTime, formatDay, formatElapsed } from "@/lib/format";
import { FOLLOW_NEWEST, isLiveSummary, runName } from "@/lib/live-view";
import type { RunStatus, RunSummary } from "@/lib/live-types";
import { cn } from "@/lib/utils";

/** The status word shown per run. "live" is a run the server reports as still running. */
type PickerStatus = "live" | "finished" | "failed" | "stopped" | "canceled";

const PICKER_STATUS: Record<RunStatus, PickerStatus> = {
  running: "live",
  finished: "finished",
  error: "failed",
  stale: "stopped",
  canceled: "canceled",
};

const STATUS_LABEL: Record<PickerStatus, string> = {
  live: "Live",
  finished: "Finished",
  failed: "Failed",
  stopped: "Stopped",
  canceled: "Canceled",
};

/** Dot and label colours per status. Live pulses; canceled is a hollow grey dot. */
const STATUS_STYLE: Record<PickerStatus, { dot: string; text: string }> = {
  live: { dot: "bg-emerald-500 animate-pulse", text: "text-emerald-700 dark:text-emerald-400" },
  finished: { dot: "bg-foreground/60", text: "text-ink-2" },
  failed: { dot: "bg-red-500", text: "text-red-600 dark:text-red-400" },
  stopped: { dot: "bg-amber-500", text: "text-amber-700 dark:text-amber-400" },
  canceled: { dot: "border border-ink-2 bg-transparent", text: "text-ink-2" },
};

/** cmdk value of the "Follow newest run" item. Not a run id. */
const FOLLOW_ITEM = "__follow_newest__";

function pickerStatus(run: RunSummary): PickerStatus {
  return isLiveSummary(run) ? "live" : PICKER_STATUS[run.status];
}

interface RunDay {
  day: string;
  runs: RunSummary[];
}

/** Newest run first, grouped by local day with the newest day first. Runs without a start time go last. */
function groupRunsByDay(runs: readonly RunSummary[]): RunDay[] {
  const sorted = [...runs].sort((a, b) => (b.started_t ?? -1) - (a.started_t ?? -1));
  const days: RunDay[] = [];
  for (const run of sorted) {
    const day = run.started_t == null ? DASH : formatDay(run.started_t);
    const last = days[days.length - 1];
    if (last && last.day === day) last.runs.push(run);
    else days.push({ day, runs: [run] });
  }
  return days;
}

/** Filter by file name, run id or status. `query` is already trimmed and lower-cased. */
function matchesQuery(run: RunSummary, query: string): boolean {
  if (!query) return true;
  const haystack = [runName(run), run.run_id, STATUS_LABEL[pickerStatus(run)], run.status].join(" ").toLowerCase();
  return haystack.includes(query);
}

/** Live runs show the time elapsed so far; ended runs show the audio duration. */
function durationText(run: RunSummary, status: PickerStatus, nowMs: number): string {
  if (status === "live") return run.started_t == null ? DASH : formatElapsed(nowMs / 1000 - run.started_t);
  return formatElapsed(run.duration);
}

function segmentText(count: number): string {
  return count === 1 ? "1 segment" : `${count} segments`;
}

export interface RunPickerProps {
  runs: RunSummary[];
  /** FOLLOW_NEWEST, or the run_id of the shown run. */
  value: string;
  onChange: (value: string) => void;
}

/**
 * The run history: a button that shows the selected run, and a popover with a filter box and the
 * runs grouped by day. Built on the shadcn Popover and Command (cmdk), which handle the keyboard.
 */
export function RunPicker({ runs, value, onChange }: RunPickerProps) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  // The clock ticks only while the list is open, for the elapsed time of live runs.
  const now = useNow(open);
  const query = filter.trim().toLowerCase();
  const days = useMemo(() => groupRunsByDay(runs.filter((run) => matchesQuery(run, query))), [runs, query]);
  const visible = days.reduce((count, day) => count + day.runs.length, 0);
  const chosen = value === FOLLOW_NEWEST ? null : (runs.find((run) => run.run_id === value) ?? null);

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setFilter("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="run-picker"
          className="h-8 w-[150px] min-w-0 justify-between gap-2 rounded-full bg-background px-3.5 text-[13px] font-normal dark:bg-background sm:w-[300px]"
        >
          {chosen ? (
            <span className="flex min-w-0 flex-1 items-center gap-2 text-left">
              <span className="min-w-0 truncate">{runName(chosen)}</span>
              <span className="hidden shrink-0 tabular-nums text-ink-3 sm:inline">
                {formatDateTime(chosen.started_t)}
              </span>
            </span>
          ) : value === FOLLOW_NEWEST ? (
            <span className="min-w-0 flex-1 truncate text-left">
              <span className="sm:hidden">Follow newest</span>
              <span className="hidden sm:inline">Follow newest run</span>
            </span>
          ) : (
            <span className="min-w-0 flex-1 truncate text-left">{value}</span>
          )}
          <ChevronDown className="size-3.5 shrink-0 opacity-60" aria-hidden="true" />
        </Button>
      </PopoverTrigger>

      <PopoverContent align="end" sideOffset={6} className="w-[min(92vw,420px)] overflow-hidden rounded-[14px] p-0">
        <Command shouldFilter={false} className="rounded-[14px]">
          <CommandInput
            data-testid="run-filter"
            aria-label="Filter runs"
            placeholder="Filter by file, run id or status"
            value={filter}
            onValueChange={setFilter}
          />
          <CommandList className="max-h-[60vh]">
            <CommandItem value={FOLLOW_ITEM} data-testid="run-option-follow" onSelect={() => choose(FOLLOW_NEWEST)}>
              <Check
                aria-hidden="true"
                className={cn("size-4 shrink-0", value === FOLLOW_NEWEST ? "opacity-100" : "opacity-0")}
              />
              <span>Follow newest run</span>
            </CommandItem>

            {days.map((group) => (
              <CommandGroup key={group.day} heading={group.day} data-testid="run-group" data-day={group.day}>
                {group.runs.map((run) => {
                  const status = pickerStatus(run);
                  const style = STATUS_STYLE[status];
                  return (
                    <CommandItem
                      key={run.run_id}
                      value={run.run_id}
                      data-testid="run-option"
                      data-run-id={run.run_id}
                      data-status={status}
                      onSelect={() => choose(run.run_id)}
                      className="items-start gap-3 py-2"
                    >
                      <span aria-hidden="true" className={cn("mt-1.5 size-2 shrink-0 rounded-full", style.dot)} />
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="min-w-0 flex-1 truncate font-medium">{runName(run)}</span>
                          <span className={cn("shrink-0 text-[12px]", style.text)}>{STATUS_LABEL[status]}</span>
                        </span>
                        <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-[12px] tabular-nums text-ink-2">
                          <span>{formatDateTime(run.started_t)}</span>
                          <span aria-hidden="true">·</span>
                          <span>{durationText(run, status, now)}</span>
                          <span aria-hidden="true">·</span>
                          <span>{segmentText(run.segments)}</span>
                        </span>
                      </span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ))}

            {visible === 0 && (
              <p className="px-3 py-6 text-center text-[13px] text-ink-2">
                {runs.length === 0 ? "No runs yet." : `No runs match "${filter.trim()}".`}
              </p>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
