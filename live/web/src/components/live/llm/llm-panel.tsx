import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Settings2, Sparkles } from "lucide-react";
import { useI18n } from "@/i18n";
import type { LlmReviewMessages } from "@/i18n/catalog/llmReview";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ContextSection } from "@/components/live/llm/context-section";
import { LlmSettingsDialog } from "@/components/live/llm/settings-dialog";
import { ReviewList } from "@/components/live/llm/review-list";
import { useEasyView } from "@/hooks/use-easy-view";
import { useContextDocs } from "@/lib/llm/context-store";
import { runCorrections } from "@/lib/llm/correct";
import { useLlmSettings } from "@/lib/llm/settings";
import { correctionsVersion, loadCorrections, saveCorrections, subscribeCorrections } from "@/lib/llm/store";
import type { LlmError, RunCorrections, SegmentRef } from "@/lib/llm/types";
import type { RunState, Segment } from "@/lib/live-state";
import { useZhConverter } from "@/lib/zh-tw";
import { cn } from "@/lib/utils";

/** Trigger button and dialog for AI correction of one finished run. Opened from the transcript card header. */
export function LlmPanel({ run, segments }: { run: RunState; segments: Segment[] }) {
  const { t } = useI18n();
  const { easy } = useEasyView();
  const reduce = useReducedMotion() ?? false;
  const { settings, apiKey } = useLlmSettings();
  const { docs, freeText } = useContextDocs();
  const { display } = useZhConverter();
  const version = useSyncExternalStore(subscribeCorrections, correctionsVersion);
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [corrections, setCorrections] = useState<RunCorrections | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const configured = settings.baseUrl.trim() !== "" && settings.model.trim() !== "";
  const L = t.llmReview;

  // Cancel a run only when the panel itself goes away. Closing the dialog keeps the run going.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Reload the stored corrections when the dialog opens and whenever they change elsewhere.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    loadCorrections(run.runId)
      .then((rc) => {
        if (alive) setCorrections(rc);
      })
      .catch(() => {
        if (alive) setCorrections(null);
      });
    return () => {
      alive = false;
    };
  }, [open, run.runId, version]);

  const start = async () => {
    if (!configured || running) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setRunning(true);
    setError(null);
    setSaveFailed(false);
    setProgress({ done: 0, total: 0 });
    try {
      const refs: SegmentRef[] = segments.map((s) => ({
        index: s.index,
        seq: s.seq,
        speaker: s.speaker ? s.speaker : null,
        start: s.start,
        end: s.end,
        text: display(s.text.trim()),
      }));
      const items = await runCorrections({
        runId: run.runId,
        segments: refs,
        settings,
        apiKey,
        docs,
        freeText,
        signal: ctrl.signal,
        onProgress: (done, total) => setProgress({ done, total }),
      });
      // Earlier decisions stay. New suggestions only fill segments that have no item yet.
      const existing = await loadCorrections(run.runId).catch(() => null);
      const decided = new Set((existing?.items ?? []).map((c) => c.segmentIndex));
      const merged = [
        ...(existing?.items ?? []),
        ...items.filter((c) => !decided.has(c.segmentIndex)),
      ].sort((a, b) => a.segmentIndex - b.segmentIndex);
      const next: RunCorrections = {
        runId: run.runId,
        model: settings.model,
        createdAt: Date.now() / 1000,
        items: merged,
      };
      setCorrections(next);
      saveCorrections(next).catch(() => setSaveFailed(true));
    } catch (err) {
      if (isLlmError(err) && err.kind === "aborted") {
        // Cancelled by the reader: nothing to report.
      } else {
        setError(isLlmError(err) ? err : { kind: "network", message: String(err) });
      }
    } finally {
      abortRef.current = null;
      setRunning(false);
      setProgress(null);
    }
  };

  const onReviewChange = (next: RunCorrections) => {
    setCorrections(next);
    saveCorrections(next).catch(() => setSaveFailed(true));
  };

  const pct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="llm-open"
            className={cn(
              "shrink-0 rounded-full",
              easy && "min-h-12 px-5 text-[16px]",
            )}
          >
            <Sparkles aria-hidden="true" />
            {L.open}
          </Button>
        </DialogTrigger>
        <DialogContent
          data-testid="llm-panel"
          className="max-h-[88vh] gap-4 overflow-y-auto sm:max-w-2xl"
        >
          <DialogHeader>
            <DialogTitle>{L.title}</DialogTitle>
            <DialogDescription>{L.privacy}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="llm-settings-open"
              onClick={() => setSettingsOpen(true)}
            >
              <Settings2 aria-hidden="true" />
              {L.settings}
            </Button>
          </div>

          <ContextSection />

          <div className="flex flex-col gap-3">
            {running ? (
              <>
                <p
                  data-testid="llm-progress"
                  aria-live="polite"
                  className="text-[13px] leading-5 text-ink-2"
                >
                  {progress && progress.total > 0 ? L.progress(progress.done, progress.total) : L.preparing}
                </p>
                <div className="flex items-center gap-3">
                  <div className="relative min-w-0 flex-1 overflow-hidden rounded-full">
                    <Progress value={pct} className="h-2" />
                    {reduce || easy ? null : (
                      <motion.span
                        aria-hidden="true"
                        className="pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-linear-to-r from-transparent via-white/35 to-transparent"
                        animate={{ x: ["-100%", "320%"] }}
                        transition={{ duration: 2.4, ease: "easeInOut", repeat: Infinity }}
                      />
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="llm-cancel"
                    onClick={() => abortRef.current?.abort()}
                  >
                    {L.cancel}
                  </Button>
                </div>
              </>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  data-testid="llm-run"
                  disabled={!configured}
                  onClick={start}
                  className={cn(easy && "min-h-12 px-5 text-[16px]")}
                >
                  {L.run}
                </Button>
                {configured ? null : <span className="text-[13px] text-ink-2">{L.needConfig}</span>}
              </div>
            )}
            {error && error.kind !== "aborted" ? (
              <div
                role="alert"
                data-testid="llm-error"
                data-kind={error.kind}
                className="rounded-[12px] border border-destructive/50 bg-destructive/10 px-3 py-2 text-[14px] leading-6 text-foreground"
              >
                {errorText(error, L)}
              </div>
            ) : null}
            {saveFailed ? <p className="text-[13px] text-destructive">{L.saveFailed}</p> : null}
          </div>

          {corrections ? (
            <ReviewList
              runId={run.runId}
              segments={segments}
              corrections={corrections}
              onChange={onReviewChange}
            />
          ) : null}
        </DialogContent>
      </Dialog>
      <LlmSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  );
}

function isLlmError(err: unknown): err is LlmError {
  return typeof err === "object" && err !== null && typeof (err as { kind?: unknown }).kind === "string";
}

function errorText(err: LlmError, L: LlmReviewMessages): string {
  switch (err.kind) {
    case "cors":
      return L.errorCors;
    case "network":
      return L.errorNetwork;
    case "http":
      return L.errorHttp(err.status ?? 0);
    case "auth":
      return L.errorAuth;
    case "json":
      return L.errorJson;
    case "aborted":
      return L.errorAborted;
    default:
      return L.errorGeneric;
  }
}
