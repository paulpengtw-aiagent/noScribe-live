import { createContext, useCallback, useContext } from "react";
import { speakerDisplayName } from "@/lib/speakers";

/** Speakers in order of first appearance. The page provides it once, so every view numbers speakers alike. */
export const SpeakerOrderContext = createContext<readonly string[]>([]);

/** Display name for a speaker label, using the order the page provides. */
export function useSpeakerName(): (label: string) => string {
  const speakers = useContext(SpeakerOrderContext);
  return useCallback((label: string) => speakerDisplayName(label, speakers), [speakers]);
}
