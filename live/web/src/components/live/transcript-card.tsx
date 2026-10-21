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
import { useEasyView } from "@/hooks/use-easy-view";
import { RevealEngine, type RevealView } from "@/lib/reveal-engine";
import { cn } from "@/lib/utils";

/** The view follows new text while the reader is within this many px of the bottom. */
const STICK_PX = 8;
/** After a programmatic scroll, scroll events for this long (ms) cannot change whether the view follows. */
const HOLD_MS = 1000;
/** Content this far past an edge (px) counts as "more above or below" and gets a soft fade. */
const EDGE_PX = 2;
/** A reveal this far behind the data (ms) is flushed: shown at once, not replayed. Only a stalled tab gets here. */
const FLUSH_LAG_MS = 4000;
/** Longest frame step (ms) the reveal integrates in one go. Real elapsed time counts up to this: at 7 fps a frame is
 *  143 ms, and a 100 ms cap silently dropped that time, so the reveal fell behind. Longer stalls are still bounded. */
const MAX_FRAME_MS = 250;
/** Frame step (ms) for the first frame of a loop. */
const FIRST_FRAME_MS = 16;
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
  /** Wall-clock ms. No longer used by the reveal (the reveal reads its own clock); kept so callers need no change. */
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

/** Test instrumentation, exposed as window.__nsliveReveal. Lag runs from the oldest segment not yet fully revealed. */
interface RevealStats {
  maxLagMs: number;
  currentLagMs: number;
  queued: number;
  revealedSegments: number;
}

declare global {
  interface Window {
    __nsliveReveal?: RevealStats;
  }
}

const revealStats: RevealStats = { maxLagMs: 0, currentLagMs: 0, queued: 0, revealedSegments: 0 };
if (typeof window !== "undefined") window.__nsliveReveal = revealStats;

/** Frame-loop state for one card: the pending frame id (null when idle) and the previous frame's timestamp. */
interface RevealLoop {
  frame: number | null;
  last: number | null;
}

function recordStats(engine: RevealEngine, now: number) {
  const lag = engine.lagMs(now);
  revealStats.currentLagMs = lag;
  revealStats.maxLagMs = Math.max(revealStats.maxLagMs, lag);
  revealStats.queued = engine.queued();
  revealStats.revealedSegments = engine.revealedSegments;
}

/**
 * One rAF loop drives the reveal for the card. It advances the queue, publishes the view at most once per frame,
 * and stops once nothing is revealing.
 */
function pumpReveal(engine: RevealEngine, loop: RevealLoop, publish: (view: RevealView) => void) {
  if (loop.frame !== null || !engine.busy()) return;
  const step = (time: number) => {
    const dt = loop.last === null ? FIRST_FRAME_MS : Math.min(MAX_FRAME_MS, time - loop.last);
    loop.last = time;
    if (engine.lagMs(Date.now()) > FLUSH_LAG_MS) engine.flush();
    engine.advance(dt);
    recordStats(engine, Date.now());
    publish(engine.view());
    if (engine.busy()) {
      loop.frame = requestAnimationFrame(step);
    } else {
      loop.frame = null;
      loop.last = null;
    }
  };
  loop.frame = requestAnimationFrame(step);
}


/** One-shot highlight that fades out over 1.2 s. Callers skip it under reduced motion and Easy view (no JS motion). */
function flashSegment(el: HTMLElement) {
  const lit = { backgroundColor: "rgb(128 128 128 / 0.22)", boxShadow: "0 0 0 0.5px rgb(128 128 128 / 0.8)" };
  const clear = { backgroundColor: "rgb(128 128 128 / 0)", boxShadow: "0 0 0 0.5px rgb(128 128 128 / 0)" };
  el.animate([lit, clear], { duration: 1200, easing: "ease-out" });
}

interface SegmentSpanProps {
  segment: Segment;
  overlap: boolean;
  spaceBefore: boolean;
  thinBefore: boolean;
  reveal: Reveal;
  /** Only for the segment revealing now: graphemes of its text shown so far. Passed to that segment alone, so the others do not re-render per frame. */
  shown?: number;
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
  shown,
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
              <StreamingTextInline text={text} shown={shown} caret idle={reveal === "caret"} />
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

/**
 * How a run ended: the title, one detail line, and the raw CLI error behind one disclosure. This is the only place
 * the page explains an ended run. Centred in place of an empty transcript; a left-aligned strip under the header
 * when the run kept some segments, so the reason stays in view.
 */
function EndNotice({ end, strip = false }: { end: EndDescription; strip?: boolean }) {
  return (
    <div
      className={cn(
        "flex w-full flex-col gap-2",
        strip ? "shrink-0 px-6 pb-4 text-left" : "m-auto max-w-[600px] items-center px-2 py-10 text-center",
      )}
    >
      <h3 className="text-[18px] leading-tight font-medium tracking-[-0.01em]">{end.title}</h3>
      {end.detail ? <p className="text-[15px] leading-relaxed text-ink-2">{end.detail}</p> : null}
      {end.rawError ? (
        <ErrorDetails raw={end.rawError} className={cn("w-full max-w-[560px]", strip ? "mt-1" : "mt-3")} />
      ) : null}
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
  // Keyboard focus on the scroller. The edge fade is dropped while it holds, so the inset focus ring is never faded.
  const [keyFocus, setKeyFocus] = useState(false);
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

  // The reveal (see src/lib/reveal-engine.ts). Live segments type out one grapheme at a time, in arrival order; a
  // segment is queued only when it arrives live after the run was opened. Reduced motion, Easy view and a frozen feed
  // show text at once. `view` is the only React state the reveal changes, and it changes at most once per frame.
  const [engine] = useState(() => new RevealEngine());
  const [view, setView] = useState<RevealView>(() => engine.view());
  const loop = useRef<RevealLoop>({ frame: null, last: null });
  const { easy } = useEasyView();
  const queueable = !reduce && !easy && !frozen;
  useLayoutEffect(() => {
    if (engine.runId !== runId) {
      engine.reset(runId, segments);
      revealStats.maxLagMs = 0;
    } else {
      engine.sync(segments);
    }
    if (!queueable) engine.flush();
    recordStats(engine, Date.now());
    setView(engine.view());
    pumpReveal(engine, loop.current, setView);
  }, [engine, runId, segments, queueable]);
  useEffect(
    () => () => {
      if (loop.current.frame !== null) cancelAnimationFrame(loop.current.frame);
      loop.current.frame = null;
    },
    [],
  );
  // The caret rests after the newest text of a live run while nothing reveals; it is off under reduced motion and Easy view.
  const idleCaretIndex = active && view.head === null && queueable ? lastIndex : -1;

  // Turns whose text has not started yet are not drawn at all, so a speaker header never shows without words under it.
  const visibleBlocks = blocks
    .map((block) => ({
      block,
      paragraphs: block.paragraphs.filter((paragraph) => paragraph.items.some((item) => !view.waiting.has(item.seg.index))),
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
        if (!reduce && !easy) flashSegment(target);
      },
    }),
    [reduce, easy],
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
          <h2
            data-testid="run-title"
            title={name ?? undefined}
            className="truncate text-[22px] leading-tight font-medium tracking-[-0.02em]"
          >
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

      {hasBlocks && end && end.kind !== "finished" ? <EndNotice end={end} strip /> : null}

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
        onFocus={(event) => setKeyFocus(event.currentTarget.matches(":focus-visible"))}
        onBlur={() => setKeyFocus(false)}
        className="quiet-scroll flex min-h-0 flex-1 flex-col overflow-y-auto px-6 pb-8 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        style={keyFocus ? undefined : { maskImage: edgeMask(edges), WebkitMaskImage: edgeMask(edges) }}
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
            <div key={runId ?? ""} className="run-fade">
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
                        const reveal: Reveal =
                          seg.index === view.head
                            ? "reveal"
                            : view.waiting.has(seg.index)
                              ? "waiting"
                              : seg.index === idleCaretIndex
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
                            shown={reveal === "reveal" ? view.shown : undefined}
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
            initial={reduce || easy ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce || easy ? undefined : { opacity: 0, y: 6 }}
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
