import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { LocaleContext } from "./context";
import { detectLocale, HTML_LANG, LOCALE_KEY, type Locale } from "./core";

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectLocale);

  useEffect(() => {
    document.documentElement.lang = HTML_LANG[locale];
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    try {
      window.localStorage.setItem(LOCALE_KEY, next);
    } catch {
      // Storage unavailable: the choice still applies for this page view.
    }
    setLocaleState(next);
  }, []);

  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}
