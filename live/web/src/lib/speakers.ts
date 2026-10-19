// The speaker palette is the only hue in the UI. Colours are keyed by the
// order in which speakers first appear; "//" marks overlapping speech and is
// stripped before the lookup.

export const SPEAKER_PALETTE = ["#8fb4ff", "#f0a6c8", "#9ad7b4", "#f2cf8a", "#c3a6ff", "#7fd3e6"] as const;

export const UNKNOWN_SPEAKER_COLOR = "#737373";

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
