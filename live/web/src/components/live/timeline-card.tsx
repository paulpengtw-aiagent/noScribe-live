import { WaveformTimeline, type WaveformTimelineProps } from "@/components/live/waveform-timeline";
import type { PeaksError } from "@/hooks/use-run-peaks";
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
  /** "Transcribed 01:12 of 03:23", or a dash before a run. */
  transcribed: string;
  waveform: WaveformTimelineProps;
  /** Why the waveform is missing, from `useRunPeaks`. The speaker bars still show. */
  peaksError?: PeaksError;
  className?: string;
}

export function TimelineCard({ speakers, transcribed, waveform, peaksError = null, className }: TimelineCardProps) {
  const speakerName = useSpeakerName();
  const note = peaksError ? PEAKS_NOTE[peaksError] : undefined;
  // loaded | loading | missing | undecodable | failed: the waveform state, on the card root.
  const peaksState = waveform.peaks ? "loaded" : (peaksError ?? "loading");
  return (
    <section
      aria-label="Timeline"
      data-peaks={peaksState}
      className={cn("live-card flex min-h-0 flex-1 flex-col gap-4 p-5", className)}
    >
      <header className="flex min-w-0 items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-5">
          <h2 className="shrink-0 text-[14px] font-medium tracking-[-0.01em]">Timeline</h2>
          <ul aria-label="Speakers" className="flex min-w-0 items-center gap-4 overflow-hidden">
            {speakers.map((speaker) => (
              <li key={speaker} className="flex shrink-0 items-center gap-1.5 text-[13px] text-ink-2">
                <span
                  aria-hidden="true"
                  className="size-2 rounded-full"
                  style={{ backgroundColor: waveform.speakerColor(speaker) }}
                />
                {speakerName(speaker)}
              </li>
            ))}
          </ul>
        </div>
        <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-3">{transcribed}</span>
      </header>
      <div className="relative min-h-0 flex-1">
        <WaveformTimeline {...waveform} />
      </div>
      {note ? (
        <p data-testid="waveform-note" className="shrink-0 text-[12px] leading-5 text-ink-3">
          {note}
        </p>
      ) : null}
    </section>
  );
}
