import { Button } from "@/components/ui/button";

export interface RunMissingProps {
  onFollowNewest: () => void;
}

/** The server knows other runs, but not the one asked for (for example an old ?run= link). */
export function RunMissing({ onFollowNewest }: RunMissingProps) {
  return (
    <section
      data-testid="run-missing"
      aria-label="Transcript"
      className="live-card flex min-h-0 flex-1 flex-col items-start justify-center gap-4 p-8"
    >
      <h2 className="text-[20px] font-medium tracking-[-0.02em]">找不到這場轉錄</h2>
      <p className="text-[14px] leading-6 text-ink-2">這個連結指向的轉錄不在目前的清單中。</p>
      <Button type="button" variant="outline" size="sm" onClick={onFollowNewest}>
        跟隨最新的轉錄
      </Button>
    </section>
  );
}
