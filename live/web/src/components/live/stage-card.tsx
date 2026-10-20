import { useRef } from "react";
import { Check } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { ActivityOrb, type OrbMode } from "@/components/live/activity-orb";
import { ErrorDetails } from "@/components/live/error-details";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useElementSize } from "@/hooks/use-element-size";
import { useMediaQuery } from "@/hooks/use-media-query";
import { describeEnd } from "@/lib/end-state";
import { DASH, formatElapsed, formatMs, formatPercent, formatRtf } from "@/lib/format";
import { PHASE_LABEL, phaseLabel, type DisplayPhase, type LatencyStats, type RunState } from "@/lib/live-state";
import { deviceText, languageText, latencyHint } from "@/lib/live-view";
import { useSpeakerName } from "@/lib/speaker-names";
import { cn } from "@/lib/utils";

const MODEL_HINT = "The speech model transcribing this audio.";
const DEVICE_HINT = "Where the model runs. CUDA means the graphics card.";
const LANGUAGE_HINT = "The language the model heard in the first speech, with its confidence.";
const ELAPSED_HINT = "Time since the run started. Frozen when it ends.";
const SEGMENTS_HINT = "Segments transcribed so far.";
const RTF_HINT =
  "Real-time factor: processing time ÷ audio time, including model load. Below 1× is faster than real time.";

/** Below the sm breakpoint: a fixed 96 px orb row, and the stats stay in a two-column grid. */
const PHONE_QUERY = "(max-width: 639px)";
const PHONE_ORB_PX = 96;

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
  const speakerName = useSpeakerName();
  const area = useElementSize(orbArea);
  const phone = useMediaQuery(PHONE_QUERY);
  // Phones: a fixed orb. Tablets: 140 px. Desktop: the orb takes the room the stats leave over, between 120 and 260 px.
  const orbSize = phone
    ? PHONE_ORB_PX
    : compact
      ? 140
      : area.height > 0
        ? Math.round(Math.min(260, Math.max(120, area.height - 8)))
        : 260;

  // The bar and the number share one value: the bar is drawn at exactly the percentage shown.
  const percent = formatPercent(progress);

  const stats = [
    { label: "Model", value: run?.model ?? DASH, hint: MODEL_HINT },
    { label: "Device", value: deviceText(run) ?? DASH, hint: DEVICE_HINT },
    { label: "Latency", value: formatMs(latency.last), hint: latencyHint(latency) },
    { label: "RTF", value: formatRtf(rtf), hint: RTF_HINT },
    { label: "Language", value: languageText(run) ?? DASH, hint: LANGUAGE_HINT },
    { label: "Speakers", value: run && run.speakers.length > 0 ? String(run.speakers.length) : DASH, hint: speakerHint(run, speakerName) },
    { label: "Elapsed", value: formatElapsed(elapsed), hint: ELAPSED_HINT },
    { label: "Segments", value: run ? String(run.segments.length) : DASH, hint: SEGMENTS_HINT },
  ];

  const timed = hasTimeline(run, phase);

  return (
    <section aria-label="Run status" className="live-card flex min-h-0 flex-1 flex-col gap-3 p-5 max-sm:min-h-[460px]">
      <div
        ref={orbArea}
        className={cn("flex items-center justify-center", phone ? "h-24 shrink-0" : compact ? "shrink-0" : "min-h-0 flex-1")}
      >
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
            style={{ width: run ? percent : "0%" }}
          />
        </div>
        <div className="mt-2 flex h-5 items-baseline justify-between gap-3 text-[12px] tabular-nums">
          <span className={cn("min-w-0 truncate text-ink-3", timed && "font-mono")}>
            {timed ? transcribed : run ? PHASE_LABEL[phase] : DASH}
          </span>
          <span className="shrink-0 text-ink-2">{run ? percent : DASH}</span>
        </div>
      </div>

      {/* A plain grid, never a horizontal scroller: the stat tiles are read-only and are not tab stops. */}
      <div className="grid grid-cols-2 gap-1.5">
        {stats.map((stat) => (
          <StatTile key={stat.label} label={stat.label} value={stat.value} hint={stat.hint} />
        ))}
      </div>
    </section>
  );
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

function speakerHint(run: RunState | null, speakerName: (label: string) => string): string {
  return run && run.speakers.length > 0
    ? `Speaker labels found in the audio: ${run.speakers.map((label) => speakerName(label)).join(", ")}.`
    : "Speaker labels appear once speaker detection has run.";
}

/** The pill (and whatever sits beside it) that names the current phase. */
function PhaseRow({ run, phase, elapsed }: { run: RunState | null; phase: DisplayPhase; elapsed: number | null }) {
  switch (phase) {
    case "waiting":
      return <Orb variant="C2" pill label="Listening for a run…" />;
    case "loading":
    case "listening":
      return <Orb variant="S1" pill label={phaseLabel(run, phase)} />;
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
      const end = run ? describeEnd(run) : null;
      return (
        <div className="min-w-0 max-w-full">
          <p className="text-[14px] font-medium text-foreground">{phaseLabel(run, phase)}</p>
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
function diarizingLabel(run: RunState | null): string {
  const detail = phaseLabel(run, "diarizing");
  if (detail === PHASE_LABEL.diarizing) return detail;
  return `${PHASE_LABEL.diarizing} · ${detail.charAt(0).toLowerCase()}${detail.slice(1)}`;
}
