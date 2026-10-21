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

const NUMBERED_LABEL = /^S\d+$/;

export function isOverlapLabel(label: string): boolean {
  return label.startsWith("//");
}

export function speakerKey(label: string): string {
  return isOverlapLabel(label) ? label.slice(2) : label;
}

/** Colour for a speaker label given the speakers in order of first appearance. */
export function speakerColor(speakers: readonly string[], label: string): string {
  const key = speakerKey(label);
  if (!key) return UNKNOWN_SPEAKER_COLOR;
  const index = speakers.indexOf(key);
  const slot = index < 0 ? speakers.length : index;
  return SPEAKER_PALETTE[slot % SPEAKER_PALETTE.length];
}

/** Colour for text and legend dots: the light variant on the light theme. */
export function speakerDotColor(speakers: readonly string[], label: string, theme: "dark" | "light"): string {
  const key = speakerKey(label);
  if (!key) return theme === "light" ? UNKNOWN_SPEAKER_COLOR_LIGHT : UNKNOWN_SPEAKER_COLOR;
  const index = speakers.indexOf(key);
  const slot = index < 0 ? speakers.length : index;
  const palette = theme === "light" ? SPEAKER_PALETTE_LIGHT : SPEAKER_PALETTE;
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
