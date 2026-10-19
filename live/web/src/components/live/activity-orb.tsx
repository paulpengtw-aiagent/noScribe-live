// PLACEHOLDER — replaced in the next pass
import type { JSX } from "react";
import { cn } from "@/lib/utils";

export type OrbMode = "idle" | "converting" | "diarizing" | "thinking" | "transcribing" | "finished" | "error";

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

export function ActivityOrb({ mode, speakerColors, activeColor, size = 260, className }: ActivityOrbProps): JSX.Element {
  const color = activeColor ?? speakerColors[0] ?? "#737373";
  return (
    <div
      aria-hidden="true"
      className={cn("relative shrink-0", className)}
      style={{ width: size, height: size }}
    >
      <div
        className="absolute inset-0 rounded-full transition-opacity duration-700"
        style={{
          background: `radial-gradient(circle at 50% 50%, ${color} 0%, transparent 70%)`,
          opacity: mode === "idle" ? 0.2 : 0.6,
        }}
      />
    </div>
  );
}
