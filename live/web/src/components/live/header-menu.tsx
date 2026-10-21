import { useState } from "react";
import { Check, Moon, Settings, Sun } from "lucide-react";
import { LocaleMenuItem } from "@/components/live/locale-toggle";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { type Palette, type Theme, usePalette } from "@/hooks/use-theme";
import { useI18n } from "@/i18n";

const PALETTES: Palette[] = ["nordic", "crimson"];
const THEMES: Theme[] = ["light", "dark"];
/** Swatch per palette: the family's primary red or blue, so the two rows read as two families. */
const SWATCH: Record<Palette, string> = { nordic: "#5e81ac", crimson: "#93272c" };
const ROW = "flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-[14px] hover:bg-raised";
const HEADING = "px-3 pt-1.5 pb-1 text-[12px] text-ink-2";

/** Palette choice (Nordic, Crimson). The chosen one is pressed and ticked. */
function PaletteRows() {
  const { t } = useI18n();
  const { palette, setPalette } = usePalette();
  return (
    <div role="group" aria-label={t.topbar.paletteLabel}>
      <p className={HEADING}>{t.topbar.paletteLabel}</p>
      {PALETTES.map((p) => (
        <button
          key={p}
          type="button"
          data-testid={`palette-${p}`}
          aria-pressed={palette === p}
          className={ROW}
          onClick={() => setPalette(p)}
        >
          <span aria-hidden="true" className="size-3 shrink-0 rounded-full" style={{ backgroundColor: SWATCH[p] }} />
          <span className="min-w-0 flex-1 truncate">{t.topbar.palette[p]}</span>
          {palette === p && <Check aria-hidden="true" className="size-4 shrink-0" />}
        </button>
      ))}
    </div>
  );
}

/** Light and dark choice. Picks the other value through onToggleTheme, so the page keeps one theme state. */
function ThemeRows({ theme, onToggleTheme }: { theme: Theme; onToggleTheme: () => void }) {
  const { t } = useI18n();
  return (
    <div role="group" aria-label={t.topbar.themeLabel}>
      <p className={HEADING}>{t.topbar.themeLabel}</p>
      {THEMES.map((th) => (
        <button
          key={th}
          type="button"
          data-testid={`theme-${th}`}
          aria-pressed={theme === th}
          className={ROW}
          onClick={() => {
            if (theme !== th) onToggleTheme();
          }}
        >
          <span aria-hidden="true" className="flex w-5 shrink-0 justify-center">
            {th === "dark" ? <Moon className="size-4" /> : <Sun className="size-4" />}
          </span>
          <span className="min-w-0 flex-1 truncate">{t.topbar.themeChoice[th]}</span>
          {theme === th && <Check aria-hidden="true" className="size-4 shrink-0" />}
        </button>
      ))}
    </div>
  );
}

export interface ThemeMenuProps {
  theme: Theme;
  onToggleTheme: () => void;
}

/** Desktop header: the theme button opens a menu with the palette and the light or dark choice. */
export function ThemeMenu({ theme, onToggleTheme }: ThemeMenuProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          data-testid="theme-menu"
          aria-label={t.topbar.themeMenuLabel}
          className="shrink-0 rounded-full shadow-ring hover:bg-raised dark:hover:bg-raised"
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="w-[min(88vw,240px)] rounded-[14px] p-1.5">
        <PaletteRows />
        <ThemeRows theme={theme} onToggleTheme={onToggleTheme} />
      </PopoverContent>
    </Popover>
  );
}

export interface HeaderMenuProps {
  theme: Theme;
  onToggleTheme: () => void;
}

/** Compact header only (below sm): the palette, the theme and the language, in one icon menu. Easy view has its own header button. */
export function HeaderMenu({ theme, onToggleTheme }: HeaderMenuProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const done = () => setOpen(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          data-testid="header-menu"
          aria-label={t.topbar.menuLabel}
          className="size-9 shrink-0 rounded-full shadow-ring hover:bg-raised dark:hover:bg-raised"
        >
          <Settings />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="w-[min(88vw,240px)] rounded-[14px] p-1.5">
        <PaletteRows />
        <ThemeRows theme={theme} onToggleTheme={onToggleTheme} />
        <div aria-hidden="true" className="my-1 border-t border-hairline" />
        <LocaleMenuItem onDone={done} />
      </PopoverContent>
    </Popover>
  );
}
