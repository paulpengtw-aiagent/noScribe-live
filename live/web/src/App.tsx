import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { toast } from "sonner";
import { AuroraBackground } from "@/components/live/aurora-background";
import { StageCard } from "@/components/live/stage-card";
import { TimelineCard } from "@/components/live/timeline-card";
import type { TimelineSegment, WaveformTimelineProps } from "@/components/live/waveform-timeline";
import type { OrbMode } from "@/components/live/activity-orb";
import { TopBar } from "@/components/live/top-bar";
import { TranscriptCard, type TranscriptHandle } from "@/components/live/transcript-card";
import { ConnBanner } from "@/components/live/conn-banner";
import { notifyFailedRun, notifyNewRun } from "@/components/live/new-run-notice";
import { LoadingSkeleton, RunLoading, TranscriptSkeleton } from "@/components/live/loading-skeleton";
import { RunMissing } from "@/components/live/run-missing";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useLiveFeed, type Connection } from "@/hooks/use-live-feed";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useNow } from "@/hooks/use-now";
import { useRunPeaks } from "@/hooks/use-run-peaks";
import { useTheme } from "@/hooks/use-theme";
import { useI18n, type Messages } from "@/i18n";
import { DASH } from "@/lib/format";
import type { RunStatus } from "@/lib/live-types";
import {
  displayPhase,
  elapsedSeconds,
  frontier,
  isRunActive,
  latencyStats,
  progressFraction,
  realTimeFactor,
  type DisplayPhase,
  type RunState,
} from "@/lib/live-state";
import { clockText, envelopeFor, FOLLOW_NEWEST, otherLiveRun, runName } from "@/lib/live-view";
import { SpeakerOrderContext } from "@/lib/speaker-names";
import { speakerColor } from "@/lib/speakers";

/** Below this width the page stacks into one column. */
const WIDE_QUERY = "(min-width: 1100px)";
const NO_SPEAKERS: string[] = [];
const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1];

function orbModeFor(phase: DisplayPhase): OrbMode {
  switch (phase) {
    case "waiting":
      return "idle";
    case "converting":
      return "converting";
    case "diarizing":
      return "diarizing";
    case "loading":
    case "listening":
      return "thinking";
    case "transcribing":
      return "transcribing";
    case "finished":
      return "finished";
    case "error":
    case "canceled":
      return "error";
  }
}

/** One orchestrated entrance on load: the three cards fade and rise 8 px, staggered by 60 ms. */
function entrance(index: number, reduce: boolean) {
  if (reduce) return {};
  return {
    initial: { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.4, delay: index * 0.06, ease: EASE_OUT },
  };
}

/** `?run=<id>` from the URL, or the follow-newest default. */
function readRunParam(): string {
  return new URLSearchParams(window.location.search).get("run") || FOLLOW_NEWEST;
}

/**
 * Tab title: the shown run's file and how it stands, so a background tab says what is happening.
 * A lost connection is never reported as the run having stopped.
 */
function documentTitle(run: RunState | null, connection: Connection, hasHello: boolean, t: Messages["app"]): string {
  const name = run ? run.audioName || run.runId : null;
  if (hasHello && connection !== "live") return t.titleReconnecting(name ?? t.titleIdle);
  if (name === null) return t.titleIdle;
  if (run?.endStatus === "finished") return t.titleFinished(name);
  if (run?.endStatus === "error") return t.titleFailed(name);
  if (run?.endStatus === "canceled") return t.titleCanceled(name);
  if (run?.stale) return t.titleStopped(name);
  if (connection === "live") return t.titleLive(name);
  return t.titleIdle;
}

/** A failed-run notice still on screen, by run id. `id` is the toast id. */
interface OpenFailedNotice {
  name: string;
  id: string | number;
}

/**
 * Raises the persistent failed-run notice for one run. `open` tracks the notices still on screen so a locale
 * switch can re-raise them in the new language; a notice closed by the reader leaves the map.
 */
function raiseFailedRun(
  open: Map<string, OpenFailedNotice>,
  runId: string,
  name: string,
  app: Messages["app"],
  onView: (runId: string) => void,
) {
  const id = notifyFailedRun({
    message: app.failedRunToast(name),
    viewLabel: app.failedRunView,
    closeLabel: app.toastClose,
    onView: () => onView(runId),
    onDismiss: (dismissed) => {
      if (open.get(runId)?.id === dismissed) open.delete(runId);
    },
  });
  open.set(runId, { name, id });
}

export default function App() {
  const [runParam, setRunParam] = useState(readRunParam);
  const { state, connection, retry, lastUpdateT } = useLiveFeed(runParam);
  const { t, locale } = useI18n();
  const { theme, toggle: toggleTheme } = useTheme();
  const wide = useMediaQuery(WIDE_QUERY);
  const reduceMotion = useReducedMotion() ?? false;

  // A run that has no start event is a stale or unknown id: show the waiting state.
  const run: RunState | null = state.run && state.run.startedT !== null ? state.run : null;
  const active = isRunActive(run);
  // Frozen while the stream is down: the run panel stops at the last message instead of counting on.
  const frozen = connection !== "live" && state.helloed;
  const now = useNow(active, 250);
  const clockNow = frozen && lastUpdateT !== null ? lastUpdateT * 1000 : now;
  // Offers a switch to another still-running run; never moves the user off a run they picked.
  const otherLive = otherLiveRun(state.runs, run?.runId ?? null, active, runParam === FOLLOW_NEWEST);
  // The waveform is requested as soon as the run's audio is known, live or not.
  const peakRunId = run?.audioFile ? run.runId : null;
  const { peaks, error: peaksError } = useRunPeaks(peakRunId, !active);
  // The header never says "Live" while the stream is down: the run's state is unknown then.
  const badgeRun = active && connection !== "live" ? null : run;
  // Transcript column. Following the newest run: the skeleton while it is awaited, the CLI hint only when the
  // server confirmed zero runs, else the run. An explicit run id: a loading state until its snapshot is in;
  // the "not found" card only after the server's 404 (state.runMissing), never before.
  const runsExist = state.runs.length > 0;
  const picked = runParam === FOLLOW_NEWEST ? null : runParam;
  const awaitingRun = picked === null && !run && (connection === "connecting" || runsExist);
  const onboarding = state.helloed && !runsExist && !run && connection !== "connecting";
  const missingRun = picked !== null && !run && state.runMissing === picked && !state.runs.some((r) => r.run_id === picked);

  // The URL names the shown run; following the newest run leaves the URL bare.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (runParam === FOLLOW_NEWEST) url.searchParams.delete("run");
    else url.searchParams.set("run", runParam);
    window.history.replaceState(null, "", url);
  }, [runParam]);

  useEffect(() => {
    document.title = documentTitle(run, connection, state.helloed, t.app);
  }, [run, connection, state.helloed, t]);

  // A run that starts while an explicit run is shown gets a notice. It never switches by itself.
  const seenRuns = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!state.helloed) return;
    if (seenRuns.current === null) {
      seenRuns.current = new Set(state.runs.map((item) => item.run_id));
      return;
    }
    for (const item of state.runs) {
      if (seenRuns.current.has(item.run_id)) continue;
      seenRuns.current.add(item.run_id);
      if (item.status === "running" && runParam !== FOLLOW_NEWEST) {
        notifyNewRun(t.app.newRunStarted(runName(item)), t.app.newRunSwitch, () => setRunParam(item.run_id));
      }
    }
  }, [state.helloed, state.runs, runParam, t]);

  // Failed-run notices are open toasts. A locale switch drops every toast and re-raises the open failed-run
  // notices in the new language, so no toast stays in the old one.
  const openFailed = useRef(new Map<string, OpenFailedNotice>());
  useEffect(() => {
    const open = [...openFailed.current];
    openFailed.current.clear();
    toast.dismiss();
    for (const [runId, notice] of open) raiseFailedRun(openFailed.current, runId, notice.name, t.app, setRunParam);
  }, [t]);

  // A followed run that turns failed gets one persistent notice, once per run id. The first hello only sets the
  // baseline, so failures already listed are not news; a run that changes to error while following is.
  const runStatuses = useRef<Map<string, RunStatus> | null>(null);
  const failedNoticed = useRef(new Set<string>());
  useEffect(() => {
    if (!state.helloed) return;
    const before = runStatuses.current;
    runStatuses.current = new Map(state.runs.map((item): [string, RunStatus] => [item.run_id, item.status]));
    if (before === null || runParam !== FOLLOW_NEWEST) return;
    for (const item of state.runs) {
      if (item.status !== "error" || before.get(item.run_id) === "error" || failedNoticed.current.has(item.run_id)) {
        continue;
      }
      failedNoticed.current.add(item.run_id);
      raiseFailedRun(openFailed.current, item.run_id, runName(item), t.app, setRunParam);
    }
  }, [state.helloed, state.runs, runParam, t]);

  const phase = displayPhase(run);
  const segments = run?.segments;
  const lastSegment = segments && segments.length > 0 ? segments[segments.length - 1] : undefined;
  const speakers = run?.speakers ?? NO_SPEAKERS;
  const duration = run?.duration ?? null;
  const startOffset = run?.startOffset ?? 0;
  const end = frontier(run);

  // Media seconds transcribed so far; the whole file once the run has finished.
  const transcribedSeconds = !run
    ? null
    : run.endStatus === "finished" && duration
      ? duration
      : Math.max(0, (end ?? startOffset) - startOffset);
  const transcribed = clockText(transcribedSeconds, duration, locale);
  const progress = progressFraction(run);

  const latency = useMemo(() => latencyStats(run), [run]);
  const rtf = realTimeFactor(run, clockNow);
  const elapsed = elapsedSeconds(run, clockNow);

  const envelope = useMemo(
    () => envelopeFor(peaks, duration, startOffset, lastSegment),
    [peaks, duration, startOffset, lastSegment],
  );
  const colorOf = useCallback((speaker: string) => speakerColor(speakers, speaker), [speakers]);
  const speakerColors = useMemo(() => speakers.map(colorOf), [speakers, colorOf]);
  const activeColor = lastSegment ? colorOf(lastSegment.speaker) : undefined;
  const pulseKey = run?.liveCount ?? 0;

  const timelineSegments = useMemo<TimelineSegment[]>(
    () =>
      (segments ?? []).map((seg) => ({
        index: seg.index,
        start: seg.start,
        end: seg.end,
        speaker: seg.speaker,
        text: seg.text,
      })),
    [segments],
  );

  // Hover is shared: a segment in the transcript highlights its bar in the timeline, and back.
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const transcriptRef = useRef<TranscriptHandle>(null);
  // The segment the reader picked (text or timeline). Stays highlighted until another pick.
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const selectSegment = useCallback((index: number) => {
    setActiveIndex(index);
    transcriptRef.current?.reveal(index);
  }, []);

  const waveform: WaveformTimelineProps = {
    duration,
    startOffset,
    peaks,
    segments: timelineSegments,
    frontier: end,
    speakerColor: colorOf,
    hoveredIndex,
    onHover: setHoveredIndex,
    activeIndex,
    onSelect: selectSegment,
    live: active && !frozen,
  };

  return (
    <TooltipProvider delayDuration={150}>
      <SpeakerOrderContext.Provider value={speakers}>
        <div className="flex min-h-svh flex-col bg-background text-foreground">
          <AuroraBackground live={active && !frozen} />
          <TopBar
            runs={state.runs}
            runParam={runParam}
            onRunChange={setRunParam}
            run={badgeRun}
            otherLive={otherLive}
            connection={connection}
            theme={theme}
            onToggleTheme={toggleTheme}
          />
          <ConnBanner connection={connection} retry={retry} lastUpdateT={lastUpdateT} />
          <main className="live-page">
            {!state.helloed ? (
              <LoadingSkeleton />
            ) : (
            <div className="live-grid">
              <motion.div className="live-stage" {...entrance(0, reduceMotion)}>
                <StageCard
                  run={run}
                  phase={phase}
                  compact={!wide}
                  orbMode={orbModeFor(phase)}
                  envelope={envelope}
                  pulseKey={pulseKey}
                  speakerColors={speakerColors}
                  activeColor={activeColor}
                  progress={progress}
                  transcribed={transcribed}
                  latency={latency}
                  rtf={rtf}
                  elapsed={elapsed}
                  frozen={frozen}
                  lastUpdateT={lastUpdateT}
                  loading={picked !== null && !run && !missingRun}
                />
              </motion.div>

              <motion.div className="live-transcript" {...entrance(1, reduceMotion)}>
                {awaitingRun ? (
                  <TranscriptSkeleton />
                ) : picked !== null && !run ? (
                  missingRun ? (
                    <RunMissing onFollowNewest={() => setRunParam(FOLLOW_NEWEST)} />
                  ) : (
                    <RunLoading />
                  )
                ) : (
                <div
                  data-testid={onboarding ? "onboarding" : undefined}
                  className={onboarding ? "flex min-h-0 flex-1 flex-col" : "contents"}
                >
                <TranscriptCard
                  ref={transcriptRef}
                  run={run}
                  speakers={speakers}
                  now={clockNow}
                  frozen={frozen}
                  lastUpdateT={lastUpdateT}
                  hoveredIndex={hoveredIndex}
                  onHover={setHoveredIndex}
                  activeIndex={activeIndex}
                  onSelect={setActiveIndex}
                />
                </div>
                )}
              </motion.div>

              <motion.div className="live-timeline" {...entrance(2, reduceMotion)}>
                <TimelineCard
                  speakers={speakers}
                  phase={phase}
                  transcribed={run ? transcribed : DASH}
                  waveform={waveform}
                  peaksError={peaksError}
                  frozen={frozen}
                  lastUpdateT={lastUpdateT}
                />
              </motion.div>
            </div>
            )}
          </main>
        </div>
      </SpeakerOrderContext.Provider>
      <Toaster
        theme={theme}
        position="top-right"
        offset={72}
        mobileOffset={72}
        containerAriaLabel={t.app.toastsAria}
      />
    </TooltipProvider>
  );
}
