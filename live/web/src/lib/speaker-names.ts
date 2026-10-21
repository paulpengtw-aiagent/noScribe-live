import { createContext, useCallback, useContext } from "react";
import { useI18n } from "@/i18n";
import { speakerKey } from "@/lib/speakers";

/** Speakers in order of first appearance. The page provides it once, so every view numbers speakers alike. */
export const SpeakerOrderContext = createContext<readonly string[]>([]);

/** Same numbering rule as speakers.ts: only generated labels (S1, S2, ...) get a number. */
const NUMBERED_LABEL = /^S\d+$/;

/**
 * Display name for a speaker label. A real name is shown as it is. A generated label becomes the locale's
 * numbered form (speakerNumber), numbered by the order the page provides. "" when there is no label.
 */
export function speakerLabel(
  label: string,
  speakers: readonly string[],
  speakerNumber: (n: number) => string,
): string {
  const key = speakerKey(label);
  if (!key) return "";
  if (!NUMBERED_LABEL.test(key)) return key;
  const index = speakers.indexOf(key);
  return speakerNumber(index >= 0 ? index + 1 : Number(key.slice(1)) + 1);
}

/** Display name for a speaker label in the active locale, using the order the page provides. */
export function useSpeakerName(): (label: string) => string {
  const { t } = useI18n();
  const speakers = useContext(SpeakerOrderContext);
  return useCallback(
    (label: string) => speakerLabel(label, speakers, t.transcript.speakerNumber),
    [speakers, t],
  );
}
