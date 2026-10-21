/**
 * Adapted from AICSS StreamingText (MIT). Inline span that shows the first `shown` graphemes of its text, with a
 * soft caret at the reveal edge.
 *
 * Timing is not done here: the reveal queue (src/lib/reveal-engine.ts) advances one shared frame loop and passes
 * the shown count down, so no component keeps its own animation state. Without `shown`, the whole text is drawn.
 *
 * Source: https://www.aicss.dev (free registry). See ./README.md.
 */

import { sliceGraphemes } from "@/lib/reveal-rate";
import { cn } from "@/lib/utils";
import styles from "./streaming-text-inline.module.css";

export interface StreamingTextInlineProps {
  /** The full text. Only its leading `shown` graphemes are drawn. */
  text: string;
  /** How many leading graphemes to draw. Omitted: the whole text. */
  shown?: number;
  /** Draw the soft caret at the reveal edge. Callers pass false under reduced motion and Easy view. */
  caret?: boolean;
  /** The caret rests after the newest text of a live run instead of pulsing while text reveals. */
  idle?: boolean;
  className?: string;
}

export function StreamingTextInline({ text, shown, caret = false, idle = false, className }: StreamingTextInlineProps) {
  const visible = shown === undefined ? text : sliceGraphemes(text, shown);
  return (
    <span className={cn(className)}>
      {visible}
      {caret ? <span aria-hidden="true" className={cn(styles.caret, idle ? styles.idle : styles.pulse)} /> : null}
    </span>
  );
}
