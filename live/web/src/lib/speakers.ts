// The speaker palette is the only hue in the UI. Colours are keyed by the order in which
// speakers first appear; "//" marks overlapping speech and is stripped before the lookup.

/** Dark theme palette, also used for the waveform bars on both themes. */
export const SPEAKER_PALETTE = ["#8fb4ff", "#f0a6c8", "#9ad7b4", "#f2cf8a", "#c3a6ff", "#7fd3e6"] as const;

/**
 * Light theme variant for text and legend dots. Yellow and mint fall below 1.6:1 against the light
 * card (#fafafa: #f2cf8a 1.43:1, #9ad7b4 1.58:1), so each is mixed 35% toward #1a1a1a, which
 * lifts them to 2.96:1 and 3.22:1. The other four are already at 1.63:1 or more and keep their values.
 */
export const SPEAKER_PALETTE_LIGHT = ["#8fb4ff", "#f0a6c8", "#6d957e", "#a69063", "#c3a6ff", "#7fd3e6"] as const;

export const UNKNOWN_SPEAKER_COLOR = "#737373";

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
  if (!key) return UNKNOWN_SPEAKER_COLOR;
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
