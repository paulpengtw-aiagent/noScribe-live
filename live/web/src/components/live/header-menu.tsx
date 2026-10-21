import { useState } from "react";
import { Moon, Settings, Sun } from "lucide-react";
import { EasyMenuItem } from "@/components/live/easy-toggle";
import { LocaleMenuItem } from "@/components/live/locale-toggle";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Theme } from "@/hooks/use-theme";
import { useI18n } from "@/i18n";

export interface HeaderMenuProps {
  theme: Theme;
  onToggleTheme: () => void;
}

/** Compact header only (below sm): the theme and language switches, in one icon menu. */
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
        <button
          type="button"
          className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-[14px] hover:bg-raised"
          onClick={() => {
            onToggleTheme();
            done();
          }}
        >
          <span aria-hidden="true" className="flex w-5 shrink-0 justify-center">
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </span>
          <span className="min-w-0 truncate">
            {theme === "dark" ? t.topbar.switchTheme.light : t.topbar.switchTheme.dark}
          </span>
        </button>
        <EasyMenuItem onDone={done} />
        <LocaleMenuItem onDone={done} />
      </PopoverContent>
    </Popover>
  );
}
