import { useId, useRef, useState } from "react";
import { Check } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { ActivityOrb, type ActivityOrbProps, type OrbMode } from "@/components/live/activity-orb";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatClock, useI18n, type Messages } from "@/i18n";
import { useElementSize } from "@/hooks/use-element-size";
import { useMediaQuery } from "@/hooks/use-media-query";
import { DASH, formatElapsed, formatMs, formatRtf } from "@/lib/format";
import { type DisplayPhase, type LatencyStats, type RunState } from "@/lib/live-state";
import { deviceText, languageText } from "@/lib/live-view";
import { useSpeakerName } from "@/lib/speaker-names";
import { cn } from "@/lib/utils";

type StageText = Messages["stage"];

/** Up to and including 640 px: the orb and the stats collapse into one summary strip. */
const PHONE_QUERY = "(max-width: 640px)";
/** The orb in the phone summary strip. */
const PHONE_SUMMARY_ORB_PX = 32;

export interface StageCardProps {
  run: RunState | null;
  phase: DisplayPhase;
  /** Below 1100 px: a smaller orb. */
  compact: boolean;
  orbMode: OrbMode;
  envelope: number[];
  pulseKey: number;
  speakerColors: string[];
  activeColor: string | undefined;
  /** 0..1 */
  progress: number;
  /** The transcribed-of-total reading in the page's locale, e.g. "01:12 / 03:23", or a dash. */
  transcribed: string;
  latency: LatencyStats;
  rtf: number | null;
  elapsed: number | null;
  /** The run has ended or the connection is lost: animations stop and the last update time shows. */
  frozen?: boolean;
  /** Unix seconds of the last update. Shown as "Last update hh:mm:ss" while frozen. */
  lastUpdateT?: number | null;
  /** A picked run whose snapshot has not arrived yet: the phase row reads "Loading…", not "Listening for a run…". */
  loading?: boolean;
}

export function StageCard({
  run,
  phase,
  compact,
  orbMode,
  envelope,
  pulseKey,
  speakerColors,
  activeColor,
  progress,
  transcribed,
  latency,
  rtf,
  elapsed,
  frozen = false,
  lastUpdateT = null,
  loading = false,
}: StageCardProps) {
  const { t, locale } = useI18n();
  const s = t.stage;
  const speakerName = useSpeakerName();
  const phone = useMediaQuery(PHONE_QUERY);
  const statsId = useId();
  const [statsOpen, setStatsOpen] = useState(false);

  // The bar and the number share one value: the bar is drawn at exactly the whole percentage shown.
  // A phase with no measured percentage (pct 0) shows no number at all, so the bar never reads "0%".
  const pctValue = run ? Math.round(Math.min(1, Math.max(0, progress)) * 100) : 0;
  const showPercent = pctValue > 0;

  const phaseName = phaseText(s, run, phase);
  const orbLabel = orbLabelFor(s, run, phase);
  const timed = hasTimeline(run, phase);

  // The same eight tiles in every phase, so the grid never gains or loses a row. A value not known yet reads as a dash.
  const stats: Stat[] = [
    { label: s.stats.model, value: run?.model ?? DASH, hint: s.hints.model },
    { label: s.stats.device, value: deviceText(run) ?? DASH, hint: s.hints.device },
    {
      label: s.stats.latency,
      value: latency.last !== null ? formatMs(latency.last) : DASH,
      hint: latencyHintText(s, latency),
    },
    { label: s.stats.rtf, value: rtf !== null ? formatRtf(rtf) : DASH, hint: s.hints.rtf },
    { label: s.stats.language, value: languageText(run) ?? DASH, hint: s.hints.language },
    {
      label: s.stats.speakers,
      value: run && run.speakers.length > 0 ? String(run.speakers.length) : DASH,
      hint: speakerHint(s, run, speakerName),
    },
    { label: s.stats.elapsed, value: formatElapsed(elapsed), hint: s.hints.elapsed },
    { label: s.stats.segments, value: run ? String(run.segments.length) : DASH, hint: s.hints.segments },
  ];

  // A frozen run stops its spinner: the pill's CSS animations are paused on their current frame.
  const phaseRowClass = cn(
    "flex min-h-[30px] items-center justify-center text-center",
    frozen && "[&_*]:[animation-play-state:paused]!",
  );

  // Both slots are always present, with a dash for an unknown value, so the strip keeps its width.
  const summary = `${formatElapsed(elapsed)} · ${run ? s.segmentCount(run.segments.length) : DASH}`;

  return (
    <section
      aria-label={s.runStatusLabel}
      data-testid="stage-card"
      data-frozen={frozen ? "true" : "false"}
      className={cn("live-card flex min-h-0 flex-1 flex-col gap-3 p-5", phone && "gap-2.5 p-4")}
    >
      {phone ? (
        <div className="flex min-w-0 items-center gap-2.5 text-[13px]" data-testid="stage-summary">
          <ActivityOrb
            mode={orbMode}
            envelope={envelope}
            pulseKey={pulseKey}
            progress={progress}
            speakerColors={speakerColors}
            activeColor={activeColor}
            size={PHONE_SUMMARY_ORB_PX}
            frozen={frozen}
            label={orbLabel}
          />
          <span className="min-w-0 truncate font-medium text-foreground">{phaseName}</span>
          <span className="min-w-0 truncate font-mono tabular-nums text-ink-3">{summary}</span>
          <button
            type="button"
            data-testid="stats-toggle"
            aria-expanded={statsOpen}
            aria-controls={statsId}
            onClick={() => setStatsOpen((open) => !open)}
            className="ml-auto shrink-0 rounded-md px-2 py-1 text-[12px] text-ink-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {statsOpen ? s.hideDetails : s.showDetails}
          </button>
        </div>
      ) : (
        <OrbArea
          compact={compact}
          mode={orbMode}
          envelope={envelope}
          pulseKey={pulseKey}
          progress={progress}
          speakerColors={speakerColors}
          activeColor={activeColor}
          frozen={frozen}
          label={orbLabel}
        />
      )}

      {/* The phase is named once: in the phone strip above, or in this row on wider screens. */}
      {phone ? null : (
        <div className={phaseRowClass}>
          <PhaseRow run={run} phase={phase} elapsed={elapsed} s={s} loading={loading} />
        </div>
      )}

      <div>
        <div className="h-[2px] w-full overflow-hidden rounded-full bg-hairline">
          <div
            className="h-full rounded-full bg-foreground transition-[width] duration-500 ease-out"
            style={{ width: `${pctValue}%` }}
          />
        </div>
        {/* The progress line never repeats the phase name: the row above already names it. */}
        <div className="mt-2 flex h-5 items-baseline justify-between gap-3 text-[12px] tabular-nums">
          <span className={cn("min-w-0 truncate text-ink-3", timed && "font-mono")}>{timed ? transcribed : DASH}</span>
          <span className="shrink-0 text-ink-2">{showPercent ? `${pctValue}%` : null}</span>
        </div>
      </div>

      {/* Always reserves its line, so the card does not move when the run freezes. */}
      <p data-testid="last-update" className="min-h-[20px] text-center text-[12px] tabular-nums text-ink-3">
        {frozen && lastUpdateT !== null ? s.lastUpdate(formatClock(lastUpdateT, locale)) : null}
      </p>

      {/* A plain grid, never a horizontal scroller: the stat tiles are read-only and are not tab stops. */}
      <div id={statsId} className={cn("grid grid-cols-2 gap-1.5", phone && !statsOpen && "hidden")}>
        {stats.map((stat) => (
          <StatTile key={stat.label} label={stat.label} value={stat.value} hint={stat.hint} />
        ))}
      </div>
    </section>
  );
}

/**
 * The desktop orb's box. It mounts only off-phone, and useElementSize observes once, on mount, so a
 * window that crosses the phone breakpoint gets a fresh measurement when this box appears.
 */
type OrbAreaProps = Omit<ActivityOrbProps, "size" | "className"> & { compact: boolean };

function OrbArea({ compact, ...orb }: OrbAreaProps) {
  const ref = useRef<HTMLDivElement>(null);
  const area = useElementSize(ref);
  // Desktop: the orb takes the room the stats leave over, between 120 and 260 px. Below 1100 px it is 140 px.
  const size = compact ? 140 : area.height > 0 ? Math.round(Math.min(260, Math.max(120, area.height - 8))) : 260;
  return (
    <div ref={ref} className={cn("flex items-center justify-center", compact ? "shrink-0" : "min-h-0 flex-1")}>
      <ActivityOrb {...orb} size={size} />
    </div>
  );
}

interface Stat {
  label: string;
  value: string;
  hint: string;
}

/**
 * A read-only stat. A plain div with no tabIndex or button role: the hint appears on pointer hover only,
 * so the keyboard order skips the stats.
 */
function StatTile({ label, value, hint }: { label: string; value: string; hint: string }) {
  const unknown = value === DASH;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div data-testid="stat-card" className="min-w-0 cursor-default rounded-[12px] bg-raised px-3 py-1 shadow-ring">
          <span className="block truncate text-[12px] leading-4 text-ink-2">{label}</span>
          <span
            className={cn(
              "mt-0.5 block truncate text-[14px] leading-5 font-medium tabular-nums",
              unknown ? "text-ink-3" : "text-foreground",
            )}
          >
            {value}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        className="max-w-[280px] rounded-[10px] bg-popover px-3 py-2 text-[12px] leading-snug text-popover-foreground shadow-ring [&>svg]:bg-popover [&>svg]:fill-popover"
      >
        {hint}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * True when the "transcribed / length" reading can be shown: the audio length is known and transcription has
 * begun (or the run has ended). Before that the line stays a dash, so it never reads "00:00 / —".
 */
function hasTimeline(run: RunState | null, phase: DisplayPhase): boolean {
  if (!run || run.duration === null || run.duration <= 0) return false;
  return phase === "transcribing" || phase === "finished" || phase === "error" || phase === "canceled";
}

function speakerHint(s: StageText, run: RunState | null, speakerName: (label: string) => string): string {
  return run && run.speakers.length > 0
    ? s.hints.speakersFound(run.speakers.map((label) => speakerName(label)).join(", "))
    : s.hints.speakersNone;
}

const msText = (value: number) => `${Math.round(value)} ms`;

function latencyHintText(s: StageText, stats: LatencyStats): string {
  if (stats.last === null || stats.median === null) return s.hints.latencyUnmeasured;
  const split =
    stats.tail !== null && stats.push !== null ? s.hints.latencySplit(msText(stats.tail), msText(stats.push)) : "";
  return s.hints.latencyMeasured(msText(stats.last), msText(stats.median), split);
}

/** A run the viewer found stale with no end status: the process stopped without reporting why. */
function stoppedRun(run: RunState | null): boolean {
  return Boolean(run?.stale && !run.endStatus);
}

/** The phase's name, with the diarization detail (segmenting, comparing voices) when the CLI reports one. */
function phaseText(s: StageText, run: RunState | null, phase: DisplayPhase): string {
  if (phase === "diarizing" && run?.progress?.detail === "segmentation") return s.phase.segmenting;
  if (phase === "diarizing" && run?.progress?.detail === "embeddings") return s.phase.comparingVoices;
  if (phase === "error" && stoppedRun(run)) return s.phase.stopped;
  return s.phase[phase];
}

/** The orb's accessible name says the same state as the title: Failed, Stopped or Canceled. Other phases keep the mode's name. */
function orbLabelFor(s: StageText, run: RunState | null, phase: DisplayPhase): string | undefined {
  if (phase === "error") return stoppedRun(run) ? s.orbAria.stopped : s.orbAria.failed;
  if (phase === "canceled") return s.orbAria.canceled;
  return undefined;
}

/**
 * The pill (and whatever sits beside it) that names the current phase. A failed or stopped run is named here
 * by its title alone; its message and details live in the transcript card, not in this panel.
 */
function PhaseRow({
  run,
  phase,
  elapsed,
  s,
  loading,
}: {
  run: RunState | null;
  phase: DisplayPhase;
  elapsed: number | null;
  s: StageText;
  loading: boolean;
}) {
  switch (phase) {
    case "waiting":
      // A picked run whose snapshot is still on its way is loading, not a run the page is listening for.
      return <Orb variant="C2" pill label={loading && !run ? s.loadingRun : s.listeningForRun} />;
    case "loading":
    case "listening":
      return <Orb variant="S1" pill label={phaseText(s, run, phase)} />;
    case "converting":
      return <Orb variant="S2" pill label={phaseText(s, run, phase)} />;
    case "diarizing":
      return <Orb variant="B2" pill label={diarizingText(s, run)} />;
    case "transcribing":
      return <Orb variant="C3" pill label={phaseText(s, run, phase)} />;
    case "finished":
      return (
        <p className="flex items-center gap-2 text-[14px] text-ink-2">
          <Check className="size-4 text-foreground" aria-hidden="true" />
          {elapsed !== null ? s.finishedIn(formatElapsed(elapsed)) : s.phase.finished}
        </p>
      );
    case "error":
    case "canceled":
      return <p className="max-w-full truncate text-[14px] font-medium text-foreground">{phaseText(s, run, phase)}</p>;
  }
}

/** "Identifying speakers · comparing voices" while diarization reports which step it is on. */
function diarizingText(s: StageText, run: RunState | null): string {
  const detail = run?.progress?.detail;
  if (detail === "segmentation") return s.diarizingSegmenting;
  if (detail === "embeddings") return s.diarizingComparing;
  return s.phase.diarizing;
}
