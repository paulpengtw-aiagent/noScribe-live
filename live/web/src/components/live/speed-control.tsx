import { Gauge } from "lucide-react";
import { useI18n } from "@/i18n";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Slider } from "@/components/ui/slider";
import { useRevealSpeed } from "@/hooks/use-reveal-speed";
import { CUSTOM_MAX_CPS, CUSTOM_MIN_CPS, type RevealMode } from "@/lib/reveal-rate";
import { cn } from "@/lib/utils";

/** The modes in the segmented control. Custom has no segment: the slider sets it. */
const PRESETS = ["continuous", "reading", "normal", "fast"] as const;

interface SpeedControlProps {
  /** A fixed-rate backlog is long: a subtle "behind" hint shows on the button. Nothing is flushed. */
  behind?: boolean;
  className?: string;
}

/**
 * Compact reveal-speed control: a gauge button showing the current mode, and a popover with the modes and a custom
 * rate slider. The transcript card hides it in Easy view and under reduced motion, where text shows at once.
 */
export function SpeedControl({ behind = false, className }: SpeedControlProps) {
  const { t } = useI18n();
  const { mode, cps, setMode, setCps } = useRevealSpeed();
  const labels: Record<RevealMode, string> = {
    continuous: t.transcript.speedContinuous,
    reading: t.transcript.speedReading,
    normal: t.transcript.speedNormal,
    fast: t.transcript.speedFast,
    custom: t.transcript.speedCustom,
  };
  return (
    <Popover>
      <PopoverTrigger
        data-testid="speed-control"
        title={t.transcript.speedLabel}
        className={cn(
          "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium text-ink-2 shadow-ring hover:bg-raised hover:text-foreground",
          className,
        )}
      >
        <Gauge className="size-4" aria-hidden="true" />
        <span>{labels[mode]}</span>
        {behind ? (
          <span data-testid="reveal-behind" className="text-[12px] font-normal text-ink-3">
            {t.transcript.speedBehind}
          </span>
        ) : null}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-3">
        <div role="radiogroup" aria-label={t.transcript.speedLabel} className="grid grid-cols-4 gap-1 rounded-full bg-muted p-1">
          {PRESETS.map((item) => (
            <button
              key={item}
              type="button"
              role="radio"
              aria-checked={mode === item}
              data-testid={`speed-mode-${item}`}
              onClick={() => setMode(item)}
              className={cn(
                "h-8 min-w-0 truncate rounded-full px-2 text-[13px] font-medium transition-colors",
                mode === item ? "bg-background text-foreground shadow-ring" : "text-ink-2 hover:text-foreground",
              )}
            >
              {labels[item]}
            </button>
          ))}
        </div>
        <label className="mt-3 flex flex-col gap-2">
          <span className="flex items-center justify-between text-[13px] text-ink-2">
            <span>{t.transcript.speedCharsPerSecond}</span>
            <span data-testid="speed-cps" className="font-mono tabular-nums text-foreground">
              {cps}
            </span>
          </span>
          <Slider
            data-testid="speed-slider"
            min={CUSTOM_MIN_CPS}
            max={CUSTOM_MAX_CPS}
            step={1}
            value={[cps]}
            onValueChange={(values) => setCps(values[0])}
          />
        </label>
      </PopoverContent>
    </Popover>
  );
}
