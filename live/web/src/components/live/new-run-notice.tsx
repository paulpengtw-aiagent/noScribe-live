import { toast } from "sonner";
import { Button } from "@/components/ui/button";

/** Toast for a run that started while another run is shown. It never switches by itself. */
export function notifyNewRun(fileName: string, onSwitch: () => void) {
  toast.custom(
    (id) => (
      <div
        data-testid="new-run-notice"
        role="status"
        className="flex w-full items-center justify-between gap-3 rounded-lg border border-border bg-popover px-4 py-3 text-[13px] text-popover-foreground shadow-md"
      >
        <span className="min-w-0 truncate">New run started: {fileName}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            onSwitch();
            toast.dismiss(id);
          }}
        >
          切換
        </Button>
      </div>
    ),
    { duration: 15000 },
  );
}
