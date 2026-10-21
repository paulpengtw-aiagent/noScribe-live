import { useEffect, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { useI18n } from "@/i18n";
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
  /** False in Easy view: the speaker blocks stay, the loudness bars (canvas) are not drawn. */
  showWaveform?: boolean;
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
// Narrowest a block is drawn, in percent of the track, so a very short segment stays visible.
const MIN_BLOCK_PERCENT = 0.3;

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
  showWaveform = true,
}: WaveformTimelineProps): JSX.Element {
  const { t } = useI18n();
  const speakerName = useSpeakerName();
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [ink, setInk] = useState(FALLBACK_INK);
  // Roving tabindex: one block is in the tab order (the last one focused, else the active one, else the newest).
  const [focusStop, setFocusStop] = useState<number | null>(null);
  const newestIndex = segments.length > 0 ? segments[segments.length - 1].index : null;
  // A remembered index whose block has gone (the segments were replaced) must not leave the timeline with no tab stop.
  const isBlock = (index: number | null | undefined) => index != null && segments.some((seg) => seg.index === index);
  const stopIndex = [focusStop, activeIndex].find(isBlock) ?? newestIndex;

  // Arrow keys move focus between blocks, Home and End go to the first and last, so the timeline is one tab stop.
  // Enter and Space select through the native button click.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const { key } = event;
    if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "Home" && key !== "End") return;
    const root = rootRef.current;
    if (!root) return;
    const blocks = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-timeline-index]"));
    const at = blocks.indexOf(event.target as HTMLButtonElement);
    if (at < 0) return;
    event.preventDefault();
    let next = at;
    if (key === "Home") next = 0;
    else if (key === "End") next = blocks.length - 1;
    else next = Math.min(blocks.length - 1, Math.max(0, at + (key === "ArrowRight" ? 1 : -1)));
    blocks[next]?.focus();
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
  // A block's left edge and width, in percent of the track. Drawing and hit testing both use this.
  // Clamped to the track: left + width never passes 100%, so a block cannot reach past the card's content box.
  const blockBox = (seg: TimelineSegment) => {
    const left = Math.min(100 - MIN_BLOCK_PERCENT, pct(seg.start));
    const width = Math.min(100 - left, Math.max(MIN_BLOCK_PERCENT, pct(seg.end) - left));
    return { left, width };
  };

  // The block whose centre is nearest the pointer's x. The one hit layer covers the gaps between blocks too,
  // so a tap anywhere on the track selects the block it is closest to.
  const nearestIndex = (clientX: number, box: DOMRect): number | null => {
    if (box.width <= 0) return null;
    const x = ((clientX - box.left) / box.width) * 100;
    let best: number | null = null;
    let bestDistance = Infinity;
    for (const seg of segments) {
      const { left, width } = blockBox(seg);
      const distance = Math.abs(left + width / 2 - x);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = seg.index;
      }
    }
    return best;
  };

  return (
    <div ref={rootRef} onKeyDown={onKeyDown} className={cn("relative h-full w-full", className)}>
      {showWaveform ? (
        <canvas ref={canvasRef} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />
      ) : null}
      <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-hairline" />
      {/* Keyboard stops only: pointer input goes to the hit layer below, which picks the nearest block. */}
      {segments.map((seg) => {
        const { left, width } = blockBox(seg);
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
            aria-label={name ? t.timeline.segment(seg.index + 1, name) : t.timeline.segmentPlain(seg.index + 1)}
            onFocus={() => {
              onHover(seg.index);
              setFocusStop(seg.index);
            }}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(seg.index)}
            className="timeline-block pointer-events-none absolute top-1/2 h-10 -translate-y-1/2 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card"
            style={{
              left: `${left}%`,
              width: `${width}%`,
              backgroundColor: speakerColor(seg.speaker),
            }}
          />
        );
      })}
      {frontier !== null ? (
        <div className="pointer-events-none absolute inset-y-0 w-px bg-foreground" style={{ left: `${pct(frontier)}%` }} />
      ) : null}
      {/* One hit layer over the whole track, at least 24 px tall. Pointer hover and click select the nearest block. */}
      <div
        data-testid="timeline-hit"
        aria-hidden="true"
        className="absolute inset-0 min-h-[24px] cursor-pointer"
        onPointerMove={(event) => {
          const index = nearestIndex(event.clientX, event.currentTarget.getBoundingClientRect());
          if (index !== hoveredIndex) onHover(index);
        }}
        onPointerLeave={() => onHover(null)}
        onClick={(event) => {
          const index = nearestIndex(event.clientX, event.currentTarget.getBoundingClientRect());
          if (index !== null) onSelect(index);
        }}
      />
    </div>
  );
}
