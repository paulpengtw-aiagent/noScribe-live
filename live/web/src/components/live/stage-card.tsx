import { useId, useRef, useState } from "react";
import { Check } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { ActivityOrb, type ActivityOrbProps, type OrbMode } from "@/components/live/activity-orb";
import { ErrorDetails } from "@/components/live/error-details";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatClock, useI18n, type Messages } from "@/i18n";
import { useElementSize } from "@/hooks/use-element-size";
import { useMediaQuery } from "@/hooks/use-media-query";
import { describeEnd } from "@/lib/end-state";
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
  /** "01:12 of 03:23", or a dash. */
  transcribed: string;
  latency: LatencyStats;
  rtf: number | null;
  elapsed: number | null;
  /** The run has ended or the connection is lost: animations stop and the last update time shows. */
  frozen?: boolean;
  /** Unix seconds of the last update. Shown as "Last update hh:mm:ss" while frozen. */
  lastUpdateT?: number | null;
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
  const timed = hasTimeline(run, phase);

  // Latency and RTF are shown only when they can be computed: a finished run opened from history has
  // no live segments to measure, so its Latency tile is left out rather than reading a dash.
  const stats: Stat[] = [
    { label: s.stats.model, value: run?.model ?? DASH, hint: s.hints.model },
    { label: s.stats.device, value: deviceText(run) ?? DASH, hint: s.hints.device },
    ...(latency.last !== null
      ? [{ label: s.stats.latency, value: formatMs(latency.last), hint: latencyHintText(s, latency) }]
      : []),
    ...(rtf !== null ? [{ label: s.stats.rtf, value: formatRtf(rtf), hint: s.hints.rtf }] : []),
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

  const summary = [
    elapsed !== null ? formatElapsed(elapsed) : null,
    run ? s.segmentCount(run.segments.length) : null,
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");

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
          />
          <span className="min-w-0 truncate font-medium text-foreground">{phaseName}</span>
          {summary ? <span className="min-w-0 truncate font-mono tabular-nums text-ink-3">{summary}</span> : null}
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
        />
      )}

      {/* On phones the strip already names the phase, so the pill only appears for a failure, which carries details. */}
      {!phone || phase === "error" || phase === "canceled" ? (
        <div className={phaseRowClass}>
          <PhaseRow run={run} phase={phase} elapsed={elapsed} s={s} errors={t.errors} />
        </div>
      ) : null}

      <div>
        <div className="h-[2px] w-full overflow-hidden rounded-full bg-hairline">
          <div
            className="h-full rounded-full bg-foreground transition-[width] duration-500 ease-out"
            style={{ width: `${pctValue}%` }}
          />
        </div>
        <div className="mt-2 flex h-5 items-baseline justify-between gap-3 text-[12px] tabular-nums">
          <span className={cn("min-w-0 truncate text-ink-3", timed && "font-mono")}>
            {timed ? transcribed : run ? phaseName : DASH}
          </span>
          {showPercent ? <span className="shrink-0 text-ink-2">{`${pctValue}%`}</span> : null}
        </div>
      </div>

      {frozen && lastUpdateT !== null ? (
        <p data-testid="last-update" className="text-center text-[12px] tabular-nums text-ink-3">
          {s.lastUpdate(formatClock(lastUpdateT, locale))}
        </p>
      ) : null}

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
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="min-w-0 cursor-default rounded-[12px] bg-raised px-3 py-1 shadow-ring">
          <span className="block truncate text-[12px] leading-4 text-ink-2">{label}</span>
          <span className="mt-0.5 block truncate text-[14px] leading-5 font-medium tabular-nums text-foreground">
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
 * True when "mm:ss of mm:ss" can be shown: the audio length is known and transcription has begun
 * (or the run has ended). Before that the line names the phase instead, so it never reads "00:00 of —".
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

/** The phase's name, with the diarization detail (segmenting, comparing voices) when the CLI reports one. */
function phaseText(s: StageText, run: RunState | null, phase: DisplayPhase): string {
  if (phase === "diarizing" && run?.progress?.detail === "segmentation") return s.phase.segmenting;
  if (phase === "diarizing" && run?.progress?.detail === "embeddings") return s.phase.comparingVoices;
  if (phase === "error" && run?.stale && !run.endStatus) return s.phase.stoppedUnexpectedly;
  return s.phase[phase];
}

/** The pill (and whatever sits beside it) that names the current phase. */
function PhaseRow({
  run,
  phase,
  elapsed,
  s,
  errors,
}: {
  run: RunState | null;
  phase: DisplayPhase;
  elapsed: number | null;
  s: StageText;
  errors: Messages["errors"];
}) {
  switch (phase) {
    case "waiting":
      return <Orb variant="C2" pill label={s.listeningForRun} />;
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
    case "canceled": {
      const end = run ? describeEnd(run, errors) : null;
      return (
        <div className="min-w-0 max-w-full">
          <p className="text-[14px] font-medium text-foreground">{phaseText(s, run, phase)}</p>
          {end ? (
            <>
              <p className="mt-1 text-[13px] leading-5 break-words text-ink-2">{end.title}</p>
              {end.detail ? <p className="text-[13px] leading-5 break-words text-ink-3">{end.detail}</p> : null}
              {end.rawError ? <ErrorDetails raw={end.rawError} className="mt-2" /> : null}
            </>
          ) : null}
        </div>
      );
    }
  }
}

/** "Identifying speakers · comparing voices" while diarization reports which step it is on. */
function diarizingText(s: StageText, run: RunState | null): string {
  const detail = run?.progress?.detail;
  if (detail === "segmentation") return s.diarizingSegmenting;
  if (detail === "embeddings") return s.diarizingComparing;
  return s.phase.diarizing;
}
