import {
  memo,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type Ref,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowDown, Check, Copy } from "lucide-react";
import { StreamingTextInline } from "@/components/aicss/streaming-text-inline";
import { Button } from "@/components/ui/button";
import { formatTimecode, isMostlyCjk } from "@/lib/format";
import { isRunActive, type RunState, type Segment } from "@/lib/live-state";
import { splitPath } from "@/lib/live-view";
import { speakerColor, speakerKey } from "@/lib/speakers";
import { buildBlocks } from "@/lib/transcript-blocks";
import { cn } from "@/lib/utils";

/** The view keeps following new text while the reader is this close to the bottom (px). */
const FOLLOW_THRESHOLD_PX = 120;
/** Content this far past an edge (px) counts as "more above or below" and gets a soft fade. */
const EDGE_PX = 2;
/** A live segment that arrived this recently (ms) is revealed rather than shown at once. */
const RECENT_MS = 1500;
const CLI_COMMAND =
  "python -m noScribe --no-gui --model breeze-asr-25 --speaker-detection auto --timestamps --live-feed live/feeds/ INPUT OUTPUT.html";

const NO_SEGMENTS: Segment[] = [];

/** How one segment is drawn: plain text, revealed, revealed with a caret, or shown whole with a caret. */
type Reveal = "plain" | "reveal" | "caret" | "static-caret";

function distanceToEnd(el: HTMLElement): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight;
}

/** Soft fade at whichever edge still has text beyond it. */
function edgeMask(edges: { top: boolean; bottom: boolean }): string {
  const top = edges.top ? "transparent 0, #000 28px" : "#000 0";
  const bottom = edges.bottom ? "#000 calc(100% - 36px), transparent 100%" : "#000 100%";
  return `linear-gradient(to bottom, ${top}, ${bottom})`;
}

export interface TranscriptHandle {
  /** Scrolls a segment into view and flashes it. */
  reveal: (index: number) => void;
}

export interface TranscriptCardProps {
  run: RunState | null;
  speakers: string[];
  /** Wall-clock ms; drives the reveal window of recent segments. */
  now: number;
  hoveredIndex: number | null;
  onHover: (index: number | null) => void;
  ref?: Ref<TranscriptHandle>;
}

function revealFor(segment: Segment, isLast: boolean, active: boolean, now: number): Reveal {
  if (isLast && active) return segment.live ? "caret" : "static-caret";
  if (segment.live && now - segment.recvAt < RECENT_MS) return "reveal";
  return "plain";
}

/** One-shot highlight that fades out over 1.2 s. Under reduced motion it holds, then drops. */
function flashSegment(el: HTMLElement, reduce: boolean) {
  const lit = { backgroundColor: "rgb(128 128 128 / 0.22)", boxShadow: "0 0 0 0.5px rgb(128 128 128 / 0.8)" };
  const clear = { backgroundColor: "rgb(128 128 128 / 0)", boxShadow: "0 0 0 0.5px rgb(128 128 128 / 0)" };
  const frames: Keyframe[] = reduce ? [lit, { ...lit, offset: 0.85 }, { ...clear, offset: 1 }] : [lit, clear];
  el.animate(frames, { duration: 1200, easing: "ease-out" });
}

interface SegmentSpanProps {
  segment: Segment;
  overlap: boolean;
  spaceBefore: boolean;
  reveal: Reveal;
  hovered: boolean;
  onHover: (index: number | null) => void;
}

const SegmentSpan = memo(function SegmentSpan({
  segment,
  overlap,
  spaceBefore,
  reveal,
  hovered,
  onHover,
}: SegmentSpanProps) {
  const text = segment.text.trim();
  const caret = reveal === "caret" || reveal === "static-caret";
  return (
    <>
      {spaceBefore ? " " : null}
      <span
        data-index={segment.index}
        lang={isMostlyCjk(text) ? "zh-Hant" : undefined}
        onMouseEnter={() => onHover(segment.index)}
        onMouseLeave={() => onHover(null)}
        className={cn("segment", segment.live && "segment-fresh", hovered && "bg-raised")}
      >
        {overlap ? <OverlapTag speaker={speakerKey(segment.speaker)} /> : null}
        {reveal === "plain" ? (
          text
        ) : (
          <StreamingTextInline text={text} caret={caret} instant={reveal === "static-caret"} />
        )}
      </span>
    </>
  );
});

function OverlapTag({ speaker }: { speaker: string }) {
  return (
    <span className="mr-1.5 inline-block rounded-full px-1.5 align-[2px] text-[11px] leading-4 text-ink-2 shadow-ring">
      overlap · {speaker}
    </span>
  );
}

/** The output file, with its directory cut in the middle of the path and the file name kept. */
function PathLine({ path }: { path: string }) {
  const { dir, file } = splitPath(path);
  return (
    <span title={path} className="flex min-w-0 items-baseline">
      <span className="min-w-0 truncate">{dir}</span>
      <span className="max-w-[70%] shrink-0 truncate">{file}</span>
    </span>
  );
}

function CommandBlock() {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(id);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(CLI_COMMAND);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="w-full rounded-[14px] bg-raised p-4 text-left shadow-ring">
      <code className="block font-mono text-[13px] leading-[1.7] break-words text-foreground">{CLI_COMMAND}</code>
      <div className="mt-3 flex justify-end">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={copy}
          className="rounded-full shadow-ring"
        >
          {copied ? <Check /> : <Copy />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}

export function TranscriptCard({ run, speakers, now, hoveredIndex, onHover, ref }: TranscriptCardProps) {
  const reduce = useReducedMotion() ?? false;
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  // Whether the view follows new text. Kept in a ref so observers and handlers read the latest value.
  const pinnedRef = useRef(true);
  const [pinned, setPinned] = useState(true);
  const [edges, setEdges] = useState({ top: false, bottom: false });
  // Keeps the previous object when nothing changed, so scroll events do not re-render the card.
  const setEdgesFor = (el: HTMLElement) => {
    const top = el.scrollTop > EDGE_PX;
    const bottom = distanceToEnd(el) > EDGE_PX;
    setEdges((prev) => (prev.top === top && prev.bottom === bottom ? prev : { top, bottom }));
  };
  const active = isRunActive(run);
  const activeRef = useRef(active);
  const runId = run?.runId ?? null;
  const segments = run?.segments ?? NO_SEGMENTS;
  const blocks = useMemo(() => buildBlocks(segments), [segments]);
  const lastIndex = segments.length > 0 ? segments[segments.length - 1].index : -1;
  const hasBlocks = run !== null && segments.length > 0;
  const name = run ? (run.audioName ?? run.runId) : null;

  useLayoutEffect(() => {
    activeRef.current = active;
  });

  // A new run opens at its newest text while it is live, and at the top once it has ended.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const follow = activeRef.current;
    pinnedRef.current = follow;
    setPinned(follow);
    if (!el) return;
    el.scrollTop = follow ? el.scrollHeight : 0;
    setEdgesFor(el);
  }, [runId]);

  // A reader who is at the newest text stays there while the content grows, including after the run ends.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  });

  // The last segment reveals over time and grows the content; keep the edges and any follow in step.
  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const observer = new ResizeObserver(() => {
      const el = scrollRef.current;
      if (!el) return;
      if (pinnedRef.current) el.scrollTop = el.scrollHeight;
      setEdgesFor(el);
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [hasBlocks]);

  useImperativeHandle(
    ref,
    () => ({
      reveal(index: number) {
        const target = scrollRef.current?.querySelector<HTMLElement>(`[data-index="${index}"]`);
        if (!target) return;
        target.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
        flashSegment(target, reduce);
      },
    }),
    [reduce],
  );

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = distanceToEnd(el) <= FOLLOW_THRESHOLD_PX;
    setPinned(pinnedRef.current);
    setEdgesFor(el);
  };

  const jumpToLive = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = true;
    setPinned(true);
    el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  };

  const showJump = active && !pinned && segments.length > 0;

  return (
    <section aria-label="Transcript" className="live-card relative flex min-h-0 flex-1 flex-col overflow-hidden">
      {run ? (
        <header className="shrink-0 px-6 pt-5 pb-4">
          <h2 title={name ?? undefined} className="truncate text-[22px] leading-tight font-medium tracking-[-0.02em]">
            {name}
          </h2>
          <div className="mt-1.5 flex min-w-0 items-center gap-2 text-[13px] leading-5 text-ink-2">
            {run.outputFile ? <PathLine path={run.outputFile} /> : null}
            {run.model ? (
              <>
                {run.outputFile ? <span aria-hidden="true" className="text-ink-3">·</span> : null}
                <span className="shrink-0 whitespace-nowrap">Model {run.model}</span>
              </>
            ) : null}
          </div>
        </header>
      ) : null}

      <div
        ref={scrollRef}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        className="quiet-scroll flex min-h-0 flex-1 flex-col overflow-y-auto px-6 pb-8"
        style={{ maskImage: edgeMask(edges), WebkitMaskImage: edgeMask(edges) }}
      >
        {!run ? (
          <div className="m-auto flex w-full max-w-[600px] flex-col items-center gap-5 py-10 text-center">
            <h2 className="text-[28px] leading-tight font-medium tracking-[-0.025em]">Waiting for a transcription</h2>
            <p className="text-[15px] leading-relaxed text-ink-2">
              Start a noScribe run with --live-feed and it appears here as it is transcribed.
            </p>
            <CommandBlock />
          </div>
        ) : hasBlocks ? (
          <div ref={contentRef} className="shrink-0">
            {blocks.map((block) => (
              <section key={block.id} className="mt-[18px] first:mt-0">
                <header className="flex items-center gap-2 text-[13px] leading-5">
                  <span
                    aria-hidden="true"
                    className="size-2 rounded-full"
                    style={{ backgroundColor: speakerColor(speakers, block.speaker) }}
                  />
                  {block.speaker ? <span className="font-medium text-ink-2">{block.speaker}</span> : null}
                  <span className="font-mono text-[12px] tabular-nums text-ink-3">{formatTimecode(block.start)}</span>
                </header>
                <p className="mt-2 max-w-[70ch] text-pretty text-[17px] leading-[1.7] text-foreground">
                  {block.items.map(({ seg, overlap, spaceBefore }) => {
                    const isLast = seg.index === lastIndex;
                    return (
                      <SegmentSpan
                        key={seg.index}
                        segment={seg}
                        overlap={overlap}
                        spaceBefore={spaceBefore}
                        reveal={revealFor(seg, isLast, active, now)}
                        hovered={hoveredIndex === seg.index}
                        onHover={onHover}
                      />
                    );
                  })}
                </p>
              </section>
            ))}
          </div>
        ) : (
          <p className="m-auto px-2 py-10 text-[15px] text-ink-2">
            {active ? "Segments appear here as soon as the model hears speech." : "No speech was transcribed in this run."}
          </p>
        )}
      </div>

      <AnimatePresence>
        {showJump ? (
          <motion.button
            key="jump-to-live"
            type="button"
            onClick={jumpToLive}
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 6 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="absolute right-6 bottom-5 inline-flex h-8 items-center gap-1.5 rounded-full bg-secondary px-3.5 text-[13px] font-medium text-secondary-foreground shadow-ring hover:bg-raised"
          >
            <ArrowDown className="size-3.5" aria-hidden="true" />
            Jump to live
          </motion.button>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
