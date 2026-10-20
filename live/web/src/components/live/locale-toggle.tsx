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
