import { useLayoutEffect, useRef, type JSX } from "react";
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
  /** Not read out: the orb is hidden from assistive tech, and the phase text names the state. */
  label?: string;
  /** The pre-roll's big orb: larger, brighter dots so the orb keeps its presence at full size. */
  prominent?: boolean;
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
  prominent = false,
}: ActivityOrbProps): JSX.Element {
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
    rendererRef.current?.setInput({ mode, envelope, pulseKey, progress, speakerColors, activeColor, size, prominent });
  }, [mode, envelope, pulseKey, progress, speakerColors, activeColor, size, prominent, still]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      data-testid="activity-orb"
      data-frozen={frozen ? "true" : undefined}
      className={cn("block shrink-0", className)}
      style={{ width: size, height: size, flex: "none", contain: "layout size" }}
    />
  );
}
