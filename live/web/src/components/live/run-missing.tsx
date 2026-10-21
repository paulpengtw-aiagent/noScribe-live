import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";

export interface RunMissingProps {
  onFollowNewest: () => void;
}

/** The server knows other runs, but not the one asked for (for example an old ?run= link). */
export function RunMissing({ onFollowNewest }: RunMissingProps) {
  const { t } = useI18n();
  return (
    <section
      data-testid="run-missing"
      aria-label={t.app.runMissingAria}
      className="live-card flex min-h-0 flex-1 flex-col items-start justify-center gap-4 p-8"
    >
      <h2 className="text-[20px] font-medium tracking-[-0.02em]">{t.app.runMissingTitle}</h2>
      <p className="text-[14px] leading-6 text-ink-2">{t.app.runMissingBody}</p>
      <Button type="button" variant="outline" size="sm" onClick={onFollowNewest}>
        {t.app.runMissingFollow}
      </Button>
    </section>
  );
}
