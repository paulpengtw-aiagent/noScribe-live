import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

export type Theme = "dark" | "light";
/** Colour family: Nordic (the original) or Crimson. Light and dark apply to both. */
export type Palette = "nordic" | "crimson";

const STORAGE_KEY = "noscribe-live-theme";
const PALETTE_KEY = "noscribe-live-palette";

function readStoredTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

/** Dark is the default. The class and data-theme on <html> are kept in sync. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    const el = document.documentElement;
    el.classList.toggle("dark", theme === "dark");
    el.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Storage can be unavailable; the toggle still works for this page.
    }
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, toggle };
}

function readStoredPalette(): Palette {
  try {
    return localStorage.getItem(PALETTE_KEY) === "crimson" ? "crimson" : "nordic";
  } catch {
    return "nordic";
  }
}

// One palette per page: every usePalette() caller reads the same value, so the header and the menu agree.
let currentPalette: Palette = readStoredPalette();
const paletteListeners = new Set<() => void>();

function subscribePalette(onChange: () => void) {
  paletteListeners.add(onChange);
  return () => {
    paletteListeners.delete(onChange);
  };
}

/** Sets <html data-palette> (the CSS keys off it), remembers the choice, and tells the subscribers. */
function setPalette(next: Palette) {
  if (next === currentPalette) return;
  currentPalette = next;
  document.documentElement.dataset.palette = next;
  try {
    localStorage.setItem(PALETTE_KEY, next);
  } catch {
    // Storage can be unavailable; the choice still holds for this page.
  }
  paletteListeners.forEach((listener) => listener());
}

/** The colour family. index.html applies the stored choice before first paint, so this only changes on a pick. */
export function usePalette() {
  const palette = useSyncExternalStore(
    subscribePalette,
    () => currentPalette,
    () => "nordic" as Palette,
  );
  return { palette, setPalette };
}
