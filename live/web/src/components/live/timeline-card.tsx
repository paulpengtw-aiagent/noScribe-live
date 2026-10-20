import { WaveformTimeline, type WaveformTimelineProps } from "@/components/live/waveform-timeline";
import type { PeaksError } from "@/hooks/use-run-peaks";
import { DASH } from "@/lib/format";
import { PHASE_LABEL, type DisplayPhase } from "@/lib/live-state";
import { useSpeakerName } from "@/lib/speaker-names";
import { cn } from "@/lib/utils";

/** Shown under the timeline when its waveform cannot be drawn. */
const PEAKS_NOTE: Record<NonNullable<PeaksError>, string> = {
  undecodable: "無法顯示波形：音訊檔無法讀取",
  missing: "無法顯示波形：找不到音訊檔",
  failed: "波形暫時無法載入",
};

export interface TimelineCardProps {
  speakers: string[];
  /** Names the header's status: the progress is shown only once transcription has begun. */
  phase: DisplayPhase;
  /** "01:12 of 03:23", or a dash before a run. */
  transcribed: string;
  waveform: WaveformTimelineProps;
  /** Why the waveform is missing, from `useRunPeaks`. The speaker bars still show. */
  peaksError?: PeaksError;
  className?: string;
}

/** Phases in which "transcribed of length" is a meaningful progress reading. */
function isTranscribing(phase: DisplayPhase): boolean {
  return phase === "transcribing" || phase === "finished" || phase === "error" || phase === "canceled";
}

export function TimelineCard({ speakers, phase, transcribed, waveform, peaksError = null, className }: TimelineCardProps) {
  const speakerName = useSpeakerName();
  const note = peaksError ? PEAKS_NOTE[peaksError] : undefined;
  // loaded | loading | missing | undecodable | failed: the waveform state, on the card root.
  const peaksState = waveform.peaks ? "loaded" : (peaksError ?? "loading");
  // Until the audio length is known and transcription has begun, the header names the phase
  // (e.g. "Identifying speakers") instead of reading "Transcribed 00:00 of —".
  const timed = waveform.duration !== null && waveform.duration > 0 && isTranscribing(phase);
  const status = timed ? `Transcribed ${transcribed}` : phase === "waiting" ? DASH : PHASE_LABEL[phase];
  return (
    <section
      aria-label="Timeline"
      data-peaks={peaksState}
      className={cn("live-card flex min-h-[200px] flex-1 flex-col gap-4 p-5", className)}
    >
      <header className="flex min-h-[24px] min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-1">
          <h2 className="shrink-0 text-[14px] font-medium tracking-[-0.01em]">Timeline</h2>
          <ul aria-label="Speakers" className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
            {speakers.map((speaker) => (
              <li key={speaker} className="flex min-w-0 items-center gap-1.5 text-[13px] break-words text-ink-2">
                <span
                  aria-hidden="true"
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: waveform.speakerColor(speaker) }}
                />
                {speakerName(speaker)}
              </li>
            ))}
          </ul>
        </div>
        <span className={cn("max-w-full shrink-0 text-[12px] tabular-nums text-ink-3", timed && "font-mono")}>{status}</span>
      </header>
      <div className="relative min-h-0 flex-1">
        <WaveformTimeline {...waveform} />
      </div>
      {/* Always reserves its line, so a note appearing does not move the card. */}
      <p data-testid={note ? "waveform-note" : undefined} className="min-h-[20px] shrink-0 text-[12px] leading-5 text-ink-3">
        {note}
      </p>
    </section>
  );
}
