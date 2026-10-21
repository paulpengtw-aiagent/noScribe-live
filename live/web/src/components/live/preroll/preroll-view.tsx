import { useEffect, useRef, useState, type JSX } from "react";
import { motion } from "motion/react";
import { ActivityOrb } from "@/components/live/activity-orb";
import type { OrbMode } from "@/lib/orb-renderer";
import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/i18n";
import { useNow } from "@/hooks/use-now";
import { useMediaQuery } from "@/hooks/use-media-query";
import { formatElapsed } from "@/lib/format";
import { displayPhase, elapsedSeconds, progressFraction, type DisplayPhase, type RunState } from "@/lib/live-state";
import { barText, formatDuration, prerollLines, type PrerollLine } from "@/lib/preroll-log";
import type { PrerollMessages } from "@/i18n/catalog/preroll";
import { cn } from "@/lib/utils";

/** The terminal types about 70 characters a second, one character per tick. */
const TICK_MS = 14;
const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const PHONE_QUERY = "(max-width: 640px)";

const ORB_MODE: Record<DisplayPhase, OrbMode> = {
  waiting: "idle",
  converting: "converting",
  diarizing: "diarizing",
  loading: "thinking",
  listening: "thinking",
  transcribing: "transcribing",
  finished: "finished",
  error: "error",
  canceled: "error",
};

/** The stat rows the terminal hands over to the stat cards in the full UI. */
const STAT_LAYOUT: Partial<Record<PrerollLine["id"], string>> = {
  speakers: "stat-speakers",
  model: "stat-model",
  device: "stat-device",
  language: "stat-language",
};

interface Row {
  id: string;
  text: string;
  state: PrerollLine["state"];
  layoutId?: string;
}

function rowText(line: PrerollLine, s: PrerollMessages): string {
  const x = line.text;
  switch (x.kind) {
    case "audio":
      return s.lines.audio(x.name) + (x.duration !== null ? ` · ${formatDuration(x.duration)}` : "");
    case "convert":
      return s.lines.convert;
    case "detect": {
      const label = x.step === "segmentation" ? s.lines.segmentation : s.lines.embeddings;
      return x.pct === null ? label : `${label} ${barText(x.pct)} ${Math.round(x.pct)}%`;
    }
    case "speakers":
      return s.lines.speakers(x.count);
    case "model":
      return s.lines.model(x.model);
    case "device": {
      const parts = [x.name, x.device?.toUpperCase() ?? null, x.computeType];
      if (x.loadSeconds !== null) parts.push(s.loadedIn(x.loadSeconds.toFixed(1)));
      const detail = parts.filter((part): part is string => part !== null && part !== "").join(" · ");
      return detail ? `${s.lines.device}  ${detail}` : s.lines.device;
    }
    case "language":
      return s.lines.language(x.code) + (x.percent !== null ? ` · ${x.percent}%` : "");
    case "firstSegment":
      return s.lines.firstSegment;
  }
}

/** Types the rows one after another. A row that already finished typing shows its new text at once (progress bars). */
function useTyping(rows: readonly Row[], reduce: boolean): Record<string, number> {
  const [typed, setTyped] = useState<Record<string, number>>({});
  const rowsRef = useRef(rows);
  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);
  useEffect(() => {
    if (reduce) return;
    const timer = window.setInterval(() => {
      setTyped((prev) => {
        for (const row of rowsRef.current) {
          const at = prev[row.id];
          if (at === undefined) return { ...prev, [row.id]: 0 };
          if (at < row.text.length) return { ...prev, [row.id]: at + 1 };
        }
        return prev;
      });
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [reduce]);
  return typed;
}

function Spinner() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setFrame((f) => (f + 1) % SPINNER.length), 90);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <span aria-hidden="true" className="inline-block w-[1ch] text-ink-2">
      {SPINNER[frame]}
    </span>
  );
}

function useViewport(): { w: number; h: number } {
  const [size, setSize] = useState(() => ({ w: window.innerWidth, h: window.innerHeight }));
  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return size;
}

export interface PrerollViewProps {
  run: RunState;
  /** "morph": the full UI is mounted beside this view; the shared elements fly to it and the view fades out. */
  morphing: boolean;
  easy: boolean;
  reduce: boolean;
}

/** The cinematic pre-roll: a large orb, a terminal fed by the run, and one status line. Lazy-loaded by App. */
export default function PrerollView({ run, morphing, easy, reduce }: PrerollViewProps): JSX.Element {
  const { t } = useI18n();
  const s = t.preroll;
  const phone = useMediaQuery(PHONE_QUERY);
  const { w, h } = useViewport();
  const now = useNow(true, 250);
  const phase = displayPhase(run);
  const pct = Math.round(progressFraction(run) * 100);
  const elapsed = elapsedSeconds(run, now);
  const rows: Row[] = prerollLines(run).map((line) => ({
    id: line.id,
    text: rowText(line, s),
    state: line.state,
    layoutId: STAT_LAYOUT[line.id],
  }));
  const typed = useTyping(rows, reduce || easy);
  const orbSize = phone ? Math.round(w * 0.7) : Math.round(Math.min(w, h) * 0.55);
  const fade = morphing ? 0 : 1;
  const status = `${s.status[phase]} · ${s.elapsed(formatElapsed(elapsed))}`;

  if (easy) {
    return (
      <motion.section
        data-testid="preroll"
        data-easy="true"
        animate={{ opacity: fade }}
        transition={{ duration: 0.4 }}
        className="flex min-h-[60svh] flex-col items-center justify-center gap-8 px-6 text-center"
      >
        <p data-testid="preroll-status" className="text-[28px] leading-snug font-medium text-foreground">
          {s.status[phase]}
        </p>
        <Progress value={pct} className="h-[3px]! w-full max-w-[520px] bg-hairline!" aria-label={s.status[phase]} />
      </motion.section>
    );
  }

  return (
    <motion.section
      data-testid="preroll"
      animate={{ opacity: fade }}
      transition={{ duration: 0.6 }}
      className="flex min-h-[70svh] flex-col items-center justify-center gap-6 px-4 py-8"
    >
      <motion.div layoutId="orb" className="flex shrink-0 items-center justify-center">
        <ActivityOrb
          mode={ORB_MODE[phase]}
          envelope={[]}
          pulseKey={run.liveCount}
          progress={progressFraction(run)}
          speakerColors={[]}
          size={orbSize}
          frozen={reduce}
          prominent
        />
      </motion.div>
      <div
        data-testid="preroll-terminal"
        role="log"
        aria-live="polite"
        aria-label={s.terminalAria}
        className="w-full max-w-[min(92vw,720px)] font-mono text-[14px] leading-6 text-foreground"
      >
        {rows.map((row) => {
          const at = typed[row.id];
          if (!reduce && at === undefined && !easy) return null;
          const shown = reduce || at === undefined ? row.text : row.text.slice(0, at);
          const typing = !reduce && at !== undefined && at < row.text.length;
          return (
            <motion.div
              key={row.id}
              layoutId={row.layoutId}
              data-testid="preroll-line"
              data-line={row.id}
              className="flex min-w-0 items-baseline gap-2 break-words"
            >
              <span aria-hidden="true" className="text-ink-3">
                ›
              </span>
              <span className="min-w-0 break-words">
                {shown}
                {typing ? <span aria-hidden="true" className="animate-pulse">▍</span> : null}
              </span>
              {typing ? null : row.state === "running" ? (
                <Spinner />
              ) : (
                <span aria-hidden="true" className={cn("shrink-0 text-foreground")}>
                  {s.done}
                </span>
              )}
            </motion.div>
          );
        })}
      </div>
      <p data-testid="preroll-status" className="text-center text-[14px] text-ink-2 tabular-nums">
        {status}
      </p>
    </motion.section>
  );
}
