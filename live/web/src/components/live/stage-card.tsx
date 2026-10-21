import { useId, useRef, useState } from "react";
import { motion } from "motion/react";
import { Check, ChevronDown } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { ActivityOrb, type ActivityOrbProps, type OrbMode } from "@/components/live/activity-orb";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatClock, useI18n, type Messages } from "@/i18n";
import { useEasyView } from "@/hooks/use-easy-view";
import { useElementSize } from "@/hooks/use-element-size";
import { useMediaQuery } from "@/hooks/use-media-query";
import { DASH, formatElapsed, formatMs, formatRtf } from "@/lib/format";
import { type DisplayPhase, type LatencyStats, type RunState } from "@/lib/live-state";
import type { RunSummary } from "@/lib/live-types";
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
  /** Easy view on a phone: the other live run's switch sits under the status sentence (the header has no room). */
  otherLive?: RunSummary | null;
  onRunChange?: (runId: string) => void;
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
  otherLive = null,
  onRunChange,
}: StageCardProps) {
  const { t, locale } = useI18n();
  const s = t.stage;
  const speakerName = useSpeakerName();
  const phone = useMediaQuery(PHONE_QUERY);
  const statsId = useId();
  const [statsOpen, setStatsOpen] = useState(false);
  const { easy } = useEasyView();
  const moreId = useId();
  const [moreOpen, setMoreOpen] = useState(false);
  // Easy view: the orb draws its still frame, the same as a frozen run.
  const orbFrozen = frozen || easy;
  // The run is live while it has a run that has not ended and is not frozen: the progress fill carries its sheen.
  const liveRun = run !== null && !frozen && phase !== "finished" && phase !== "error" && phase !== "canceled";

  // The bar and the number share one value: the bar is drawn at exactly the whole percentage shown.
  // A phase with no measured percentage (pct 0) shows no number at all, so the bar never reads "0%".
  const pctValue = run ? Math.round(Math.min(1, Math.max(0, progress)) * 100) : 0;
  const showPercent = pctValue > 0;

  const phaseName = phaseText(s, run, phase);
  const timed = hasTimeline(run, phase);
  // An ended run with no clock has no progress reading: its line stays empty, so the card keeps its height.
  const clockHidden = !timed && (phase === "finished" || phase === "error" || phase === "canceled");

  // The same eight tiles in every phase, so the grid never gains or loses a row. A value not known yet reads as a dash.
  const stats: Stat[] = [
    { label: s.stats.model, value: run?.model ?? DASH, hint: s.hints.model, hiddenInEasy: true, layoutId: "stat-model" },
    { label: s.stats.device, value: deviceText(run) ?? DASH, hint: s.hints.device, secondary: true, layoutId: "stat-device" },
    {
      label: s.stats.latency,
      value: latency.last !== null ? formatMs(latency.last) : DASH,
      hint: latencyHintText(s, latency),
      secondary: true,
    },
    { label: s.stats.rtf, value: rtf !== null ? formatRtf(rtf) : DASH, hint: s.hints.rtf, secondary: true },
    { label: s.stats.language, value: languageText(run) ?? DASH, hint: s.hints.language, secondary: true, layoutId: "stat-language" },
    {
      label: s.stats.speakers,
      value: run && run.speakers.length > 0 ? String(run.speakers.length) : DASH,
      hint: speakerHint(s, run, speakerName),
      layoutId: "stat-speakers",
    },
    { label: s.stats.elapsed, value: formatElapsed(elapsed), hint: s.hints.elapsed },
    { label: s.stats.segments, value: run ? String(run.segments.length) : DASH, hint: s.hints.segments },
  ];

  // Easy view: wider screens show the primary tiles and fold the rest behind "Show details". Phones fold every tile.
  const easyGrid: Stat[] = phone ? [] : stats.filter((stat) => !stat.secondary && !stat.hiddenInEasy);
  const easyFolded: Stat[] = phone ? stats.filter((stat) => !stat.hiddenInEasy) : stats.filter((stat) => stat.secondary);
  // Easy phone: the other-live switch and the "Show details" toggle share one row under the sentence, and an ended run
  // drops its progress bar (the status sentence already says how it ended).
  const phoneEasy = easy && phone;
  const ended = phase === "finished" || phase === "error" || phase === "canceled";
  const otherLiveButton =
    compact && otherLive ? (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        data-testid="other-live-run"
        onClick={() => onRunChange?.(otherLive.run_id)}
        className={cn(
          "h-auto min-h-12 rounded-full bg-raised py-2 text-[15px] text-foreground shadow-ring hover:bg-raised dark:bg-raised dark:hover:bg-raised",
          phoneEasy ? "min-w-0 flex-auto shrink px-2" : "w-full px-3",
        )}
      >
        <span
          aria-hidden="true"
          className={cn("size-1.5 shrink-0 animate-pulse rounded-full bg-foreground", phoneEasy && "hidden")}
        />
        <span>{t.topbar.otherLiveShort}</span>
      </Button>
    ) : null;
  const moreButton = (
    <button
      type="button"
      data-testid="easy-more"
      aria-expanded={moreOpen}
      aria-controls={moreId}
      onClick={() => setMoreOpen((open) => !open)}
      className={cn(
        "flex items-center justify-center gap-1.5 rounded-[12px] text-[17px] font-medium text-foreground shadow-ring hover:bg-raised",
        phoneEasy ? "min-h-12 min-w-0 flex-auto shrink px-1.5" : "w-full px-3",
      )}
    >
      {t.easy.moreInfo}
      {/* Easy phone: the row is one line only without the chevron; aria-expanded still carries the state. */}
      <ChevronDown
        aria-hidden="true"
        className={cn("size-4 shrink-0 transition-transform", moreOpen && "rotate-180", phoneEasy && "hidden")}
      />
    </button>
  );

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
      {/* Easy view: no orb. The status sentence leads the card on every width. */}
      {easy ? (
        <>
        <p
          data-testid="easy-status-sentence"
          className="text-center text-[22px] leading-snug font-medium break-words text-foreground"
        >
          {easySentence(s, run, phase, frozen, pctValue)}
        </p>
        {phoneEasy ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {otherLiveButton}
            {moreButton}
          </div>
        ) : (
          otherLiveButton
        )}
        </>
      ) : phone ? (
        <div className="flex min-w-0 items-center gap-2.5 text-[13px]" data-testid="stage-summary">
          <div
            data-orb-slot="stage"
            className="flex items-center justify-center"
            style={{ width: PHONE_SUMMARY_ORB_PX, height: PHONE_SUMMARY_ORB_PX, flex: "none", contain: "layout size" }}
          >
            <ActivityOrb
              mode={orbMode}
              envelope={envelope}
              pulseKey={pulseKey}
              progress={progress}
              speakerColors={speakerColors}
              activeColor={activeColor}
              size={PHONE_SUMMARY_ORB_PX}
              frozen={orbFrozen}
            />
          </div>
          {/* Wraps onto a second line instead of truncating: the phase, then the elapsed time and segment count. */}
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="font-medium break-words text-foreground">{phaseName}</span>
            <span className="font-mono break-words tabular-nums text-ink-3">{summary}</span>
          </div>
          <button
            type="button"
            data-testid="stats-toggle"
            aria-expanded={statsOpen}
            aria-controls={statsId}
            onClick={() => setStatsOpen((open) => !open)}
            className="shrink-0 rounded-md px-2 py-1 text-[12px] text-ink-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
          frozen={orbFrozen}
        />
      )}

      {/* The phase is named once: in the phone strip above, or in this row on wider screens. */}
      {phone || easy ? null : (
        <div className={phaseRowClass}>
          <PhaseRow run={run} phase={phase} elapsed={elapsed} s={s} loading={loading} />
        </div>
      )}

      <div className={cn(phoneEasy && ended && "hidden")}>
        <Progress value={pctValue} live={liveRun} className="h-[2px]! bg-hairline!" aria-label={s.progressLabel} />
        {/* The progress line never repeats the phase name: the row above already names it. */}
        <div className="mt-2 flex h-5 items-baseline justify-between gap-3 text-[12px] tabular-nums">
          <span className={cn("min-w-0 truncate text-ink-3", timed && "font-mono")}>
            {clockHidden ? null : timed ? transcribed : DASH}
          </span>
          <span className="shrink-0 text-ink-2">{showPercent ? `${pctValue}%` : null}</span>
        </div>
      </div>

      {/* Always reserves its line, so the card does not move when the run freezes. */}
      <p data-testid="last-update" className="min-h-[20px] text-center text-[12px] tabular-nums text-ink-3">
        {frozen && lastUpdateT !== null ? s.lastUpdate(formatClock(lastUpdateT, locale)) : null}
      </p>

      {/* A plain grid, never a horizontal scroller: the stat tiles are read-only and are not tab stops. */}
      <div
        id={statsId}
        className={cn(
          "grid grid-cols-2 gap-1.5",
          phone && !easy && !statsOpen && "hidden",
          // Easy phone: the toggle sits in the row under the sentence, so this grid holds only the details, when open.
          phoneEasy && !moreOpen && "hidden",
        )}
      >
        {(easy ? easyGrid : stats).map((stat) => (
          <StatTile key={stat.label} label={stat.label} value={stat.value} hint={stat.hint} layoutId={stat.layoutId} />
        ))}
        {easy ? (
          <div className="col-span-2 flex flex-col gap-1.5">
            {phone ? null : moreButton}
            <div id={moreId} hidden={!moreOpen} className="grid grid-cols-2 gap-1.5">
              {easyFolded.map((stat) => (
                <StatTile key={stat.label} label={stat.label} value={stat.value} hint={stat.hint} layoutId={stat.layoutId} />
              ))}
            </div>
          </div>
        ) : null}
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
  // Pinned: the desktop size is taken from the first measurement of this layout and then held, so the orb never
  // resizes when the stats or the log beside it grow. Desktop: between 120 and 260 px. Below 1100 px it is 140 px.
  const [pinnedPx, setPinnedPx] = useState<number | null>(null);
  if (!compact && pinnedPx === null && area.height > 0) {
    setPinnedPx(Math.round(Math.min(260, Math.max(120, area.height - 8))));
  }
  const size = compact ? 140 : (pinnedPx ?? 260);
  return (
    <div ref={ref} className={cn("flex items-center justify-center", compact ? "shrink-0" : "min-h-0 flex-1")}>
      {/* The slot is a fixed box: it never shrinks or grows with its neighbours. The pre-roll flies its orb onto it. */}
      <div
        data-orb-slot="stage"
        className="flex items-center justify-center"
        style={{ width: size, height: size, flex: "none", contain: "layout size" }}
      >
        <ActivityOrb {...orb} size={size} />
      </div>
    </div>
  );
}

interface Stat {
  label: string;
  value: string;
  hint: string;
  /** Easy view folds these behind the "Show details" disclosure. */
  secondary?: boolean;
  /** Easy view drops this tile altogether (the model name). */
  hiddenInEasy?: boolean;
  /** Shared-element id: the pre-roll terminal row with the same id flies into this tile. */
  layoutId?: string;
}

/**
 * A read-only stat. A plain div with no tabIndex or button role: the hint appears on pointer hover only,
 * so the keyboard order skips the stats.
 */
function StatTile({
  label,
  value,
  hint,
  layoutId,
}: {
  label: string;
  value: string;
  hint: string;
  layoutId?: string;
}) {
  const unknown = value === DASH;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <motion.div
          data-stat={layoutId}
          data-testid="stat-card"
          className="min-w-0 cursor-default rounded-[12px] bg-raised px-3 py-1 shadow-ring"
        >
          <span className="block truncate text-[12px] leading-4 text-ink-2">{label}</span>
          <span
            className={cn(
              "mt-0.5 block truncate text-[14px] leading-5 font-medium tabular-nums",
              unknown ? "text-ink-3" : "text-foreground",
            )}
          >
            {value}
          </span>
        </motion.div>
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

/**
 * Easy view's one plain status sentence, which leads the stage card on every width (no truncation). A transcribing
 * run with no measured percent reads without one; a frozen run that has not ended reads as reconnecting.
 */
function easySentence(s: StageText, run: RunState | null, phase: DisplayPhase, frozen: boolean, pct: number): string {
  const ended = phase === "finished" || phase === "error" || phase === "canceled";
  if (frozen && !ended) return s.sentence.reconnecting;
  switch (phase) {
    case "transcribing":
      // Progress at 99.5% or more rounds to 100 here: the run is still finishing, so it does not read "100% done".
      if (pct >= 100) return s.sentence.finishing;
      return pct > 0 ? s.sentence.transcribing(pct) : s.sentence.transcribingPlain;
    case "diarizing":
      return s.sentence.diarizing;
    case "loading":
      return s.sentence.loading;
    case "listening":
      return s.sentence.listening;
    case "converting":
      return s.sentence.converting;
    case "waiting":
      return s.sentence.waiting;
    case "finished":
      return run?.duration ? s.sentence.finished(formatElapsed(run.duration)) : s.sentence.finishedPlain;
    case "error":
      return stoppedRun(run) ? s.sentence.stopped : s.sentence.failed;
    case "canceled":
      return s.sentence.canceled;
  }
}

/** The phase's name, with the diarization detail (segmenting, comparing voices) when the CLI reports one. */
function phaseText(s: StageText, run: RunState | null, phase: DisplayPhase): string {
  if (phase === "diarizing" && run?.progress?.detail === "segmentation") return s.phase.segmenting;
  if (phase === "diarizing" && run?.progress?.detail === "embeddings") return s.phase.comparingVoices;
  if (phase === "error" && stoppedRun(run)) return s.phase.stopped;
  return s.phase[phase];
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
