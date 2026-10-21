import { X } from "lucide-react";
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

export interface FailedRunNoticeOptions {
  /** Already localised, for example "<file> failed". */
  message: string;
  /** Already localised action label. */
  viewLabel: string;
  /** Already localised accessible label of the close button. */
  closeLabel: string;
  /** Picks the failed run explicitly; the notice then closes. */
  onView: () => void;
  /** Called with the toast id when the notice goes away, whoever closed it. */
  onDismiss: (id: string | number) => void;
}

/** Persistent notice for a followed run that failed. It stays until the reader dismisses it or picks the run. */
export function notifyFailedRun({
  message,
  viewLabel,
  closeLabel,
  onView,
  onDismiss,
}: FailedRunNoticeOptions): string | number {
  return toast.custom(
    (id) => (
      <div
        data-testid="failed-run-notice"
        role="status"
        className="flex w-full items-center justify-between gap-3 rounded-lg border border-border bg-popover px-4 py-3 text-[13px] text-popover-foreground shadow-md"
      >
        <span className="min-w-0 truncate">{message}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            onView();
            toast.dismiss(id);
          }}
        >
          {viewLabel}
        </Button>
        <Button type="button" variant="ghost" size="icon-sm" aria-label={closeLabel} onClick={() => toast.dismiss(id)}>
          <X aria-hidden="true" />
        </Button>
      </div>
    ),
    { duration: Infinity, dismissible: true, onDismiss: (dismissed) => onDismiss(dismissed.id) },
  );
}
