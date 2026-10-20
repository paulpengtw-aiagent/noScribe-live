import { useContext } from "react";
import { catalog } from "./catalog";
import { LocaleContext } from "./context";

export function useI18n() {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useI18n() must be used inside <LocaleProvider>");
  return { locale: ctx.locale, setLocale: ctx.setLocale, t: catalog[ctx.locale] };
}
