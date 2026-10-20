import { toast } from "sonner";
import { Button } from "@/components/ui/button";

/**
 * Toast for a run that started while another run is shown. It never switches by itself.
 * `message` and `switchLabel` come already localised from the caller.
 */
export function notifyNewRun(message: string, switchLabel: string, onSwitch: () => void) {
  toast.custom(
    (id) => (
      <div
        data-testid="new-run-notice"
        role="status"
        className="flex w-full items-center justify-between gap-3 rounded-lg border border-border bg-popover px-4 py-3 text-[13px] text-popover-foreground shadow-md"
      >
        <span className="min-w-0 truncate">{message}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            onSwitch();
            toast.dismiss(id);
          }}
        >
          {switchLabel}
        </Button>
      </div>
    ),
    { duration: 15000 },
  );
}
