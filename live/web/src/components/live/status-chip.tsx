import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface StatusChipProps {
  label: string;
  value: string;
  /** Explains the value; shown on hover and focus. The tile becomes focusable when set. */
  hint?: string;
  className?: string;
}

export function StatusChip({ label, value, hint, className }: StatusChipProps) {
  const base = cn("min-w-0 rounded-[12px] bg-raised px-3 py-1 shadow-ring", className);
  const body = (
    <>
      <span className="block truncate text-[12px] leading-4 text-ink-2">{label}</span>
      <span className="mt-0.5 block truncate text-[14px] leading-5 font-medium tabular-nums text-foreground">
        {value}
      </span>
    </>
  );
  if (!hint) return <div className={base}>{body}</div>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div tabIndex={0} className={cn(base, "cursor-default")}>
          {body}
        </div>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        className="max-w-[280px] rounded-[10px] bg-popover px-3 py-2 text-[12px] leading-snug text-popover-foreground shadow-ring [&>svg]:bg-popover [&>svg]:fill-popover"
      >
        {hint}
      </TooltipContent>
    </Tooltip>
  );
}
