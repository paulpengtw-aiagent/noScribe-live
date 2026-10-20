import { useEffect, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { useSpeakerName } from "@/lib/speaker-names";
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
  /** The segment the reader picked (clicked in the timeline or the text); shown with data-active. */
  activeIndex?: number | null;
  onHover: (index: number | null) => void;
  onSelect: (index: number) => void;
  live: boolean;
  className?: string;
}

// Waveform bars are 2 px wide with a 1 px gap, so one bar every 3 CSS px.
const BAR_WIDTH = 2;
const BAR_PITCH = 3;
// The tallest bar spans this share of the timeline height. Heights follow peak ** SHAPE_EXPONENT.
const MAX_BAR_SHARE = 0.8;
const SHAPE_EXPONENT = 0.8;
// Opacity of the waveform left of the frontier (transcribed) and right of it (not yet transcribed).
const ALPHA_TRANSCRIBED = 0.24;
const ALPHA_PENDING = 0.1;
// Used only if --foreground cannot be read.
const FALLBACK_INK = "#737373";

interface WaveformDraw {
  /** Timeline size in CSS pixels. */
  width: number;
  height: number;
  peaks: readonly number[] | null;
  duration: number | null;
  startOffset: number;
  frontier: number | null;
  ink: string;
}

/**
 * Paints the mirrored loudness bars. The peak array spans [startOffset, startOffset + duration] evenly,
 * so sample k sits at x = k / n × width, the same mapping the speaker bars use for time. Each bar takes
 * the loudest sample that falls in its slot, at least one sample.
 */
function drawWaveform(canvas: HTMLCanvasElement, draw: WaveformDraw): void {
  const { width, height, peaks, duration, startOffset, frontier, ink } = draw;
  // The backing store is in device pixels so the bars stay sharp on high-DPI screens.
  const dpr = window.devicePixelRatio || 1;
  const pxWidth = Math.max(1, Math.round(width * dpr));
  const pxHeight = Math.max(1, Math.round(height * dpr));
  if (canvas.width !== pxWidth) canvas.width = pxWidth;
  if (canvas.height !== pxHeight) canvas.height = pxHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!peaks || peaks.length === 0 || !duration || duration <= 0 || width <= 0 || height <= 0) return;

  // From here on, drawing is in CSS pixels.
  ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0);
  ctx.fillStyle = ink;

  const n = peaks.length;
  const bars = Math.floor((width - BAR_WIDTH + BAR_PITCH) / BAR_PITCH);
  const frontierX = frontier === null ? 0 : Math.min(1, Math.max(0, (frontier - startOffset) / duration)) * width;
  const mid = height / 2;
  for (let i = 0; i < bars; i++) {
    const slotStart = i * BAR_PITCH;
    const first = Math.min(n - 1, Math.floor((slotStart / width) * n));
    const last = Math.min(n, Math.max(first + 1, Math.ceil(((slotStart + BAR_PITCH) / width) * n)));
    let peak = 0;
    for (let k = first; k < last; k++) {
      const value = peaks[k];
      if (Number.isFinite(value) && value > peak) peak = value;
    }
    const barHeight = Math.max(1, Math.pow(Math.min(1, peak), SHAPE_EXPONENT) * MAX_BAR_SHARE * height);
    const centre = slotStart + BAR_WIDTH / 2;
    ctx.globalAlpha = centre < frontierX ? ALPHA_TRANSCRIBED : ALPHA_PENDING;
    ctx.fillRect(slotStart, mid - barHeight / 2, BAR_WIDTH, barHeight);
  }
  ctx.globalAlpha = 1;
}

export function WaveformTimeline({
  duration,
  startOffset,
  peaks,
  segments,
  frontier,
  speakerColor,
  hoveredIndex,
  activeIndex = null,
  onHover,
  onSelect,
  className,
}: WaveformTimelineProps): JSX.Element {
  const speakerName = useSpeakerName();
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [ink, setInk] = useState(FALLBACK_INK);
  // Roving tabindex: one block is in the tab order (the last one focused, else the active one, else the newest).
  const [focusStop, setFocusStop] = useState<number | null>(null);
  const newestIndex = segments.length > 0 ? segments[segments.length - 1].index : null;
  const stopIndex = focusStop ?? activeIndex ?? newestIndex;

  // Left and Right arrows move focus between blocks, so the timeline is one tab stop.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const root = rootRef.current;
    if (!root) return;
    const blocks = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-timeline-index]"));
    const at = blocks.indexOf(event.target as HTMLButtonElement);
    if (at < 0) return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    blocks[Math.min(blocks.length - 1, Math.max(0, at + step))]?.focus();
  };

  // The canvas fills the root without padding, so the root's content box is the drawing area.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (!box) return;
      const { width, height } = box;
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    });
    observer.observe(root);
    return () => observer.disconnect();
  }, []);

  // --foreground is read on the canvas, and again whenever the class or data-theme on <html> changes.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const readInk = () => {
      const value = getComputedStyle(canvas).getPropertyValue("--foreground").trim();
      setInk(value || FALLBACK_INK);
    };
    readInk();
    const observer = new MutationObserver(readInk);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => observer.disconnect();
  }, []);

  const { width: canvasWidth, height: canvasHeight } = size;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawWaveform(canvas, { width: canvasWidth, height: canvasHeight, peaks, duration, startOffset, frontier, ink });
  }, [canvasWidth, canvasHeight, peaks, duration, startOffset, frontier, ink]);

  const span = duration && duration > 0 ? duration : Math.max(1, frontier ?? 1);
  const pct = (seconds: number) => Math.min(100, Math.max(0, ((seconds - startOffset) / span) * 100));
  return (
    <div ref={rootRef} onKeyDown={onKeyDown} className={cn("relative h-full w-full", className)}>
      <canvas ref={canvasRef} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />
      <div className="absolute inset-x-0 top-1/2 h-px bg-hairline" />
      {segments.map((seg) => {
        const left = pct(seg.start);
        const segWidth = Math.max(0.3, pct(seg.end) - left);
        const name = speakerName(seg.speaker);
        const isActive = activeIndex === seg.index;
        return (
          <button
            key={seg.index}
            type="button"
            data-timeline-index={seg.index}
            data-active={isActive ? "true" : undefined}
            data-hovered={hoveredIndex === seg.index ? "true" : undefined}
            aria-current={isActive ? "true" : undefined}
            tabIndex={seg.index === stopIndex ? 0 : -1}
            aria-label={name ? `Segment ${seg.index + 1}, ${name}` : `Segment ${seg.index + 1}`}
            onMouseEnter={() => onHover(seg.index)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => {
              onHover(seg.index);
              setFocusStop(seg.index);
            }}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(seg.index)}
            className="absolute top-1/2 h-10 -translate-y-1/2 rounded-sm"
            style={{
              left: `${left}%`,
              width: `${segWidth}%`,
              backgroundColor: speakerColor(seg.speaker),
              opacity: hoveredIndex === seg.index || isActive ? 1 : 0.55,
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
