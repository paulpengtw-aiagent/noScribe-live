import { useLayoutEffect, useRef, type JSX } from "react";
import { useReducedMotion } from "motion/react";
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
}

const LABEL: Record<OrbMode, string> = {
  idle: "waiting",
  converting: "preparing audio",
  diarizing: "identifying speakers",
  thinking: "loading or listening",
  transcribing: "transcribing",
  finished: "finished",
  error: "stopped",
};

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
}: ActivityOrbProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<OrbRenderer | null>(null);
  const reduce = useReducedMotion() ?? false;
  const { ink, ink3 } = useInkPalette();

  // One renderer per canvas. It is rebuilt only when the reduced-motion preference changes.
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = new OrbRenderer(canvas, reduce);
    rendererRef.current = renderer;
    renderer.start();
    return () => {
      renderer.dispose();
      rendererRef.current = null;
    };
  }, [reduce]);

  useLayoutEffect(() => {
    rendererRef.current?.setInk(ink, ink3);
  }, [ink, ink3, reduce]);

  useLayoutEffect(() => {
    rendererRef.current?.setInput({ mode, envelope, pulseKey, progress, speakerColors, activeColor, size });
  }, [mode, envelope, pulseKey, progress, speakerColors, activeColor, size, reduce]);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={`Activity orb: ${LABEL[mode]}`}
      className={cn("block shrink-0", className)}
      style={{ width: size, height: size }}
    />
  );
}
