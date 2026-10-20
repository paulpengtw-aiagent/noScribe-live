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
import { useI18n } from "@/i18n";
import { StreamingTextInline } from "@/components/aicss/streaming-text-inline";
import { ErrorDetails } from "@/components/live/error-details";
import { Button } from "@/components/ui/button";
import { describeEnd, type EndDescription } from "@/lib/end-state";
import { formatElapsed, isMostlyCjk } from "@/lib/format";
import { isRunActive, type RunState, type Segment } from "@/lib/live-state";
import { useSpeakerName } from "@/lib/speaker-names";
import { speakerColor, speakerKey } from "@/lib/speakers";
import { useZhTw } from "@/lib/zh-tw";
import { buildBlocks, type Paragraph, type SegmentItem } from "@/lib/transcript-blocks";
import { cn } from "@/lib/utils";

/** The view follows new text while the reader is within this many px of the bottom. */
const STICK_PX = 8;
/** After a programmatic scroll, scroll events for this long (ms) cannot change whether the view follows. */
const HOLD_MS = 1000;
/** Content this far past an edge (px) counts as "more above or below" and gets a soft fade. */
const EDGE_PX = 2;
/** A burst of live segments finishes revealing this long after its last arrival (ms). */
const BURST_MS = 1200;
/** Bounds for how long one live segment takes to reveal (ms). */
const MIN_REVEAL_MS = 120;
const MAX_REVEAL_MS = 700;
/** A finished run drains its pending text within this long (ms). */
const FINISH_MS = 400;
/** The reveal is behind when more than this many segments wait, or the oldest has waited this long (ms). */
const FLUSH_SEGMENTS = 2;
const FLUSH_MS = 2000;
/** The screen reader keeps this many announced lines; the oldest are removed. */
const SR_KEEP = 20;
const CLI_COMMAND =
  "python -m noScribe --no-gui --model breeze-asr-25 --speaker-detection auto --timestamps --live-feed live/feeds/ INPUT OUTPUT.html";

const NO_SEGMENTS: Segment[] = [];
const NO_LINES: SpokenLine[] = [];

/** How one segment is drawn: plain text, waiting its turn (nothing shown), revealing now, or shown whole with the caret. */
type Reveal = "plain" | "waiting" | "reveal" | "caret";

/** One completed segment, as the screen reader hears it. */
interface SpokenLine {
  key: number;
  text: string;
}

/** What the screen reader has heard for the current run. `seen` holds the feed seqs already announced or shown at open. */
interface AnnouncerState {
  runId: string | null;
  seen: ReadonlySet<number>;
  lines: SpokenLine[];
}

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
  /** Scrolls a segment into view and flashes it. Stops following the newest text. */
  reveal: (index: number) => void;
}

export interface TranscriptCardProps {
  run: RunState | null;
  speakers: string[];
  /** Wall-clock ms; paces the reveal of queued live segments. */
  now: number;
  hoveredIndex: number | null;
  onHover: (index: number | null) => void;
  /** The segment the reader picked (text or timeline), highlighted with data-active. */
  activeIndex?: number | null;
  /** Called when the reader clicks a segment's text. */
  onSelect?: (index: number) => void;
  /** The page has frozen the feed: no caret and no reveal; pending text is shown at once. */
  frozen?: boolean;
  /** Wall-clock ms of the newest feed update, or null. The page passes it; the card does not read it yet. */
  lastUpdateT?: number | null;
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
  thinBefore: boolean;
  reveal: Reveal;
  /** Only for the segment revealing now: how long its reveal takes (ms). */
  revealMs?: number;
  /** Only for the segment revealing now: called once its text is fully shown. */
  onRevealed?: (index: number) => void;
  /** Display text for a segment (Traditional Chinese conversion when loaded). */
  display: (text: string) => string;
  hovered: boolean;
  active: boolean;
  onHover: (index: number | null) => void;
  onSelect?: (index: number) => void;
}

const SegmentSpan = memo(function SegmentSpan({
  segment,
  overlap,
  spaceBefore,
  thinBefore,
  reveal,
  revealMs,
  onRevealed,
  display,
  hovered,
  active,
  onHover,
  onSelect,
}: SegmentSpanProps) {
  const text = display(segment.text.trim());
  return (
    <>
      {spaceBefore ? " " : null}
      {thinBefore ? (
        <span aria-hidden="true" className="text-ink-3">
          {" "}
        </span>
      ) : null}
      <span
        data-index={segment.index}
        data-segment-index={segment.index}
        data-segment-seq={segment.seq}
        data-active={active ? "true" : undefined}
        lang={isMostlyCjk(text) ? "zh-Hant" : undefined}
        onMouseEnter={() => onHover(segment.index)}
        onMouseLeave={() => onHover(null)}
        onClick={() => onSelect?.(segment.index)}
        className={cn(
          "segment",
          segment.live && "segment-fresh",
          hovered && "bg-raised",
          active && "bg-secondary",
        )}
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
  const { t } = useI18n();
  const speakerName = useSpeakerName();
  return (
    <span className="mr-1.5 inline-block rounded-full px-1.5 align-[2px] text-[11px] leading-4 text-ink-2 shadow-ring">
      {t.transcript.overlap(speakerName(speaker))}
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
  const { t } = useI18n();
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
          {copied ? t.transcript.copied : t.transcript.copy}
        </Button>
      </div>
    </div>
  );
}

export function TranscriptCard({
  run,
  speakers,
  now,
  hoveredIndex,
  onHover,
  activeIndex = null,
  onSelect,
  frozen = false,
  ref,
}: TranscriptCardProps) {
  const { t } = useI18n();
  const reduce = useReducedMotion() ?? false;
  const speakerName = useSpeakerName();
  const toDisplay = useZhTw();
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  // Whether the view follows new text. A ref so observers and handlers read the latest value; the state mirrors it for the UI.
  const followingRef = useRef(true);
  const [following, setFollowing] = useState(true);
  // scrollTop the view last set while following. Content growth never lowers scrollTop, so a lower value means the reader scrolled up.
  const stuckTopRef = useRef(0);
  // Until this time (performance.now() ms), scroll events cannot start or stop following. Covers programmatic scrolls.
  const holdRef = useRef(0);
  const [edges, setEdges] = useState({ top: false, bottom: false });
  // Keeps the previous object when nothing changed, so scroll events do not re-render the card.
  const setEdgesFor = (el: HTMLElement) => {
    const top = el.scrollTop > EDGE_PX;
    const bottom = distanceToEnd(el) > EDGE_PX;
    setEdges((prev) => (prev.top === top && prev.bottom === bottom ? prev : { top, bottom }));
  };
  const setFollow = (value: boolean) => {
    followingRef.current = value;
    setFollowing(value);
  };
  const stopFollowing = () => setFollow(false);
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
  // Reduced motion shows everything at once. Otherwise queued text reveals, including after the run ends.
  const queueable = !reduce;
  const pendingQueue = useMemo(
    () => (queueable ? segments.filter((segment) => isQueued(segment, doneThrough)) : NO_SEGMENTS),
    [queueable, segments, doneThrough],
  );
  const oldest = pendingQueue.length > 0 ? pendingQueue[0] : null;
  // Behind by too much, or frozen: the pending text is shown at once, and the reveal state catches up.
  const behind = oldest !== null && (frozen || pendingQueue.length > FLUSH_SEGMENTS || now - oldest.recvAt > FLUSH_MS);
  // Adjusts the reveal state during render (React's pattern for state that follows props); the next render has nothing pending.
  if (behind) setRevealed({ runId, through: highestLiveIndex(segments) });
  const queueing = queueable && !behind;
  const queue = queueing ? pendingQueue : NO_SEGMENTS;
  const head = queue.length > 0 ? queue[0] : null;
  const headIndex = head ? head.index : -1;
  // A segment whose turn has not come yet: nothing is drawn for it.
  const isWaiting = (segment: Segment) => queueing && segment.index !== headIndex && isQueued(segment, doneThrough);
  // The caret sits on the segment revealing now, or on the last segment while the run is live and idle.
  const caretIndex = frozen ? null : head ? head.index : active ? lastIndex : null;
  // The queue's last segment is due BURST_MS after its arrival. A finished run drains the queue within FINISH_MS.
  const revealMs = head
    ? active
      ? clamp((queue[queue.length - 1].recvAt + BURST_MS - now) / queue.length, MIN_REVEAL_MS, MAX_REVEAL_MS)
      : clamp(FINISH_MS / queue.length, 16, MAX_REVEAL_MS)
    : MAX_REVEAL_MS;
  const markRevealed = (index: number) => setRevealed({ runId, through: index });

  // Turns whose text has not started yet are not drawn at all, so a speaker header never shows without words under it.
  const visibleBlocks = blocks
    .map((block) => ({
      block,
      paragraphs: block.paragraphs.filter((paragraph) => paragraph.items.some((item) => !isWaiting(item.seg))),
    }))
    .filter((entry) => entry.paragraphs.length > 0);

  // What the screen reader announces: one line per segment, appended when the segment's data arrives. The feed text
  // is already complete, so the typewriter is not involved. Segments already on screen when a run is first shown are
  // not news. Each feed seq is announced once, existing lines are never edited, and only the newest SR_KEEP are kept.
  const [announcer, setAnnouncer] = useState<AnnouncerState>({ runId: null, seen: new Set(), lines: NO_LINES });
  if (announcer.runId !== runId) {
    setAnnouncer({ runId, seen: new Set(segments.map((segment) => segment.seq)), lines: NO_LINES });
  } else {
    const fresh = segments.filter((segment) => !announcer.seen.has(segment.seq));
    if (fresh.length > 0) {
      const lines: SpokenLine[] = [];
      for (const segment of fresh) {
        const text = toDisplay(segment.text.trim());
        if (text) lines.push({ key: segment.seq, text: segment.speaker ? t.transcript.srLine(speakerName(segment.speaker), text) : text });
      }
      const seen = new Set(announcer.seen);
      for (const segment of fresh) seen.add(segment.seq);
      setAnnouncer({ runId, seen, lines: [...announcer.lines, ...lines].slice(-SR_KEEP) });
    }
  }

  useLayoutEffect(() => {
    activeRef.current = active;
  });

  // A new run opens at its newest text while it is live, and at the top once it has ended.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const follow = activeRef.current;
    setFollow(follow);
    holdRef.current = 0;
    if (!el) return;
    el.scrollTop = follow ? el.scrollHeight : 0;
    stuckTopRef.current = el.scrollTop;
    setEdgesFor(el);
  }, [runId]);

  // Content that grows (new text, a reveal step, a resize) keeps a following reader at the newest text.
  // Nothing scrolls on render: only a size change of the content or the scroller does.
  useEffect(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (followingRef.current) {
        el.scrollTop = el.scrollHeight;
        stuckTopRef.current = el.scrollTop;
      }
      setEdgesFor(el);
    });
    observer.observe(el);
    if (content) observer.observe(content);
    return () => observer.disconnect();
  }, [hasBlocks]);

  useImperativeHandle(
    ref,
    () => ({
      reveal(index: number) {
        const el = scrollRef.current;
        const target = el?.querySelector<HTMLElement>(`[data-index="${index}"]`);
        if (!el || !target) return;
        // The reader asked for this text: stop following, and do not resume during the scroll to it.
        holdRef.current = performance.now() + HOLD_MS;
        setFollow(false);
        target.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
        flashSegment(target, reduce);
      },
    }),
    [reduce],
  );

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    if (performance.now() >= holdRef.current) {
      if (followingRef.current) {
        // Scrolled up (wheel, keys, touch or the scrollbar): stop following.
        if (el.scrollTop < stuckTopRef.current - 1) setFollow(false);
        else stuckTopRef.current = el.scrollTop;
      } else if (distanceToEnd(el) <= STICK_PX) {
        // Back at the newest text: resume following.
        stuckTopRef.current = el.scrollTop;
        setFollow(true);
      }
    }
    setEdgesFor(el);
  };

  const onWheel = (event: { deltaY: number }) => {
    if (event.deltaY < 0) stopFollowing();
  };

  const onKeyDown = (event: { key: string }) => {
    if (event.key === "PageUp" || event.key === "ArrowUp" || event.key === "Home") stopFollowing();
  };

  const jumpToLive = () => {
    const el = scrollRef.current;
    if (!el) return;
    holdRef.current = performance.now() + HOLD_MS;
    setFollow(true);
    // Lower than the final bottom on purpose: a stale high value would read as a scroll up after the hold.
    stuckTopRef.current = el.scrollTop;
    el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  };

  // The jump button shows whenever the view is not at the newest text, live or ended.
  const showJump = !following && segments.length > 0;
  // How the run ended, or null while it is still running.
  const end = run ? describeEnd(run, t.errors) : null;

  return (
    // Below the sm breakpoint the box has a fixed 70vh height: it stays a scroller that follows new text, and the
    // page keeps scrolling outside it. Streaming text then cannot push the timeline card down.
    <section aria-label={t.transcript.transcriptLabel} className="live-card relative flex min-h-0 flex-1 flex-col overflow-hidden max-sm:h-[70vh] max-sm:flex-none">
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
                <span className="shrink-0 whitespace-nowrap">{t.transcript.model(run.model)}</span>
              </>
            ) : null}
          </div>
        </header>
      ) : null}

      <div
        ref={scrollRef}
        role="region"
        aria-label={t.transcript.transcriptLabel}
        tabIndex={0}
        data-testid="transcript-scroll"
        data-following={following ? "true" : "false"}
        onScroll={onScroll}
        onWheel={onWheel}
        onTouchStart={stopFollowing}
        onTouchMove={stopFollowing}
        onKeyDown={onKeyDown}
        className="quiet-scroll flex min-h-0 flex-1 flex-col overflow-y-auto px-6 pb-8 outline-none focus-visible:ring-2 ring-ring ring-offset-2 ring-offset-card"
        style={{ maskImage: edgeMask(edges), WebkitMaskImage: edgeMask(edges) }}
      >
        {!run ? (
          <div className="m-auto flex w-full max-w-[600px] flex-col items-center gap-5 py-10 text-center">
            <h2 className="text-[28px] leading-tight font-medium tracking-[-0.025em]">{t.transcript.waiting}</h2>
            <p className="text-[15px] leading-relaxed text-ink-2">
              {t.transcript.waitingHint}
            </p>
            <CommandBlock />
          </div>
        ) : hasBlocks ? (
          <div ref={contentRef} className="shrink-0">
            {visibleBlocks.map(({ block, paragraphs }) => (
              <section key={block.id} data-testid="turn" className="mt-[18px] first:mt-0">
                <header
                  data-testid="speaker-header"
                  title={block.speaker || undefined}
                  className="flex min-w-0 items-center gap-2 text-[13px] leading-5"
                >
                  <span
                    aria-hidden="true"
                    className="size-2 shrink-0 rounded-full"
                    style={{ backgroundColor: speakerColor(speakers, block.speaker) }}
                  />
                  {block.speaker ? (
                    <span className="truncate font-medium text-ink-2">{speakerName(block.speaker)}</span>
                  ) : null}
                  {formatElapsed(paragraphs[0].start) !== formatElapsed(block.start) ? (
                    <>
                      {block.speaker ? <span aria-hidden="true" className="text-ink-3">·</span> : null}
                      <span className="font-mono text-[12px] tabular-nums text-ink-3">{formatElapsed(block.start)}</span>
                    </>
                  ) : null}
                </header>
                {paragraphs.map((paragraph: Paragraph) => (
                  <div
                    key={paragraph.id}
                    data-testid="paragraph"
                    data-start={paragraph.start}
                    className="mt-2 flex flex-col gap-0.5 sm:grid sm:grid-cols-[5rem_minmax(0,1fr)] sm:gap-x-3 sm:gap-y-0"
                  >
                    <span data-testid="paragraph-time" className="font-mono text-[12px] leading-5 tabular-nums text-ink-3 sm:pt-[5px]">
                      {formatElapsed(paragraph.start)}
                    </span>
                    <p className="max-w-[70ch] text-pretty text-[17px] leading-[1.7] text-foreground">
                      {paragraph.items.map(({ seg, overlap, spaceBefore, thinBefore }: SegmentItem) => {
                        const isHead = seg.index === headIndex;
                        const reveal: Reveal = isHead
                          ? "reveal"
                          : isWaiting(seg)
                            ? "waiting"
                            : seg.index === caretIndex && !reduce
                              ? "caret"
                              : "plain";
                        return (
                          <SegmentSpan
                            key={seg.index}
                            segment={seg}
                            overlap={overlap}
                            spaceBefore={spaceBefore}
                            thinBefore={thinBefore}
                            reveal={reveal}
                            revealMs={isHead ? revealMs : undefined}
                            onRevealed={isHead ? markRevealed : undefined}
                            display={toDisplay}
                            hovered={hoveredIndex === seg.index}
                            active={activeIndex === seg.index}
                            onHover={onHover}
                            onSelect={onSelect}
                          />
                        );
                      })}
                    </p>
                  </div>
                ))}
              </section>
            ))}
          </div>
        ) : active ? (
          <p className="m-auto px-2 py-10 text-[15px] text-ink-2">
            {t.transcript.segmentsHint}
          </p>
        ) : end ? (
          <EndNotice end={end} />
        ) : null}
      </div>

      <div data-testid="sr-announcer" aria-live="polite" className="sr-only">
        {announcer.lines.map((line) => (
          <p key={line.key}>{line.text}</p>
        ))}
      </div>

      <AnimatePresence>
        {showJump ? (
          <motion.button
            key="jump-to-live"
            type="button"
            data-testid="jump-to-live"
            onClick={jumpToLive}
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 6 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="absolute right-6 bottom-5 inline-flex h-8 items-center gap-1.5 rounded-full bg-secondary px-3.5 text-[13px] font-medium text-secondary-foreground shadow-ring hover:bg-raised"
          >
            <ArrowDown className="size-3.5" aria-hidden="true" />
            {active ? t.transcript.jumpToLive : t.transcript.jumpToEnd}
          </motion.button>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
