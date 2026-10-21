import { useLayoutEffect, useRef, type JSX } from "react";
import { useI18n } from "@/i18n";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useInkPalette } from "@/hooks/use-ink-palette";
import { OrbRenderer, type OrbMode } from "@/lib/orb-renderer";
import { cn } from "@/lib/utils";

export type { OrbMode } from "@/lib/orb-renderer";

export interface ActivityOrbProps {
  mode: OrbMode;
  envelope: number[];
  pulseKey: number;
  progress: number;
  speakerColors: string[];
  activeColor?: string;
  size?: number;
  className?: string;
  /** The run has ended or the connection is lost: the orb stops and keeps one static frame. */
  frozen?: boolean;
  /** Accessible name. Defaults to the mode's name; the stage card passes the exact state (failed, stopped). */
  label?: string;
}

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/**
 * The activity orb: a sphere of dots that reacts to the transcription (see lib/orb-renderer.ts).
 * The canvas is the only element; it is labelled with the state.
 */
export function ActivityOrb({
  mode,
  envelope,
  pulseKey,
  progress,
  speakerColors,
  activeColor,
  size = 260,
  className,
  frozen = false,
  label,
}: ActivityOrbProps): JSX.Element {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<OrbRenderer | null>(null);
  // Follows the OS setting live. Reduced motion and a frozen run both draw the static frame, not the loop.
  const reduce = useMediaQuery(REDUCED_MOTION_QUERY);
  const still = reduce || frozen;
  const { ink, ink3 } = useInkPalette();

  // One renderer per canvas. It is rebuilt only when the still/animated state changes.
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = new OrbRenderer(canvas, still);
    rendererRef.current = renderer;
    renderer.start();
    return () => {
      renderer.dispose();
      rendererRef.current = null;
    };
  }, [still]);

  useLayoutEffect(() => {
    rendererRef.current?.setInk(ink, ink3);
  }, [ink, ink3, still]);

  useLayoutEffect(() => {
    rendererRef.current?.setInput({ mode, envelope, pulseKey, progress, speakerColors, activeColor, size });
  }, [mode, envelope, pulseKey, progress, speakerColors, activeColor, size, still]);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      data-testid="activity-orb"
      aria-label={label ?? t.stage.orbAria[mode]}
      data-frozen={frozen ? "true" : undefined}
      className={cn("block shrink-0", className)}
      style={{ width: size, height: size }}
    />
  );
}
