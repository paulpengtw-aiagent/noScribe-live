import { WaveformTimeline, type WaveformTimelineProps } from "@/components/live/waveform-timeline";
import { useEasyView } from "@/hooks/use-easy-view";
import type { PeaksError } from "@/hooks/use-run-peaks";
import type { Theme } from "@/hooks/use-theme";
import { useI18n } from "@/i18n";
import { DASH } from "@/lib/format";
import { type DisplayPhase } from "@/lib/live-state";
import { useSpeakerName } from "@/lib/speaker-names";
import { speakerDotColor } from "@/lib/speakers";
import { cn } from "@/lib/utils";

export interface TimelineCardProps {
  speakers: string[];
  /** Names the header's status: the progress is shown only once transcription has begun. */
  phase: DisplayPhase;
  /** The transcribed-of-total reading in the page's locale, e.g. "01:12 / 03:23", or a dash before a run. */
  transcribed: string;
  waveform: WaveformTimelineProps;
  /** Why the waveform is missing, from `useRunPeaks`. The speaker bars still show. */
  peaksError?: PeaksError;
  className?: string;
  /** The run has ended or the connection is lost. Nothing on this card animates; the root says so. */
  frozen?: boolean;
  /** Unix seconds of the last update, exposed as data-last-update while frozen. */
  lastUpdateT?: number | null;
  /** The page theme: the legend dots take the theme's variant of the speaker colour. */
  theme: Theme;
}

/** Phases in which "transcribed of length" is a meaningful progress reading. */
function isTranscribing(phase: DisplayPhase): boolean {
  return phase === "transcribing" || phase === "finished" || phase === "error" || phase === "canceled";
}

export function TimelineCard({
  speakers,
  phase,
  transcribed,
  waveform,
  peaksError = null,
  className,
  frozen = false,
  lastUpdateT = null,
  theme,
}: TimelineCardProps) {
  const { t } = useI18n();
  const speakerName = useSpeakerName();
  const { easy } = useEasyView();
  const note = peaksError ? t.timeline.peaks[peaksError] : undefined;
  // loaded | loading | missing | undecodable | failed: the waveform state, on the card root.
  const peaksState = waveform.peaks ? "loaded" : (peaksError ?? "loading");
  // Until the audio length is known and transcription has begun, the header names the phase
  // (e.g. "Identifying speakers") instead of reading "Transcribed 00:00 of —".
  const timed = waveform.duration !== null && waveform.duration > 0 && isTranscribing(phase);
  // A failed or stopped run is named once, in the stage card; here the header stays a dash until the clock applies.
  const status =
    timed ? t.timeline.transcribed(transcribed)
    : phase === "waiting" || phase === "error" || phase === "canceled" ? DASH
    : t.stage.phase[phase];
  return (
    <section
      data-testid="timeline-card"
      aria-label={t.timeline.title}
      data-peaks={peaksState}
      data-frozen={frozen ? "true" : "false"}
      data-last-update={frozen && lastUpdateT !== null ? lastUpdateT : undefined}
      className={cn("live-card flex min-h-[200px] flex-1 flex-col gap-4 p-5", className)}
    >
      <header className="flex min-h-[24px] min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-1">
          <h2 className="shrink-0 text-[14px] font-medium tracking-[-0.01em]">{t.timeline.title}</h2>
          <ul aria-label={t.timeline.speakers} className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
            {speakers.map((speaker) => (
              <li key={speaker} className="flex min-w-0 items-center gap-1.5 text-[13px] break-words text-ink-2">
                <span
                  aria-hidden="true"
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: speakerDotColor(speakers, speaker, theme) }}
                />
                {speakerName(speaker)}
              </li>
            ))}
          </ul>
        </div>
        <span className={cn("max-w-full shrink-0 text-[12px] tabular-nums text-ink-3", timed && "font-mono")}>{status}</span>
      </header>
      <div className="relative min-h-0 flex-1">
        {/* Easy view keeps only the speaker blocks: no loudness bars, and no waveform note. */}
        <WaveformTimeline {...waveform} showWaveform={!easy} />
      </div>
      {/* Always reserves its line, so a note appearing does not move the card. Easy view has no waveform to explain. */}
      {easy ? null : (
        <p data-testid={note ? "waveform-note" : undefined} className="min-h-[20px] shrink-0 text-[12px] leading-5 text-ink-3">
          {note}
        </p>
      )}
    </section>
  );
}
