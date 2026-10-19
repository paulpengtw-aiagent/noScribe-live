import { useCallback, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { StageCard } from "@/components/live/stage-card";
import { TimelineCard } from "@/components/live/timeline-card";
import type { TimelineSegment, WaveformTimelineProps } from "@/components/live/waveform-timeline";
import type { OrbMode } from "@/components/live/activity-orb";
import { TopBar } from "@/components/live/top-bar";
import { TranscriptCard, type TranscriptHandle } from "@/components/live/transcript-card";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useLiveFeed } from "@/hooks/use-live-feed";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useNow } from "@/hooks/use-now";
import { useRunPeaks } from "@/hooks/use-run-peaks";
import { useTheme } from "@/hooks/use-theme";
import { DASH } from "@/lib/format";
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
import { clockText, envelopeFor, FOLLOW_NEWEST } from "@/lib/live-view";
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

export default function App() {
  const [runParam, setRunParam] = useState(FOLLOW_NEWEST);
  const { state, connection } = useLiveFeed(runParam);
  const { theme, toggle: toggleTheme } = useTheme();
  const wide = useMediaQuery(WIDE_QUERY);
  const reduceMotion = useReducedMotion() ?? false;

  // A run that has no start event is a stale or unknown id: show the waiting state.
  const run: RunState | null = state.run && state.run.startedT !== null ? state.run : null;
  const active = isRunActive(run);
  const now = useNow(active, 250);
  const peaks = useRunPeaks(run?.runId ?? null, !active);

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
  const transcribed = clockText(transcribedSeconds, duration);
  const progress = progressFraction(run);

  const latency = useMemo(() => latencyStats(run), [run]);
  const rtf = realTimeFactor(run, now);
  const elapsed = elapsedSeconds(run, now);

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
  const selectSegment = useCallback((index: number) => transcriptRef.current?.reveal(index), []);

  const waveform: WaveformTimelineProps = {
    duration,
    startOffset,
    peaks,
    segments: timelineSegments,
    frontier: end,
    speakerColor: colorOf,
    hoveredIndex,
    onHover: setHoveredIndex,
    onSelect: selectSegment,
    live: active,
  };

  return (
    <TooltipProvider delayDuration={150}>
      <SpeakerOrderContext.Provider value={speakers}>
        <div className="flex min-h-svh flex-col bg-background text-foreground">
          <TopBar
            runs={state.runs}
            runParam={runParam}
            onRunChange={setRunParam}
            connection={connection}
            theme={theme}
            onToggleTheme={toggleTheme}
          />
          <main className="live-page">
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
                />
              </motion.div>

              <motion.div className="live-transcript" {...entrance(1, reduceMotion)}>
                <TranscriptCard
                  ref={transcriptRef}
                  run={run}
                  speakers={speakers}
                  now={now}
                  hoveredIndex={hoveredIndex}
                  onHover={setHoveredIndex}
                />
              </motion.div>

              <motion.div className="live-timeline" {...entrance(2, reduceMotion)}>
                <TimelineCard
                  speakers={speakers}
                  transcribed={run ? `Transcribed ${transcribed}` : DASH}
                  waveform={waveform}
                />
              </motion.div>
            </div>
          </main>
        </div>
      </SpeakerOrderContext.Provider>
    </TooltipProvider>
  );
}
