import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/** localStorage key for the easy-view choice: "1" when on, "0" when off. */
export const EASY_KEY = "noscribe-live-easy";

export type EasyView = { easy: boolean; setEasy: (value: boolean) => void };

function readStoredEasy(): boolean {
  try {
    return localStorage.getItem(EASY_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * The shared value. The provider in main.tsx holds the state; components read it with useEasyView().
 * Without a provider the value is easy view off, and the setter does nothing.
 */
export const EasyViewContext = createContext<EasyView>({ easy: false, setEasy: () => {} });

/**
 * Holds the easy-view flag for the provider. The flag is remembered in localStorage, and while it is on
 * <html> carries data-easy="true" (the scope of src/easy.css). Off removes the attribute.
 */
export function useEasyViewState(): EasyView {
  const [easy, setEasyState] = useState<boolean>(readStoredEasy);

  useEffect(() => {
    const el = document.documentElement;
    if (easy) el.dataset.easy = "true";
    else delete el.dataset.easy;
    try {
      localStorage.setItem(EASY_KEY, easy ? "1" : "0");
    } catch {
      // Storage can be unavailable; the choice still applies for this page view.
    }
  }, [easy]);

  const setEasy = useCallback((value: boolean) => setEasyState(value), []);
  return useMemo(() => ({ easy, setEasy }), [easy, setEasy]);
}

/** The shared easy-view flag and its setter: `{ easy, setEasy(v) }`. */
export function useEasyView(): EasyView {
  return useContext(EasyViewContext);
}
