import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";

/** Compact English / Traditional Chinese switch. The visible label names the language it switches to. */
export function LocaleToggle() {
  const { locale, setLocale, t } = useI18n();
  const target = locale === "en" ? "zh-TW" : "en";
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      data-testid="locale-toggle"
      aria-label={t.topbar.switchLanguage}
      onClick={() => setLocale(target)}
      className="h-9 shrink-0 rounded-full px-3 font-medium shadow-ring hover:bg-raised dark:hover:bg-raised"
    >
      {t.topbar.languageShort}
    </Button>
  );
}

/** The same switch as a row in the compact header menu. `onDone` runs after the switch, to close the menu. */
export function LocaleMenuItem({ onDone }: { onDone?: () => void }) {
  const { locale, setLocale, t } = useI18n();
  const target = locale === "en" ? "zh-TW" : "en";
  return (
    <button
      type="button"
      data-testid="locale-toggle"
      className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-[14px] hover:bg-raised"
      onClick={() => {
        setLocale(target);
        onDone?.();
      }}
    >
      <span aria-hidden="true" className="w-5 shrink-0 text-center font-medium">
        {t.topbar.languageShort}
      </span>
      <span className="min-w-0 truncate">{t.topbar.switchLanguage}</span>
    </button>
  );
}
