import { useEffect, useState } from "react";
import { parseColor, sameRgb, type RGB } from "@/lib/color";

/** The ink (--foreground) and the tertiary grey (--ink-3) of the current theme, for canvas drawing. */
export interface InkPalette {
  ink: RGB;
  ink3: RGB;
}

// Used only if a variable cannot be read; these match the dark theme.
const FALLBACK: InkPalette = { ink: { r: 245, g: 245, b: 245 }, ink3: { r: 115, g: 115, b: 115 } };

function readPalette(): InkPalette {
  const style = getComputedStyle(document.documentElement);
  return {
    ink: parseColor(style.getPropertyValue("--foreground")) ?? FALLBACK.ink,
    ink3: parseColor(style.getPropertyValue("--ink-3")) ?? FALLBACK.ink3,
  };
}

function same(a: InkPalette, b: InkPalette): boolean {
  return sameRgb(a.ink, b.ink) && sameRgb(a.ink3, b.ink3);
}

/** Follows the theme: re-reads the variables whenever the class or data-theme on <html> changes. */
export function useInkPalette(): InkPalette {
  const [palette, setPalette] = useState<InkPalette>(readPalette);
  useEffect(() => {
    const refresh = () => setPalette((prev) => {
      const next = readPalette();
      return same(prev, next) ? prev : next;
    });
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme", "data-palette"] });
    return () => observer.disconnect();
  }, []);
  return palette;
}
