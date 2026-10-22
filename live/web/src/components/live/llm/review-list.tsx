import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/i18n";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { formatElapsed } from "@/lib/format";
import { diffParts, type DiffPart } from "@/lib/llm/diff";
import { setShowingOriginal, useShowingOriginal } from "@/lib/llm/store";
import type { Correction, RunCorrections } from "@/lib/llm/types";
import type { Segment } from "@/lib/live-state";
import { useSpeakerName } from "@/lib/speaker-names";
import { cn } from "@/lib/utils";

type Status = Correction["status"];

export interface ReviewListProps {
  runId: string;
  segments: Segment[];
  corrections: RunCorrections;
  /** Receives the whole updated set. The caller saves it and keeps its copy current. */
  onChange: (next: RunCorrections) => void;
}

/** The review of one run's corrections: a row per change, accept and reject, bulk actions behind a confirm. */
export function ReviewList({ runId, segments, corrections, onChange }: ReviewListProps) {
  const { t } = useI18n();
  const speakerName = useSpeakerName();
  const showOriginal = useShowingOriginal(runId);
  const [bulk, setBulk] = useState<"accepted" | "rejected" | null>(null);
  const byIndex = useMemo(() => new Map(segments.map((s) => [s.index, s] as const)), [segments]);
  const pendingCount = corrections.items.filter((c) => c.status === "pending").length;

  const setStatus = (segmentIndex: number, status: Status) =>
    onChange({
      ...corrections,
      items: corrections.items.map((c) => (c.segmentIndex === segmentIndex ? { ...c, status } : c)),
    });

  const applyBulk = (to: "accepted" | "rejected") => {
    setBulk(null);
    onChange({
      ...corrections,
      items: corrections.items.map((c) => (c.status === "pending" ? { ...c, status: to } : c)),
    });
  };

  if (corrections.items.length === 0) {
    return <p className="text-[14px] leading-6 text-ink-2">{t.llmReview.noChanges}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-ink-2">{t.llmReview.pending(pendingCount)}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid="llm-show-original"
            aria-pressed={showOriginal}
            onClick={() => setShowingOriginal(runId, !showOriginal)}
          >
            {t.llmReview.showOriginal}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="llm-accept-all"
            disabled={pendingCount === 0}
            onClick={() => setBulk("accepted")}
          >
            {t.llmReview.acceptAll}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="llm-reject-all"
            disabled={pendingCount === 0}
            onClick={() => setBulk("rejected")}
          >
            {t.llmReview.rejectAll}
          </Button>
        </div>
      </div>

      <ol className="flex flex-col gap-3" data-testid="llm-review">
        {corrections.items.map((item) => {
          const seg = byIndex.get(item.segmentIndex);
          return (
            <CorrectionRow
              key={item.segmentIndex}
              item={item}
              time={seg ? formatElapsed(seg.start) : null}
              speaker={seg?.speaker ? speakerName(seg.speaker) : null}
              onStatus={(status) => setStatus(item.segmentIndex, status)}
            />
          );
        })}
      </ol>

      <AlertDialog open={bulk !== null} onOpenChange={(open) => (open ? undefined : setBulk(null))}>
        <AlertDialogContent data-testid="llm-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {bulk === "accepted" ? t.llmReview.confirmAcceptTitle : t.llmReview.confirmRejectTitle}
            </AlertDialogTitle>
            <AlertDialogDescription>{t.llmReview.confirmBody(pendingCount)}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.llmReview.confirmCancel}</AlertDialogCancel>
            <AlertDialogAction
              data-testid="llm-confirm-ok"
              onClick={() => {
                if (bulk) applyBulk(bulk);
              }}
            >
              {t.llmReview.confirmOk}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function CorrectionRow({
  item,
  time,
  speaker,
  onStatus,
}: {
  item: Correction;
  time: string | null;
  speaker: string | null;
  onStatus: (status: Status) => void;
}) {
  const { t } = useI18n();
  const accepted = item.status === "accepted";
  const rejected = item.status === "rejected";
  return (
    <li
      data-testid="llm-diff"
      data-segment-index={item.segmentIndex}
      data-status={item.status}
      data-corrected-text={item.corrected}
      className={cn(
        "flex flex-col gap-2 rounded-[14px] border bg-card p-3",
        accepted ? "border-primary/60" : "border-border",
      )}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-[13px] leading-5 text-ink-2">
        {time ? <span className="font-mono tabular-nums text-ink-3">{time}</span> : null}
        {speaker ? <span className="min-w-0 truncate">{speaker}</span> : null}
      </div>
      <p className="text-pretty text-[16px] leading-[1.7] text-foreground">
        <DiffText original={item.original} corrected={item.corrected} />
      </p>
      {item.reason ? <p className="text-[13px] leading-5 text-ink-2">{item.reason}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant={accepted ? "default" : "outline"}
          aria-pressed={accepted}
          data-testid="llm-accept"
          onClick={() => onStatus(accepted ? "pending" : "accepted")}
        >
          {t.llmReview.accept}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={rejected ? "default" : "outline"}
          aria-pressed={rejected}
          data-testid="llm-reject"
          onClick={() => onStatus(rejected ? "pending" : "rejected")}
        >
          {t.llmReview.reject}
        </Button>
      </div>
    </li>
  );
}

/** The word or character diff of one correction: removed text struck through, added text highlighted. */
function DiffText({ original, corrected }: { original: string; corrected: string }) {
  const [parts, setParts] = useState<DiffPart[] | null>(null);
  useEffect(() => {
    let alive = true;
    diffParts(original, corrected)
      .then((next) => {
        if (alive) setParts(next);
      })
      .catch(() => {
        if (alive) setParts([{ value: original, removed: true }, { value: corrected, added: true }]);
      });
    return () => {
      alive = false;
    };
  }, [original, corrected]);

  if (!parts) return <span>{corrected}</span>;
  return (
    <>
      {parts.map((part, i) =>
        part.removed ? (
          <del key={i} className="rounded-sm bg-destructive/10 text-destructive decoration-destructive/80 decoration-[1.5px]">
            {part.value}
          </del>
        ) : part.added ? (
          <ins key={i} className="rounded-sm bg-primary/15 text-foreground no-underline">
            {part.value}
          </ins>
        ) : (
          <span key={i}>{part.value}</span>
        ),
      )}
    </>
  );
}
