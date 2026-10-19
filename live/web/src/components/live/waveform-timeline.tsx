// PLACEHOLDER — replaced in the next pass
import type { JSX } from "react";
import { cn } from "@/lib/utils";

export interface TimelineSegment {
  index: number;
  start: number;
  end: number;
  speaker: string;
  text: string;
}

export interface WaveformTimelineProps {
  duration: number | null;
  startOffset: number;
  peaks: number[] | null;
  segments: TimelineSegment[];
  frontier: number | null;
  speakerColor: (speaker: string) => string;
  hoveredIndex: number | null;
  onHover: (index: number | null) => void;
  onSelect: (index: number) => void;
  live: boolean;
  className?: string;
}

export function WaveformTimeline({
  duration,
  startOffset,
  segments,
  frontier,
  speakerColor,
  hoveredIndex,
  onHover,
  onSelect,
  className,
}: WaveformTimelineProps): JSX.Element {
  const span = duration && duration > 0 ? duration : Math.max(1, frontier ?? 1);
  const pct = (seconds: number) => Math.min(100, Math.max(0, ((seconds - startOffset) / span) * 100));
  return (
    <div className={cn("relative h-full w-full", className)}>
      <div className="absolute inset-x-0 top-1/2 h-px bg-hairline" />
      {segments.map((seg) => {
        const left = pct(seg.start);
        const width = Math.max(0.3, pct(seg.end) - left);
        return (
          <button
            key={seg.index}
            type="button"
            aria-label={`Segment ${seg.index + 1}`}
            onMouseEnter={() => onHover(seg.index)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(seg.index)}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(seg.index)}
            className="absolute top-1/2 h-10 -translate-y-1/2 rounded-sm"
            style={{
              left: `${left}%`,
              width: `${width}%`,
              backgroundColor: speakerColor(seg.speaker),
              opacity: hoveredIndex === seg.index ? 1 : 0.55,
            }}
          />
        );
      })}
      {frontier !== null ? (
        <div className="absolute inset-y-0 w-px bg-foreground" style={{ left: `${pct(frontier)}%` }} />
      ) : null}
    </div>
  );
}
