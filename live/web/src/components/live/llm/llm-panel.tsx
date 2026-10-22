// AI correction trigger. The button and the dialog root stay in the first load; the dialog body (llm-panel-body.tsx) is a
// separate chunk fetched when the button is hovered, focused or pressed. The body stays mounted after the first open, so a
// running correction keeps going when the dialog closes.
import { lazy, Suspense, useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import { useEasyView } from "@/hooks/use-easy-view";
import { useI18n } from "@/i18n";
import type { RunState, Segment } from "@/lib/live-state";
import { cn } from "@/lib/utils";

const loadBody = () => import("@/components/live/llm/llm-panel-body");
const LlmPanelBody = lazy(() => loadBody().then((m) => ({ default: m.LlmPanelBody })));

/** Trigger button and dialog root for AI correction of one finished run. Opened from the transcript card header. */
export function LlmPanel({ run, segments }: { run: RunState; segments: Segment[] }) {
  const { t } = useI18n();
  const { easy } = useEasyView();
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const L = t.llmReview;

  // Starts the chunk download before the click. The module is cached, so repeating the call is harmless.
  const preload = () => void loadBody();

  const onOpenChange = (next: boolean) => {
    if (next) setMounted(true);
    setOpen(next);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="llm-open"
          onPointerEnter={preload}
          onFocus={preload}
          className={cn(
            "shrink-0 rounded-full",
            easy && "min-h-12 px-5 text-[16px]",
          )}
        >
          <Sparkles aria-hidden="true" />
          {L.open}
        </Button>
      </DialogTrigger>
      {mounted ? (
        <Suspense
          fallback={
            <span role="status" data-testid="llm-loading" className="text-[13px] text-ink-2">
              {L.loading}
            </span>
          }
        >
          <LlmPanelBody run={run} segments={segments} open={open} />
        </Suspense>
      ) : null}
    </Dialog>
  );
}
