import { cn } from "@/lib/utils";

/** The CLI's raw error text behind a small disclosure. It wraps and can be selected and copied. */
export function ErrorDetails({ raw, className }: { raw: string; className?: string }) {
  return (
    <details className={cn("min-w-0 text-left text-[12px] leading-5 text-ink-3", className)}>
      <summary className="w-fit cursor-pointer select-none hover:text-ink-2">詳細錯誤</summary>
      <pre className="mt-1.5 max-h-48 overflow-auto rounded-[10px] bg-raised p-2.5 font-mono text-[11px] leading-[1.5] text-ink-2 break-words whitespace-pre-wrap shadow-ring select-text">
        {raw}
      </pre>
    </details>
  );
}
