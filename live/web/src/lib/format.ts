const CJK_CHAR = /[　-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯가-힯]/;

/** True when a character belongs to a script that is written without spaces. */
export function isCjkChar(ch: string): boolean {
  return CJK_CHAR.test(ch);
}

/** Segments are joined with a space unless one side is CJK. */
export function needsSpaceBetween(prevText: string, nextText: string): boolean {
  const a = prevText.trimEnd().slice(-1);
  const b = nextText.trimStart().charAt(0);
  if (!a || !b) return false;
  return !isCjkChar(a) && !isCjkChar(b);
}

/** Mostly-CJK text gets lang="zh-Hant" on its span. */
export function isMostlyCjk(text: string): boolean {
  const chars = text.replace(/\s+/g, "");
  if (!chars) return false;
  let cjk = 0;
  for (const ch of chars) if (isCjkChar(ch)) cjk += 1;
  return cjk / [...chars].length >= 0.5;
}

/** Shown wherever a value is not known yet. */
export const DASH = "—";

/** mm:ss, or h:mm:ss from one hour. */
export function formatClock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return DASH;
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Always HH:MM:SS, used for transcript block starts. */
export function formatTimecode(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

/** Run time as m:ss (minutes not padded) or h:mm:ss from one hour: "0:48", "12:05", "1:02:03". */
export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return DASH;
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const ss = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return DASH;
  if (Math.abs(ms) < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatRtf(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  return `${value < 10 ? value.toFixed(2) : value.toFixed(1)}×`;
}

export function formatPercent(fraction: number): string {
  return `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%`;
}

/** Local 24-hour HH:MM for a unix-seconds timestamp. */
export function formatTimeOfDay(unixSeconds: number | null | undefined): string {
  if (unixSeconds == null || !Number.isFinite(unixSeconds)) return DASH;
  const d = new Date(unixSeconds * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function basename(path: string | null | undefined): string | null {
  if (!path) return null;
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** "NVIDIA GeForce RTX 5060 Ti" -> "RTX 5060 Ti". */
export function shortDeviceName(name: string | null | undefined): string | null {
  if (!name) return null;
  return name.replace(/^NVIDIA\s+(GeForce\s+)?/i, "").trim() || null;
}
