import { WifiOff } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { Connection, RetryInfo } from "@/hooks/use-live-feed";
import { useNow } from "@/hooks/use-now";
import { formatClock, useI18n } from "@/i18n";

export interface ConnBannerProps {
  connection: Connection;
  retry: RetryInfo;
  /** Epoch seconds of the last message received, or null before the first one. */
  lastUpdateT: number | null;
}

/**
 * Overlay shown while the stream is down. It is fixed below the header, so it never pushes
 * the page down; the last transcript stays on screen under it.
 */
export function ConnBanner({ connection, retry, lastUpdateT }: ConnBannerProps) {
  if (connection !== "reconnecting") return null;
  return <ConnBannerBody retry={retry} lastUpdateT={lastUpdateT} />;
}

function ConnBannerBody({ retry, lastUpdateT }: Omit<ConnBannerProps, "connection">) {
  const { t, locale } = useI18n();
  // Mounted only while down, so the countdown starts from the current time, not a stale one.
  const now = useNow(true, 1000);
  const seconds = retry.nextAt === null ? null : Math.max(0, Math.ceil((retry.nextAt - now) / 1000));
  const attemptLine =
    retry.attempt > 0
      ? seconds === null
        ? t.app.connAttempt(retry.attempt)
        : t.app.connAttemptRetry(retry.attempt, seconds)
      : null;
  const lastLine = lastUpdateT === null ? null : t.app.connLastUpdate(formatClock(lastUpdateT, locale));
  return (
    <div className="pointer-events-none fixed inset-x-0 top-[4.25rem] z-50 flex justify-center px-4">
      <Alert
        variant="destructive"
        data-testid="conn-banner"
        role="status"
        className="pointer-events-auto w-auto max-w-[32rem] bg-popover shadow-lg"
      >
        <WifiOff />
        <AlertTitle>{t.app.connLost}</AlertTitle>
        {attemptLine || lastLine ? (
          <AlertDescription>
            {attemptLine ? <span className="block">{attemptLine}</span> : null}
            {lastLine ? <span className="block">{lastLine}</span> : null}
          </AlertDescription>
        ) : null}
      </Alert>
    </div>
  );
}
