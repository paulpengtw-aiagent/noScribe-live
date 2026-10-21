/**
 * Adapted from AICSS StreamingText (MIT) — inline span, configurable speed, reduced-motion aware
 *
 * Differences from the installed StreamingText.tsx (kept unmodified next to this file):
 * - renders a <span> so it can sit inside a running paragraph of transcript text;
 * - the caller sets how long the reveal takes (durationMs) and is told when it is done
 *   (onRevealed), so segments can be revealed one after another;
 * - the caret is shown only when `caret` is set: solid while revealing, blinking
 *   once idle; with reduced motion the text appears at once and nothing blinks.
 *
 * Source: https://www.aicss.dev (free registry). See ./README.md.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import styles from "./streaming-text-inline.module.css";

export interface StreamingTextInlineProps {
  text: string;
  /** Show the caret. Solid while revealing, blinking once idle. */
  caret?: boolean;
  /** Show the whole text at once (catch-up segments, or no reveal wanted). */
  instant?: boolean;
  /** Milliseconds the reveal takes. Read every frame, so a new value speeds up or slows a reveal in progress. */
  durationMs?: number;
  /** Called once when the reveal has shown the whole text. Not called when the text is shown at once. */
  onRevealed?: () => void;
  /** Minimum characters per 16 ms tick; a short duration raises the speed above it. */
  charsPerTick?: number;
  className?: string;
}

const TICK_MS = 16;
/** Default reveal time: a segment is fully revealed this long after it starts, however long it is. */
const FINISH_MS = 700;

export function StreamingTextInline({
  text,
  caret = false,
  instant = false,
  durationMs = FINISH_MS,
  onRevealed,
  charsPerTick = 2,
  className,
}: StreamingTextInlineProps) {
  const reduced = useReducedMotion() ?? false;
  const skip = instant || reduced;
  // The reveal count belongs to one text: a new text starts again from zero without an extra render.
  const [reveal, setReveal] = useState<{ text: string; count: number }>({ text, count: 0 });
  const shown = skip ? text.length : reveal.text === text ? reveal.count : 0;
  // The reveal loop reads the latest duration and callback without restarting when they change.
  const durationRef = useRef(durationMs);
  const onRevealedRef = useRef(onRevealed);
  useLayoutEffect(() => {
    durationRef.current = durationMs;
    onRevealedRef.current = onRevealed;
  });

  useEffect(() => {
    if (skip) return;
    let frame = 0;
    let count = 0;
    let carry = 0;
    let last: number | null = null;

    const step = (now: number) => {
      // Clamp the frame time so a throttled background tab does not dump the whole text at once.
      const dt = last === null ? TICK_MS : Math.min(100, now - last);
      last = now;
      const remaining = text.length - count;
      if (remaining > 0) {
        const ticks = Math.max(1, durationRef.current) / TICK_MS;
        const perTick = Math.max(charsPerTick, Math.ceil(remaining / ticks));
        carry += (dt / TICK_MS) * perTick;
        const advance = Math.floor(carry);
        if (advance > 0) {
          carry -= advance;
          count = Math.min(text.length, count + advance);
          setReveal({ text, count });
        }
      }
      if (count < text.length) frame = requestAnimationFrame(step);
      else onRevealedRef.current?.();
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [text, skip, charsPerTick]);

  const revealing = shown < text.length;
  // Reduced motion: no caret at all, so nothing in the transcript moves or blinks.
  return (
    <span className={cn(className)}>
      {text.slice(0, shown)}
      {caret && !reduced ? (
        <span
          aria-hidden="true"
          className={cn(styles.caret, revealing ? styles.solid : styles.blink)}
        />
      ) : null}
    </span>
  );
}
