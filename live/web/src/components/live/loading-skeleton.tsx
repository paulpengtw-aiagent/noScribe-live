import { Skeleton } from "@/components/ui/skeleton";

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

/** Page placeholder before the first hello: three cards shaped like the live layout. */
export function LoadingSkeleton() {
  return (
    <div data-testid="loading-skeleton" role="status" aria-label="正在載入" aria-busy="true" className="live-grid">
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
