import { lazy, Suspense, useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { Orb } from "@/components/aicss/Orb";
import { HeaderMenu } from "@/components/live/header-menu";
import { EasyStatus, EasyToggle, type EasyStatusKind } from "@/components/live/easy-toggle";
import { LocaleToggle } from "@/components/live/locale-toggle";
import { Button } from "@/components/ui/button";
import { useEasyView } from "@/hooks/use-easy-view";
import type { Connection } from "@/hooks/use-live-feed";
import type { Theme } from "@/hooks/use-theme";
import { useI18n } from "@/i18n";
import type { RunState } from "@/lib/live-state";
import { runStateBadge } from "@/lib/live-view";
import type { RunSummary } from "@/lib/live-types";
import { cn } from "@/lib/utils";

// The run picker (popover + cmdk command palette) is its own chunk, fetched on first render.
const RunPicker = lazy(() =>
  import("@/components/live/run-picker").then((mod) => ({ default: mod.RunPicker })),
);

// Below Tailwind's sm breakpoint (40rem). There the theme and language switches fold into one menu.
const COMPACT_QUERY = "(max-width: 39.99rem)";

function subscribeCompact(onChange: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(COMPACT_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function useCompactHeader(): boolean {
  return useSyncExternalStore(
    subscribeCompact,
    () => typeof window.matchMedia === "function" && window.matchMedia(COMPACT_QUERY).matches,
    () => false,
  );
}

/** Status dot colours, the same as the run picker's: failed red, stopped amber, live green, the rest neutral. */
type Tone = "red" | "amber" | "green" | "neutral";

const TONE_DOT: Record<Tone, string> = {
  red: "bg-red-500",
  amber: "bg-amber-500",
  green: "bg-emerald-500",
  neutral: "bg-foreground/60",
};

export interface TopBarProps {
  runs: RunSummary[];
  runParam: string;
  onRunChange: (runParam: string) => void;
  /** The shown run, or null when none is shown. */
  run: RunState | null;
  /** A still-running run other than the shown one; offers a switch. Null when there is none. */
  otherLive: RunSummary | null;
  connection: Connection;
  theme: Theme;
  onToggleTheme: () => void;
}

export function TopBar({
  runs,
  runParam,
  onRunChange,
  run,
  otherLive,
  connection,
  theme,
  onToggleTheme,
}: TopBarProps) {
  const { t } = useI18n();
  const { easy } = useEasyView();
  const compact = useCompactHeader();
  const badge = runStateBadge(run);
  const live = badge?.status === "running";
  // Only "live" counts as connected. Any other state (including the legacy "stale") reads as reconnecting.
  const link = connection === "live" ? "live" : connection === "connecting" ? "connecting" : "reconnecting";
  // A live run whose feed is not connected: the run badge carries the connection text, so the
  // connection text is kept for screen readers only. data-state keeps the raw link state either way.
  const feedDown = live && link !== "live";
  const cutOff = feedDown && link === "reconnecting";
  const badgeText = badge
    ? feedDown
      ? cutOff
        ? t.topbar.runDisconnected
        : t.topbar.connConnecting
      : t.topbar.runStatus[badge.status]
    : null;
  // A live run whose feed is cut off reads amber (connection trouble), whatever the run's own status.
  const tone: Tone = cutOff
    ? "amber"
    : badge?.status === "error"
      ? "red"
      : badge?.status === "stale"
        ? "amber"
        : badge?.status === "running"
          ? "green"
          : "neutral";
  // Easy view names the run's state with an icon and a word (EasyStatus) instead of the run badge text.
  const easyKind: EasyStatusKind | null = !badge
    ? null
    : feedDown
      ? "reconnecting"
      : badge.status === "running"
        ? "live"
        : badge.status === "finished"
          ? "finished"
          : badge.status === "error"
            ? "failed"
            : "stopped";
  const connText =
    link === "live"
      ? t.topbar.connConnected
      : link === "connecting"
        ? t.topbar.connConnecting
        : t.topbar.connReconnecting;

  return (
    <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center border-b border-hairline bg-background/80 backdrop-blur-xl">
      <div className="flex w-full min-w-0 items-center justify-between gap-3 px-4 min-[1100px]:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <span aria-hidden="true" data-testid="logo" className="flex shrink-0 max-sm:size-7 max-sm:items-center max-sm:justify-center">
            <Orb variant="G1" size={18} label={t.topbar.processing} />
          </span>
          <span className="min-w-0 truncate text-[15px] font-medium tracking-[-0.01em] max-sm:sr-only">
            {t.topbar.appName}
          </span>
        </div>

        <div className="flex min-w-0 flex-1 items-center gap-2 sm:flex-initial sm:gap-4">
          {otherLive && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="other-live-run"
              onClick={() => onRunChange(otherLive.run_id)}
              className="h-8 min-w-0 max-w-[120px] shrink rounded-full bg-raised px-3 text-[13px] text-foreground shadow-ring hover:bg-raised sm:max-w-none sm:shrink-0 dark:bg-raised dark:hover:bg-raised"
            >
              <span aria-hidden="true" className="size-1.5 shrink-0 animate-pulse rounded-full bg-foreground" />
              <span className="truncate">{t.topbar.otherLive}</span>
            </Button>
          )}

          <Suspense fallback={null}>
            <RunPicker runs={runs} value={runParam} onChange={onRunChange} />
          </Suspense>

          <div role="status" className="flex shrink-0 items-center gap-2 text-[13px] text-ink-2">
            <span
              data-testid="conn-state"
              data-state={link}
              className={cn("flex items-center gap-1.5", feedDown && "sr-only")}
            >
              {link !== "live" && !feedDown && (
                <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-ink-3" />
              )}
              <span className={cn(link === "live" ? "sr-only" : "max-sm:sr-only")}>{connText}</span>
            </span>
            {badge && (
              <span
                data-testid="run-state"
                data-state={badge.status}
                className={cn(
                  "flex min-w-0 shrink items-center gap-2 rounded-full bg-raised px-2.5 py-0.5 text-[12px] font-medium shadow-ring",
                  cutOff ? "text-amber-700 dark:text-amber-400" : "text-foreground",
                )}
              >
                <span
                  aria-hidden="true"
                  data-testid="run-state-dot"
                  data-tone={tone}
                  className={cn("size-1.5 shrink-0 rounded-full", TONE_DOT[tone], live && "animate-pulse")}
                />
                <span className="min-w-0 truncate max-[359px]:sr-only">
                  {easy && easyKind ? <EasyStatus kind={easyKind} /> : badgeText}
                </span>
              </span>
            )}
          </div>

          {compact ? (
            <HeaderMenu theme={theme} onToggleTheme={onToggleTheme} />
          ) : (
            <>
              <EasyToggle />
              <LocaleToggle />

              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={onToggleTheme}
                aria-label={theme === "dark" ? t.topbar.switchTheme.light : t.topbar.switchTheme.dark}
                className="shrink-0 rounded-full shadow-ring hover:bg-raised dark:hover:bg-raised"
              >
                {theme === "dark" ? <Sun /> : <Moon />}
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
