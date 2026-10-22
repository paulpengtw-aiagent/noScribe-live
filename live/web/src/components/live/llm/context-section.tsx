import { useMemo, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { CircleAlert, CircleCheck, Clock, LoaderCircle, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n, type Locale } from "@/i18n";
import { cn } from "@/lib/utils";
import { CONTEXT_ACCEPT } from "@/lib/llm/parse-docs";
import { CONTEXT_REJECT, useContextDocs } from "@/lib/llm/context-store";
import { estimateTokens, type ContextDoc } from "@/lib/llm/types";

export interface ContextSectionProps {
  /** Estimated tokens above which the panel notes that the most relevant passages are chosen per batch. */
  budgetTokens?: number;
}

/** A refused row has status "error" and one of the refusal messages. Refused rows do not count toward the limits. */
function isRefused(doc: ContextDoc): boolean {
  return (
    doc.status === "error" &&
    (doc.error === CONTEXT_REJECT.tooManyFiles ||
      doc.error === CONTEXT_REJECT.tooLarge ||
      doc.error === CONTEXT_REJECT.unsupported)
  );
}

function formatSize(bytes: number, locale: Locale): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024)).toLocaleString(locale)} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString(locale, { maximumFractionDigits: 1 })} MB`;
}

function StatusIcon({ status }: { status: ContextDoc["status"] }) {
  const base = "size-5 shrink-0";
  if (status === "parsing") {
    return <LoaderCircle aria-hidden="true" className={cn(base, "animate-spin text-muted-foreground")} />;
  }
  if (status === "ok") return <CircleCheck aria-hidden="true" className={cn(base, "text-primary")} />;
  if (status === "error") return <CircleAlert aria-hidden="true" className={cn(base, "text-destructive")} />;
  return <Clock aria-hidden="true" className={cn(base, "text-muted-foreground")} />;
}

/** Reference documents attached as context: free-text notes plus a dropzone for .docx, .pdf, .txt and .md files. */
export function ContextSection({ budgetTokens = 60000 }: ContextSectionProps = {}) {
  const { t, locale } = useI18n();
  const m = t.llmContext;
  const { docs, freeText, addFiles, remove, setFreeText } = useContextDocs();
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const stats = useMemo(() => {
    let files = 0;
    let chars = freeText.length;
    let tokens = estimateTokens(freeText);
    for (const doc of docs) {
      if (!isRefused(doc)) files += 1;
      if (doc.status === "ok" && doc.text !== undefined) {
        chars += doc.text.length;
        tokens += estimateTokens(doc.text);
      }
    }
    return { files, chars, tokens };
  }, [docs, freeText]);

  const overBudget = stats.tokens > budgetTokens;
  const fmt = (n: number) => n.toLocaleString(locale);
  const statLine = [m.fileCount(stats.files), m.charCount(fmt(stats.chars)), m.tokenCount(fmt(stats.tokens))].join(
    " · ",
  );

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setDragging(true);
  }

  function onDragLeave(e: DragEvent<HTMLDivElement>) {
    // Moving between the zone's children fires leave events; only a real exit clears the drop state.
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setDragging(false);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length > 0) addFiles(Array.from(e.dataTransfer.files));
  }

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    // Clear the input so picking the same file again still fires a change event.
    e.target.value = "";
    if (picked.length > 0) addFiles(picked);
  }

  function errorText(doc: ContextDoc): string {
    if (doc.error === CONTEXT_REJECT.tooManyFiles) return m.limitFiles;
    if (doc.error === CONTEXT_REJECT.tooLarge) return m.limitSize;
    if (doc.error === CONTEXT_REJECT.unsupported) return m.unsupported;
    return m.parseFailed;
  }

  return (
    <section aria-labelledby="llm-context-heading" className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h3 id="llm-context-heading" className="text-lg font-semibold">
          {m.title}
        </h3>
        <p className="text-[15px] text-muted-foreground">{m.hint}</p>
      </div>

      <label className="flex flex-col gap-2">
        <span className="text-[15px] font-medium">{m.textLabel}</span>
        <textarea
          data-testid="llm-context-text"
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder={m.textPlaceholder}
          rows={5}
          className="min-h-32 w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 text-[16px] leading-relaxed outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />
      </label>

      <div
        data-testid="llm-dropzone"
        data-dragging={dragging ? "true" : "false"}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={cn(
          "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors",
          dragging ? "border-primary bg-primary/10" : "border-border bg-muted/30",
        )}
      >
        <Upload aria-hidden="true" className={cn("size-8", dragging ? "text-primary" : "text-muted-foreground")} />
        <p className="text-[16px] font-medium">{dragging ? m.dropActive : m.dropTitle}</p>
        <p className="max-w-prose text-[14px] text-muted-foreground">{m.dropHint}</p>
        <Button type="button" variant="outline" onClick={() => inputRef.current?.click()}>
          {m.chooseFiles}
        </Button>
        <input
          ref={inputRef}
          data-testid="llm-files"
          type="file"
          multiple
          accept={CONTEXT_ACCEPT}
          onChange={onPick}
          tabIndex={-1}
          aria-hidden="true"
          className="sr-only"
        />
      </div>

      {docs.length > 0 && (
        <ul className="flex flex-col gap-2">
          {docs.map((doc) => (
            <li
              key={doc.id}
              data-testid="llm-file"
              data-status={doc.status}
              className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3"
            >
              <StatusIcon status={doc.status} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-medium" title={doc.name}>
                  {doc.name}
                </p>
                <p className="text-[13px] text-muted-foreground">
                  {formatSize(doc.bytes, locale)} · {isRefused(doc) ? m.status.refused : m.status[doc.status]}
                  {doc.status === "ok" && doc.chars !== undefined && <> · {m.chars(fmt(doc.chars))}</>}
                </p>
                {doc.status === "error" && (
                  <p className="text-[13px] text-destructive" title={doc.error}>
                    {errorText(doc)}
                  </p>
                )}
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={m.removeLabel(doc.name)}
                onClick={() => remove(doc.id)}
              >
                <X aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <p data-testid="llm-context-stats" className="text-[14px] text-muted-foreground">
        {statLine}
      </p>

      {overBudget && (
        <p
          data-testid="llm-retrieval-note"
          role="note"
          className="rounded-lg bg-muted px-4 py-3 text-[15px] leading-relaxed"
        >
          {m.retrievalNote}
        </p>
      )}
    </section>
  );
}
