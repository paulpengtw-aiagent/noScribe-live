import { createContext } from "react";
import type { Locale } from "./core";

export type LocaleContextValue = { locale: Locale; setLocale: (locale: Locale) => void };

export const LocaleContext = createContext<LocaleContextValue | null>(null);
