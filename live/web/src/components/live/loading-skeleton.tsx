import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/i18n";

/** How long the run-loading placeholder shows before it says the wait is longer than usual. */
const SLOW_AFTER_MS = 8000;

/** Transcript-column placeholder while a run's start is awaited. */
export function TranscriptSkeleton() {
  return (
    <section
      data-testid="transcript-skeleton"
      aria-busy="true"
      className="live-card flex min-h-0 flex-1 flex-col gap-3 p-5"
    >
      <Skeleton className="h-6 w-2/5" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-11/12" />
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-3/5" />
    </section>
  );
}

/**
 * Transcript-column placeholder while an explicitly picked run's snapshot is awaited. It is loading, not
 * "not found": the not-found card only appears after the server's definitive 404. After about 8 s it also
 * says that the wait is longer than usual.
 */
export function RunLoading() {
  const { t } = useI18n();
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <section
      data-testid="run-loading"
      role="status"
      aria-busy="true"
      aria-label={t.app.runLoading}
      className="live-card flex min-h-0 flex-1 flex-col gap-3 p-5"
    >
      <p className="text-[14px] leading-6 text-ink-2">{t.app.runLoading}</p>
      {slow ? (
        <p data-testid="run-loading-slow" className="text-[14px] leading-6 text-ink-2">
          {t.app.runLoadingSlow}
        </p>
      ) : null}
      <Skeleton className="h-6 w-2/5" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-11/12" />
      <Skeleton className="h-4 w-4/5" />
    </section>
  );
}

/** Page placeholder before the first hello: three cards shaped like the live layout. */
export function LoadingSkeleton() {
  const { t } = useI18n();
  return (
    <div
      data-testid="loading-skeleton"
      role="status"
      aria-label={t.app.loadingLabel}
      aria-busy="true"
      className="live-grid"
    >
      <div className="live-stage live-card flex flex-col gap-4 p-5">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-36 w-full" />
        <div className="grid grid-cols-2 gap-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      </div>
      <div className="live-transcript">
        <TranscriptSkeleton />
      </div>
      <div className="live-timeline live-card flex flex-col gap-4 p-5">
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  );
}
