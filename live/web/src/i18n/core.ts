// Non-component parts of the i18n layer: the locale type, the storage key, detection, and the plural and
// clock helpers. index.tsx re-exports them, so app code imports everything from "@/i18n".

export type Locale = "en" | "zh-TW";

export const LOCALE_KEY = "noscribe-live-locale";

export const HTML_LANG: Record<Locale, string> = { en: "en", "zh-TW": "zh-Hant-TW" };

/** Saved choice wins; else the first browser language (any "zh*" means Traditional Chinese); else English. */
export function detectLocale(): Locale {
  try {
    const saved = window.localStorage.getItem(LOCALE_KEY);
    if (saved === "en" || saved === "zh-TW") return saved;
  } catch {
    // Storage can be unavailable (privacy mode); fall through to the browser preference.
  }
  const first = navigator.languages?.[0] ?? navigator.language ?? "";
  return first.toLowerCase().startsWith("zh") ? "zh-TW" : "en";
}

/** Selects the CLDR plural form of n for the locale. zh always selects "other". */
export function plural(locale: Locale, n: number, forms: { one: string; other: string }): string {
  return new Intl.PluralRules(locale).select(n) === "one" ? forms.one : forms.other;
}

const clockFormats = new Map<Locale, Intl.DateTimeFormat>();

/** hh:mm:ss on a 24-hour clock, in the viewer's time zone. */
export function formatClock(epochSeconds: number, locale: Locale): string {
  let fmt = clockFormats.get(locale);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(locale, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    clockFormats.set(locale, fmt);
  }
  return fmt.format(new Date(epochSeconds * 1000));
}
