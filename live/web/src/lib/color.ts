// Colour helpers for the canvas code. Colours arrive as CSS strings (palette hex, or the value of a
// CSS variable), so they are parsed once and turned back into strings when a style is set.

export interface RGB {
  r: number;
  g: number;
  b: number;
}

/** Reads #rgb, #rrggbb, rgb() and rgba(). Anything else gives null. */
export function parseColor(value: string): RGB | null {
  const v = value.trim();
  if (v.startsWith("#")) {
    const hex = v.slice(1);
    if (/^[0-9a-f]{3}$/i.test(hex)) {
      return { r: parseInt(hex[0] + hex[0], 16), g: parseInt(hex[1] + hex[1], 16), b: parseInt(hex[2] + hex[2], 16) };
    }
    if (/^[0-9a-f]{6}$/i.test(hex)) {
      return { r: parseInt(hex.slice(0, 2), 16), g: parseInt(hex.slice(2, 4), 16), b: parseInt(hex.slice(4, 6), 16) };
    }
    return null;
  }
  const match = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(v);
  return match ? { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]) } : null;
}

/** Linear blend: t = 0 gives a, t = 1 gives b. */
export function mixColor(a: RGB, b: RGB, t: number): RGB {
  return { r: a.r + (b.r - a.r) * t, g: a.g + (b.g - a.g) * t, b: a.b + (b.b - a.b) * t };
}

export function sameRgb(a: RGB, b: RGB): boolean {
  return a.r === b.r && a.g === b.g && a.b === b.b;
}

export function rgbCss(c: RGB): string {
  return `rgb(${Math.round(c.r)}, ${Math.round(c.g)}, ${Math.round(c.b)})`;
}

export function rgbaCss(c: RGB, alpha: number): string {
  return `rgba(${Math.round(c.r)}, ${Math.round(c.g)}, ${Math.round(c.b)}, ${alpha})`;
}
