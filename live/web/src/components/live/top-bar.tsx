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
import { displayPhase, type RunState } from "@/lib/live-state";
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

/** Status colours, the same as the run picker's: failed red, stopped orange, live green, loading yellow, else neutral. */
type Tone = "red" | "amber" | "green" | "yellow" | "neutral";

/** Icon glyph per tone; the glyph and the word carry the state, so colour is never the only cue. */
const TONE_TEXT: Record<Tone, string> = {
  red: "text-status-failed-ink",
  amber: "text-status-stopped-ink",
  green: "text-status-live-ink",
  yellow: "text-status-loading-ink",
  neutral: "text-foreground",
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
  /**
   * The pre-roll is on screen: the header keeps only the logo and the toggles. Hides the run picker, the
   * other-live switch and the run-state chip.
   */
  minimal?: boolean;
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
  minimal = false,
}: TopBarProps) {
  const { t } = useI18n();
  const { easy } = useEasyView();
  const compact = useCompactHeader();
  // Easy view on a phone-width header: the header may wrap to two rows instead of overflowing.
  const easyPhone = easy && compact;
  const badge = runStateBadge(run);
  const live = badge?.status === "running";
  // Only "live" counts as connected. Any other state (including the legacy "stale") reads as reconnecting.
  const link = connection === "live" ? "live" : connection === "connecting" ? "connecting" : "reconnecting";
  // A live run whose feed is not connected: the run badge carries the connection text, so the
  // connection text is kept for screen readers only. data-state keeps the raw link state either way.
  const feedDown = live && link !== "live";
  const cutOff = feedDown && link === "reconnecting";
  // A running run with no segment yet (or still diarizing / loading the model) reads Loading, not Live.
  const loading = live && displayPhase(run) !== "transcribing";
  const badgeText = badge
    ? feedDown
      ? cutOff
        ? t.topbar.runDisconnected
        : t.topbar.connConnecting
      : loading
        ? t.topbar.runStatus.loading
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
          ? loading
            ? "yellow"
            : "green"
          : "neutral";
  const GLYPH: Record<Tone, string> = { red: "✕", amber: cutOff ? "⟳" : "■", green: "●", yellow: "◐", neutral: badge?.status === "canceled" ? "○" : "✓" };
  // Easy view names the run's state with an icon and a word (EasyStatus) instead of the run badge text.
  const easyKind: EasyStatusKind | null = !badge
    ? null
    : feedDown
      ? "reconnecting"
      : badge.status === "running"
        ? loading
          ? "loading"
          : "live"
        : badge.status === "finished"
          ? "finished"
          : badge.status === "error"
            ? "failed"
            : badge.status === "canceled"
              ? "canceled"
              : "stopped";
  const connText =
    link === "live"
      ? t.topbar.connConnected
      : link === "connecting"
        ? t.topbar.connConnecting
        : t.topbar.connReconnecting;

  return (
    <header
      className={cn(
        "sticky top-0 z-40 flex shrink-0 items-center border-b border-hairline header-glass",
        easyPhone ? "min-h-14 py-2" : "h-14",
      )}
    >
      <div
        className={cn(
          "flex w-full min-w-0 items-center justify-between px-4 min-[1100px]:px-6",
          easyPhone ? "flex-wrap gap-x-3 gap-y-2" : "gap-3",
        )}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span aria-hidden="true" data-testid="logo" className="flex shrink-0 max-sm:size-7 max-sm:items-center max-sm:justify-center">
            <Orb variant="G1" size={18} label={t.topbar.processing} />
          </span>
          <span className="min-w-0 truncate text-[15px] font-medium tracking-[-0.01em] max-sm:sr-only">
            {t.topbar.appName}
          </span>
        </div>

        <div className={cn("flex min-w-0 flex-1 items-center gap-2 sm:flex-initial sm:gap-4", easyPhone && "flex-wrap justify-end")}>
          {otherLive && !easyPhone && !minimal && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="other-live-run"
              onClick={() => onRunChange(otherLive.run_id)}
              className={cn(
                "rounded-full bg-raised px-3 text-[13px] text-foreground shadow-ring hover:bg-raised sm:max-w-none sm:shrink-0 dark:bg-raised dark:hover:bg-raised",
                easyPhone
                  ? "h-auto max-w-full shrink-0 whitespace-normal py-1.5 text-left"
                  : "h-8 min-w-0 max-w-[120px] shrink",
              )}
            >
              <span aria-hidden="true" className="size-1.5 shrink-0 animate-pulse rounded-full bg-foreground" />
              <span className={easyPhone ? "whitespace-normal" : "truncate"}>{easyPhone ? t.topbar.otherLiveShort : t.topbar.otherLive}</span>
            </Button>
          )}

          {!minimal && (
            <Suspense fallback={null}>
              <RunPicker runs={runs} value={runParam} onChange={onRunChange} />
            </Suspense>
          )}

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
            {badge && !minimal && (
              <span
                data-testid="run-state"
                data-state={badge.status}
                className={cn(
                  "flex min-w-0 items-center gap-1.5 rounded-full bg-raised px-2.5 py-0.5 text-[12px] font-medium shadow-ring",
                  easyPhone ? "shrink-0" : "shrink",
                  // Easy view on phones: the status pill is visually hidden (the Easy status sentence under the stage
                  // says the same). The node stays in the DOM and its text stays for screen readers.
                  easy && "max-sm:sr-only",
                  TONE_TEXT[tone],
                )}
              >
                <span
                  aria-hidden="true"
                  data-testid="run-state-dot"
                  data-tone={tone}
                  className="shrink-0 text-[11px] leading-none"
                >
                  {GLYPH[tone]}
                </span>
                <span className={cn("min-w-0 truncate", !easy && "max-[359px]:sr-only")}>
                  {easy && easyKind ? <EasyStatus kind={easyKind} /> : badgeText}
                </span>
              </span>
            )}
          </div>

          {/* Easy view is always one visible header button (the short label on phones); the gear menu holds the rest. */}
          <EasyToggle compact={compact} />
          {compact ? (
            <HeaderMenu theme={theme} onToggleTheme={onToggleTheme} />
          ) : (
            <>
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
