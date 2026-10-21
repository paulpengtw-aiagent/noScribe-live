import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Check, Download, X } from "lucide-react";
import { useI18n } from "@/i18n";
import { Button } from "@/components/ui/button";
import { useEasyView } from "@/hooks/use-easy-view";
import { saveOdt } from "@/lib/download-odt";
import { acceptedTexts, loadCorrections } from "@/lib/llm/store";
import { isRunActive, type RunState } from "@/lib/live-state";
import { useZhConverter } from "@/lib/zh-tw";
import { cn } from "@/lib/utils";

type Phase = "idle" | "working" | "done" | "error";

/** The button's state for tests and styling: data-state="idle | loading | success | error". */
const EXPORT_STATE: Record<Phase, "idle" | "loading" | "success" | "error"> = {
  idle: "idle",
  working: "loading",
  done: "success",
  error: "error",
};

/** How long the success or error state stays before the button returns to idle. */
const FEEDBACK_MS = 2000;

/** The file name from Content-Disposition: RFC 5987 filename* when present, else the plain filename. */
function fileNameFrom(disposition: string | null, fallback: string): string {
  if (disposition) {
    const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    if (star) {
      try {
        return decodeURIComponent(star[1].trim());
      } catch {
        // A malformed escape falls through to the plain name.
      }
    }
    const plain = /filename="([^"]+)"/i.exec(disposition);
    if (plain) return plain[1];
  }
  return fallback;
}

/**
 * Downloads the run as an .odt file (GET /api/runs/{id}/export.odt). Rendered only once the run has ended and has
 * segments, since the server answers 409 while it is live. When the run has accepted AI corrections, the file is built
 * in the page instead, with the corrected text and a note line. It fades in with a 6 px rise, except under reduced
 * motion and Easy view.
 */
export function ExportButton({ run }: { run: RunState }) {
  const { t, locale } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const live = isRunActive(run);
  const reduce = useReducedMotion() ?? false;
  const { easy } = useEasyView();
  const { display } = useZhConverter();
  const lang = locale === "zh-TW" ? "zh-TW" : "en";

  useEffect(() => {
    if (phase !== "done" && phase !== "error") return;
    const timer = window.setTimeout(() => setPhase("idle"), FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  if (live || run.segments.length === 0) return null;

  /** Builds the .odt in the page from the accepted corrections. Returns false when there are none. */
  const downloadCorrected = async (): Promise<boolean> => {
    const corrected = acceptedTexts(await loadCorrections(run.runId).catch(() => null));
    if (corrected.size === 0) return false;
    const { buildOdt, exportFileName } = await import("@/lib/llm/odt");
    const bytes = buildOdt({
      title: run.audioName || run.runId,
      segments: run.segments.map((seg) => ({
        index: seg.index,
        start: seg.start,
        end: seg.end,
        speaker: seg.speaker,
        text: corrected.get(seg.index) ?? display(seg.text.trim()),
      })),
      lang,
      startedT: run.startedT,
      duration: run.duration,
      model: run.model,
      speakers: run.speakers,
      note: t.llmReview.appliedNote(corrected.size),
    });
    saveOdt(bytes, exportFileName(run.audioName, run.runId, run.startedT));
    return true;
  };

  const download = async () => {
    setPhase("working");
    try {
      if (await downloadCorrected()) {
        setPhase("done");
        return;
      }
      const url = `/api/runs/${encodeURIComponent(run.runId)}/export.odt?lang=${lang}`;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`export failed: HTTP ${res.status}`);
      const blob = await res.blob();
      const name = fileNameFrom(res.headers.get("Content-Disposition"), `${run.runId}.odt`);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 1000);
      setPhase("done");
    } catch {
      setPhase("error");
    }
  };

  const Icon = phase === "done" ? Check : phase === "error" ? X : Download;
  const label = phase === "done" ? t.export.done : phase === "error" ? t.export.failed : t.export.label;
  return (
    <motion.div
      className="shrink-0 self-start sm:self-auto"
      initial={reduce || easy ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="export-odt"
        data-state={EXPORT_STATE[phase]}
        data-phase={phase}
        disabled={phase === "working"}
        onClick={download}
        className={cn(
          "shrink-0 rounded-full border-[#81a1c1]/50 bg-transparent text-[#5d8598] hover:bg-[#81a1c1]/15 hover:text-[#5d8598] dark:text-[#88c0d0] dark:hover:text-[#88c0d0]",
          phase === "done" && "border-[#a3be8c]/60 text-[#6f866f] dark:text-[#a3be8c]",
          phase === "error" && "border-[#bf616a]/60 text-[#bf616a] dark:text-[#bf616a]",
        )}
      >
        <Icon aria-hidden="true" />
        {label}
      </Button>
    </motion.div>
  );
}
