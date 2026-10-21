// Barrel for the i18n layer; app code imports from "@/i18n".
// Adding a UI string: add the key to the "en" object of src/i18n/catalog/<area>.ts.
// Its "zh-TW" object is typed as the en shape, so tsc fails until the translation exists.
// Read it in components as t.<area>.<key> (from useI18n()); never hard-code visible text.
// A value is a string or (args) => string. For plurals use plural(locale, n, { one, other }).
// Chinese has no plural forms: plural() returns "other" for zh-TW, so put that text in "other".
// Clock times come from formatClock(epochSeconds, locale), not from catalog strings.
// Components, the hook, and the non-component helpers live in their own files so that
// react-refresh's only-export-components rule has nothing to flag.

export { LocaleProvider } from "./provider";
export { useI18n } from "./use-i18n";
export { detectLocale, formatClock, LOCALE_KEY, plural } from "./core";
export type { Locale } from "./core";
export type { Messages } from "./catalog";
