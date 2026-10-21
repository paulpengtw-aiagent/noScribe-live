// The speaker palette is the only hue in the UI. Colours are keyed by the order in which
// speakers first appear; "//" marks overlapping speech and is stripped before the lookup.

/**
 * Dark theme palette: Nord Aurora and Frost hues, each at least 3:1 against the dark card (#3b4252).
 * Timeline blocks and waveform bars use these fills on both themes; on the light theme the pale fills
 * get a Frost-deep edge instead of a darkening filter (index.css, `.timeline-block[data-timeline-index]`).
 */
export const SPEAKER_PALETTE = ["#88c0d0", "#ebcb8b", "#a3be8c", "#b48ead", "#81a1c1", "#d08770"] as const;

/**
 * Light theme variant for text and legend dots: the Frost and Aurora hues, deepened so each is at least
 * 3:1 against the light card (#ebeef3) and the light page (#e5e9f0), and none reads as brown or slate.
 * Same slot order as SPEAKER_PALETTE: Frost, ochre, green, purple, blue, rust.
 */
export const SPEAKER_PALETTE_LIGHT = ["#4a7f96", "#a67c00", "#5b7f45", "#7e5a86", "#5e81ac", "#a4532b"] as const;

/** Unknown speaker on the dark theme: 4:1 against the dark card. */
export const UNKNOWN_SPEAKER_COLOR = "#9aa5b6";
/** Unknown speaker on the light theme: 3.7:1 against the light card. */
export const UNKNOWN_SPEAKER_COLOR_LIGHT = "#6b778c";

/**
 * Crimson palette fills (timeline blocks, waveform bars, speaker chips): red, navy-blue, gold, teal, silver
 * and blue. Each is at least 3:1 against both the Crimson light card (#FBF9F3) and the dark card (#0F1D2C),
 * so one set serves both themes.
 */
export const CRIMSON_SPEAKER_FILL = ["#b8424a", "#3b6e9e", "#a8843e", "#2f8f87", "#8a8d8f", "#0077c8"] as const;
/** Crimson text and legend dots on the light theme: at least 4.5:1 against the Crimson light card. */
export const CRIMSON_SPEAKER_DOT_LIGHT = ["#93272c", "#003865", "#7a5a1e", "#0061a8", "#24665f", "#53565a"] as const;
/** Crimson text and legend dots on the dark theme: at least 4.5:1 against the Crimson dark card. */
export const CRIMSON_SPEAKER_DOT_DARK = ["#f08a8f", "#a4bcc2", "#f5e1a4", "#7fb8e6", "#6cc5bd", "#c8c9c7"] as const;
const CRIMSON_UNKNOWN_FILL = "#8a8d8f";
const CRIMSON_UNKNOWN_DOT_LIGHT = "#6b6f73";
const CRIMSON_UNKNOWN_DOT_DARK = "#9aa3ad";

const NUMBERED_LABEL = /^S\d+$/;

/** True while <html data-palette="crimson"> is set. Read at call time; use-theme.ts sets the attribute. */
function isCrimson(): boolean {
  return typeof document !== "undefined" && document.documentElement.dataset.palette === "crimson";
}

export function isOverlapLabel(label: string): boolean {
  return label.startsWith("//");
}

export function speakerKey(label: string): string {
  return isOverlapLabel(label) ? label.slice(2) : label;
}

/** Colour for a speaker label given the speakers in order of first appearance. */
export function speakerColor(speakers: readonly string[], label: string): string {
  const key = speakerKey(label);
  const crimson = isCrimson();
  if (!key) return crimson ? CRIMSON_UNKNOWN_FILL : UNKNOWN_SPEAKER_COLOR;
  const index = speakers.indexOf(key);
  const slot = index < 0 ? speakers.length : index;
  const palette = crimson ? CRIMSON_SPEAKER_FILL : SPEAKER_PALETTE;
  return palette[slot % palette.length];
}

/** Colour for text and legend dots: the light variant on the light theme. */
export function speakerDotColor(speakers: readonly string[], label: string, theme: "dark" | "light"): string {
  const key = speakerKey(label);
  const crimson = isCrimson();
  if (!key) {
    if (crimson) return theme === "light" ? CRIMSON_UNKNOWN_DOT_LIGHT : CRIMSON_UNKNOWN_DOT_DARK;
    return theme === "light" ? UNKNOWN_SPEAKER_COLOR_LIGHT : UNKNOWN_SPEAKER_COLOR;
  }
  const index = speakers.indexOf(key);
  const slot = index < 0 ? speakers.length : index;
  const palette = crimson
    ? theme === "light"
      ? CRIMSON_SPEAKER_DOT_LIGHT
      : CRIMSON_SPEAKER_DOT_DARK
    : theme === "light"
      ? SPEAKER_PALETTE_LIGHT
      : SPEAKER_PALETTE;
  return palette[slot % palette.length];
}

/**
 * Name shown for a speaker label. "S00" becomes "Speaker 1", numbered by order of first
 * appearance (1-based). A label missing from the list falls back to its own number plus one.
 * Custom names are returned as they are. Overlap marks are stripped.
 */
export function speakerDisplayName(label: string, speakers: readonly string[]): string {
  const key = speakerKey(label);
  if (!key) return "";
  if (!NUMBERED_LABEL.test(key)) return key;
  const index = speakers.indexOf(key);
  if (index >= 0) return `Speaker ${index + 1}`;
  return `Speaker ${Number(key.slice(1)) + 1}`;
}
