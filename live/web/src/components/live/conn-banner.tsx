import { WifiOff } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { Connection, RetryInfo } from "@/hooks/use-live-feed";
import { useNow } from "@/hooks/use-now";

export interface ConnBannerProps {
  connection: Connection;
  retry: RetryInfo;
}

/** Shown while the stream is down or silent. The last transcript stays on screen under it. */
export function ConnBanner({ connection, retry }: ConnBannerProps) {
  const down = connection === "reconnecting" || connection === "stale";
  const now = useNow(down, 1000);
  if (!down) return null;
  const seconds = retry.nextAt === null ? null : Math.max(0, Math.ceil((retry.nextAt - now) / 1000));
  const details = [
    retry.attempt > 0 ? `第 ${retry.attempt} 次重新連線` : null,
    seconds !== null ? `${seconds} 秒後重試` : null,
  ].filter((part): part is string => Boolean(part));
  return (
    <div className="px-4 pt-3 min-[1100px]:px-6">
      <Alert variant="destructive" data-testid="conn-banner">
        <WifiOff />
        <AlertTitle>連線中斷，正在重新連線…</AlertTitle>
        {details.length > 0 ? <AlertDescription>{details.join(" · ")}</AlertDescription> : null}
      </Alert>
    </div>
  );
}
