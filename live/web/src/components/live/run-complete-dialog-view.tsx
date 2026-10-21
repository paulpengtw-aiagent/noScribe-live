// The transcription-complete dialog's UI. It loads on demand (see run-complete-dialog.tsx), so the entry bundle carries
// only the detection. The download is the export button's request (lib/download-odt).
import { useState } from "react";
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
import type { RunCompleteSummary } from "@/components/live/run-complete-dialog";
import { useI18n } from "@/i18n";
import { downloadOdt } from "@/lib/download-odt";
import { formatClock } from "@/lib/format";

export default function RunCompleteView({
  summary,
  open,
  onOpenChange,
}: {
  summary: RunCompleteSummary;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t, locale } = useI18n();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const lang = locale === "zh-TW" ? "zh-TW" : "en";

  const download = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await downloadOdt(summary.runId, lang);
      onOpenChange(false);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent data-testid="run-complete-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{t.app.runCompleteTitle}</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <ul data-testid="run-complete-stats" className="grid gap-1">
              <li>{t.app.runCompleteLength(formatClock(summary.duration))}</li>
              <li>{t.app.runCompleteSegments(summary.segments)}</li>
              <li>{t.app.runCompleteSpeakers(summary.speakers)}</li>
            </ul>
          </AlertDialogDescription>
        </AlertDialogHeader>
        {failed ? (
          <p role="alert" className="text-sm text-status-failed-ink">
            {t.export.failed}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="run-complete-keep">{t.app.runCompleteKeep}</AlertDialogCancel>
          <AlertDialogAction
            data-testid="run-complete-download"
            disabled={busy}
            onClick={(event) => {
              // The dialog stays open while the file is fetched; it closes itself once the download succeeds.
              event.preventDefault();
              void download();
            }}
          >
            {t.export.label}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
