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
import { ErrorDetails } from "@/components/live/error-details";
import { Button } from "@/components/ui/button";
import { describeEnd, type EndDescription } from "@/lib/end-state";
import { formatTimecode, isMostlyCjk } from "@/lib/format";
import { isRunActive, type RunState, type Segment } from "@/lib/live-state";
import { useSpeakerName } from "@/lib/speaker-names";
import { speakerColor, speakerKey } from "@/lib/speakers";
import { useZhTw } from "@/lib/zh-tw";
import { buildBlocks } from "@/lib/transcript-blocks";
import { cn } from "@/lib/utils";

/** The view keeps following new text while the reader is this close to the bottom (px). */
const FOLLOW_THRESHOLD_PX = 120;
/** Content this far past an edge (px) counts as "more above or below" and gets a soft fade. */
const EDGE_PX = 2;
/** A burst of live segments finishes revealing this long after its last arrival (ms). */
const BURST_MS = 1200;
/** Bounds for how long one live segment takes to reveal (ms). */
const MIN_REVEAL_MS = 120;
const MAX_REVEAL_MS = 700;
const CLI_COMMAND =
  "python -m noScribe --no-gui --model breeze-asr-25 --speaker-detection auto --timestamps --live-feed live/feeds/ INPUT OUTPUT.html";

const NO_SEGMENTS: Segment[] = [];

/** How one segment is drawn: plain text, waiting its turn (nothing shown), revealing now, or shown whole with the caret. */
type Reveal = "plain" | "waiting" | "reveal" | "caret";

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
  /** Wall-clock ms; paces the reveal of queued live segments. */
  now: number;
  hoveredIndex: number | null;
  onHover: (index: number | null) => void;
  ref?: Ref<TranscriptHandle>;
}

/** A live segment with text that has not finished revealing yet. Snapshot segments never queue. */
function isQueued(segment: Segment, doneThrough: number): boolean {
  return segment.live && segment.index > doneThrough && segment.text.trim() !== "";
}

/** The newest live segment index, or -1. */
function highestLiveIndex(segments: readonly Segment[]): number {
  let highest = -1;
  for (const segment of segments) {
    if (segment.live && segment.index > highest) highest = segment.index;
  }
  return highest;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
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
  /** Only for the segment revealing now: how long its reveal takes (ms). */
  revealMs?: number;
  /** Only for the segment revealing now: called once its text is fully shown. */
  onRevealed?: (index: number) => void;
  /** Display text for a segment (Traditional Chinese conversion when loaded). */
  display: (text: string) => string;
  hovered: boolean;
  onHover: (index: number | null) => void;
}

const SegmentSpan = memo(function SegmentSpan({
  segment,
  overlap,
  spaceBefore,
  reveal,
  revealMs,
  onRevealed,
  display,
  hovered,
  onHover,
}: SegmentSpanProps) {
  const text = display(segment.text.trim());
  return (
    <>
      {spaceBefore ? " " : null}
      <span
        data-index={segment.index}
        data-segment-index={segment.index}
        lang={isMostlyCjk(text) ? "zh-Hant" : undefined}
        onMouseEnter={() => onHover(segment.index)}
        onMouseLeave={() => onHover(null)}
        className={cn("segment", segment.live && "segment-fresh", hovered && "bg-raised")}
      >
        {reveal === "waiting" ? null : (
          <>
            {overlap ? <OverlapTag speaker={speakerKey(segment.speaker)} /> : null}
            {reveal === "plain" ? (
              text
            ) : (
              <StreamingTextInline
                text={text}
                caret
                instant={reveal === "caret"}
                durationMs={revealMs}
                onRevealed={onRevealed ? () => onRevealed(segment.index) : undefined}
              />
            )}
          </>
        )}
      </span>
    </>
  );
});

function OverlapTag({ speaker }: { speaker: string }) {
  const speakerName = useSpeakerName();
  return (
    <span className="mr-1.5 inline-block rounded-full px-1.5 align-[2px] text-[11px] leading-4 text-ink-2 shadow-ring">
      overlap · {speakerName(speaker)}
    </span>
  );
}

/** How a run ended, shown in place of the transcript when it produced no segments. */
function EndNotice({ end }: { end: EndDescription }) {
  return (
    <div className="m-auto flex w-full max-w-[600px] flex-col items-center gap-2 px-2 py-10 text-center">
      <h3 className="text-[18px] leading-tight font-medium tracking-[-0.01em]">{end.title}</h3>
      {end.detail ? <p className="text-[15px] leading-relaxed text-ink-2">{end.detail}</p> : null}
      {end.rawError ? <ErrorDetails raw={end.rawError} className="mt-3 w-full max-w-[560px]" /> : null}
    </div>
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
  const speakerName = useSpeakerName();
  const toDisplay = useZhTw();
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

  // Live segments reveal one after another, in arrival order. `doneThrough` is the newest live segment that has
  // finished revealing in this run. The live text on screen when the card mounts counts as done, so a remount
  // does not replay it.
  const [revealed, setRevealed] = useState(() => ({ runId, through: highestLiveIndex(segments) }));
  const doneThrough = revealed.runId === runId ? revealed.through : -1;
  // Reduced motion and an ended run show everything at once, so only a live run has a queue.
  const queueing = active && !reduce;
  const queue = useMemo(
    () => (queueing ? segments.filter((segment) => isQueued(segment, doneThrough)) : NO_SEGMENTS),
    [queueing, segments, doneThrough],
  );
  const head = queue.length > 0 ? queue[0] : null;
  // The caret sits on the segment revealing now, or on the last segment while the run is live and idle.
  const caretIndex = head ? head.index : active ? lastIndex : null;
  // The queue finishes BURST_MS after its last arrival, each segment taking an equal share of the time left.
  const revealMs = head
    ? clamp((queue[queue.length - 1].recvAt + BURST_MS - now) / queue.length, MIN_REVEAL_MS, MAX_REVEAL_MS)
    : MAX_REVEAL_MS;
  const markRevealed = (index: number) => setRevealed({ runId, through: index });

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
  // How the run ended, or null while it is still running.
  const end = run ? describeEnd(run) : null;

  return (
    <section aria-label="Transcript" className="live-card relative flex min-h-0 flex-1 flex-col overflow-hidden">
      {run ? (
        <header className="shrink-0 px-6 pt-5 pb-4">
          <h2 title={name ?? undefined} className="truncate text-[22px] leading-tight font-medium tracking-[-0.02em]">
            {name}
          </h2>
          <div className="mt-1.5 flex min-w-0 items-center gap-2 text-[13px] leading-5 text-ink-2">
            {run.outputName ? (
              <span title={run.outputName} className="min-w-0 truncate">
                {run.outputName}
              </span>
            ) : null}
            {run.model ? (
              <>
                {run.outputName ? <span aria-hidden="true" className="text-ink-3">·</span> : null}
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
                  {block.speaker ? <span className="font-medium text-ink-2">{speakerName(block.speaker)}</span> : null}
                  {block.speaker && speakerName(block.speaker) !== block.speaker ? (
                    <span className="text-[12px] text-ink-3">{block.speaker}</span>
                  ) : null}
                  <span className="font-mono text-[12px] tabular-nums text-ink-3">{formatTimecode(block.start)}</span>
                </header>
                <p className="mt-2 max-w-[70ch] text-pretty text-[17px] leading-[1.7] text-foreground">
                  {block.items.map(({ seg, overlap, spaceBefore }) => {
                    const isHead = head !== null && seg.index === head.index;
                    const reveal: Reveal = isHead
                      ? "reveal"
                      : queueing && isQueued(seg, doneThrough)
                        ? "waiting"
                        : seg.index === caretIndex
                          ? "caret"
                          : "plain";
                    return (
                      <SegmentSpan
                        key={seg.index}
                        segment={seg}
                        overlap={overlap}
                        spaceBefore={spaceBefore}
                        reveal={reveal}
                        revealMs={isHead ? revealMs : undefined}
                        onRevealed={isHead ? markRevealed : undefined}
                        display={toDisplay}
                        hovered={hoveredIndex === seg.index}
                        onHover={onHover}
                      />
                    );
                  })}
                </p>
              </section>
            ))}
          </div>
        ) : active ? (
          <p className="m-auto px-2 py-10 text-[15px] text-ink-2">
            Segments appear here as soon as the model hears speech.
          </p>
        ) : end ? (
          <EndNotice end={end} />
        ) : null}
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
