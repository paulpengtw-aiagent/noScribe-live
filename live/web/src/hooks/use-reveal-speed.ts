import { useCallback, useSyncExternalStore } from "react";
import { clampCustomCps, DEFAULT_CUSTOM_CPS, REVEAL_MODES, type RevealMode } from "@/lib/reveal-rate";

/** localStorage key for the reveal speed: JSON {"mode": ..., "cps": ...}. */
export const REVEAL_KEY = "noscribe-live-reveal";

export interface RevealSpeed {
  mode: RevealMode;
  /** The custom slider's graphemes per second. The other modes ignore it. */
  cps: number;
}

export interface RevealSpeedControls extends RevealSpeed {
  setMode: (mode: RevealMode) => void;
  /** Sets the custom rate and switches to the custom mode. */
  setCps: (cps: number) => void;
}

const DEFAULT_SPEED: RevealSpeed = { mode: "continuous", cps: DEFAULT_CUSTOM_CPS };

function parseSpeed(raw: string | null): RevealSpeed {
  if (raw === null) return DEFAULT_SPEED;
  try {
    const value = JSON.parse(raw) as { mode?: unknown; cps?: unknown };
    const mode = REVEAL_MODES.find((item) => item === value.mode) ?? DEFAULT_SPEED.mode;
    return { mode, cps: clampCustomCps(Number(value.cps)) };
  } catch {
    return DEFAULT_SPEED;
  }
}

// One shared value for every component, so the control and the transcript card always agree.
let current: RevealSpeed | null = null;
const listeners = new Set<() => void>();

function read(): RevealSpeed {
  if (current === null) {
    try {
      current = parseSpeed(localStorage.getItem(REVEAL_KEY));
    } catch {
      current = DEFAULT_SPEED;
    }
  }
  return current;
}

function write(next: RevealSpeed) {
  current = next;
  try {
    localStorage.setItem(REVEAL_KEY, JSON.stringify(next));
  } catch {
    // Storage can be unavailable; the choice still applies for this page view.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The reveal speed: the mode, the custom rate, and their setters. Remembered in localStorage. */
export function useRevealSpeed(): RevealSpeedControls {
  const speed = useSyncExternalStore(subscribe, read, () => DEFAULT_SPEED);
  const setMode = useCallback((mode: RevealMode) => write({ ...read(), mode }), []);
  const setCps = useCallback((cps: number) => write({ mode: "custom", cps: clampCustomCps(cps) }), []);
  return { mode: speed.mode, cps: speed.cps, setMode, setCps };
}
