import { useRef } from "react";
import { Check } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { ThinkingState } from "@/components/aicss/ThinkingState";
import { ActivityOrb, type OrbMode } from "@/components/live/activity-orb";
import { StatusChip } from "@/components/live/status-chip";
import { useElementSize } from "@/hooks/use-element-size";
import { DASH, formatElapsed, formatMs, formatPercent, formatRtf } from "@/lib/format";
import { PHASE_LABEL, phaseLabel, type DisplayPhase, type LatencyStats, type RunState } from "@/lib/live-state";
import { deviceText, languageText, latencyHint } from "@/lib/live-view";
import { cn } from "@/lib/utils";

const MODEL_HINT = "The speech model transcribing this audio.";
const DEVICE_HINT = "Where the model runs. CUDA means the graphics card.";
const LANGUAGE_HINT = "The language the model heard in the first speech, with its confidence.";
const ELAPSED_HINT = "Time since the run started. Frozen when it ends.";
const SEGMENTS_HINT = "Segments transcribed so far.";
const RTF_HINT =
  "Real-time factor: processing time ÷ audio time, including model load. Below 1× is faster than real time.";

export interface StageCardProps {
  run: RunState | null;
  phase: DisplayPhase;
  /** Below 1100 px: a smaller orb and a horizontally scrolling chip row. */
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
}: StageCardProps) {
  const orbArea = useRef<HTMLDivElement>(null);
  const area = useElementSize(orbArea);
  // Desktop: the orb takes the room the chips leave over, between 120 and 260 px.
  const orbSize = compact
    ? 140
    : area.height > 0
      ? Math.round(Math.min(260, Math.max(120, area.height - 8)))
      : 260;

  const chips = [
    { label: "Model", value: run?.model ?? DASH, hint: MODEL_HINT },
    { label: "Device", value: deviceText(run) ?? DASH, hint: DEVICE_HINT },
    { label: "Latency", value: formatMs(latency.last), hint: latencyHint(latency) },
    { label: "RTF", value: formatRtf(rtf), hint: RTF_HINT },
    { label: "Language", value: languageText(run) ?? DASH, hint: LANGUAGE_HINT },
    { label: "Speakers", value: run && run.speakers.length > 0 ? String(run.speakers.length) : DASH, hint: speakerHint(run) },
    { label: "Elapsed", value: formatElapsed(elapsed), hint: ELAPSED_HINT },
    { label: "Segments", value: run ? String(run.segments.length) : DASH, hint: SEGMENTS_HINT },
  ];

  return (
    <section aria-label="Run status" className="live-card flex min-h-0 flex-1 flex-col gap-3 p-5">
      <div ref={orbArea} className={cn("flex items-center justify-center", compact ? "shrink-0" : "min-h-0 flex-1")}>
        <ActivityOrb
          mode={orbMode}
          envelope={envelope}
          pulseKey={pulseKey}
          progress={progress}
          speakerColors={speakerColors}
          activeColor={activeColor}
          size={orbSize}
        />
      </div>

      <div className="flex min-h-[30px] items-center justify-center text-center">
        <PhaseRow run={run} phase={phase} elapsed={elapsed} />
      </div>

      <div>
        <div className="h-[2px] w-full overflow-hidden rounded-full bg-hairline">
          <div
            className="h-full rounded-full bg-foreground transition-[width] duration-500 ease-out"
            style={{ width: `${Math.round(progress * 1000) / 10}%` }}
          />
        </div>
        <div className="mt-2 flex items-baseline justify-between gap-3 text-[12px] tabular-nums">
          <span className="font-mono text-ink-3">{transcribed}</span>
          <span className="text-ink-2">{run ? formatPercent(progress) : DASH}</span>
        </div>
      </div>

      <div
        className={cn(
          compact
            ? "no-scrollbar -mx-5 flex snap-x scroll-px-5 gap-2 overflow-x-auto px-5 pb-1"
            : "grid grid-cols-2 gap-1.5",
        )}
      >
        {chips.map((chip) => (
          <StatusChip
            key={chip.label}
            label={chip.label}
            value={chip.value}
            hint={chip.hint}
            className={compact ? "w-[168px] shrink-0 snap-start" : undefined}
          />
        ))}
      </div>
    </section>
  );
}

function speakerHint(run: RunState | null): string {
  return run && run.speakers.length > 0
    ? `Speaker labels found in the audio: ${run.speakers.join(", ")}.`
    : "Speaker labels appear once speaker detection has run.";
}

/** The pill (and whatever sits beside it) that names the current phase. */
function PhaseRow({ run, phase, elapsed }: { run: RunState | null; phase: DisplayPhase; elapsed: number | null }) {
  switch (phase) {
    case "waiting":
      return <Orb variant="C2" pill label="Listening for a run…" />;
    case "loading":
    case "listening":
      return (
        <div className="flex items-center gap-3">
          <Orb variant="S1" pill label={phaseLabel(run, phase)} />
          <ThinkingState />
        </div>
      );
    case "converting":
      return <Orb variant="S2" pill label={phaseLabel(run, phase)} />;
    case "diarizing":
      return <Orb variant="B2" pill label={diarizingLabel(run)} />;
    case "transcribing":
      return <Orb variant="C3" pill label={phaseLabel(run, phase)} />;
    case "finished":
      return (
        <p className="flex items-center gap-2 text-[14px] text-ink-2">
          <Check className="size-4 text-foreground" aria-hidden="true" />
          {elapsed !== null ? `Finished in ${formatElapsed(elapsed)}` : "Finished"}
        </p>
      );
    case "error":
    case "canceled": {
      const message =
        run?.error ?? (phase === "canceled" ? "The run was canceled." : "The run stopped without an error message.");
      return (
        <div className="min-w-0 max-w-full">
          <p className="text-[14px] font-medium text-foreground">{phaseLabel(run, phase)}</p>
          <p title={message} className="mt-1 line-clamp-2 text-[13px] leading-5 text-ink-2">
            {message}
          </p>
        </div>
      );
    }
  }
}

/** "Identifying speakers · comparing voices" while diarization reports which step it is on. */
function diarizingLabel(run: RunState | null): string {
  const detail = phaseLabel(run, "diarizing");
  if (detail === PHASE_LABEL.diarizing) return detail;
  return `${PHASE_LABEL.diarizing} · ${detail.charAt(0).toLowerCase()}${detail.slice(1)}`;
}
