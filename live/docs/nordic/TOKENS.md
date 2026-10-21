# Nordic theme: colour tokens

Source palette: Nord (MIT). Tokens live in `live/web/src/index.css` (`:root, [data-theme="light"]` for light, `.dark, [data-theme="dark"]` for dark). Speaker colours live in `live/web/src/lib/speakers.ts`.

Ratios are WCAG 2.x relative-luminance contrast. Text tokens must reach 4.5:1 on every listed surface. Non-text tokens (rings, status dots, speaker colours) must reach 3:1.

## Surfaces

- Dark: page `#2E3440`, card `#3B4252`, raised chip `#434C5E`.
- Light: page `#E5E9F0`, card `#ECEFF4`, muted fill `#D8DEE9`.

## Text tokens

| Token | Dark hex | Dark ratio (worst surface) | Light hex | Light ratio (worst surface) | Use |
|---|---|---|---|---|---|
| `--foreground` | `#ECEFF4` | 7.49:1 (bg/card/raised) | `#2E3440` | 9.25:1 (bg/card/muted) | body text |
| `--muted-foreground` | `#B4BFCF` | 4.64:1 (bg/card/raised) | `#434C5E` | 6.39:1 (bg/card/muted) | muted text |
| `--ink-2` | `#D8DEE9` | 6.39:1 (bg/card/raised) | `#434C5E` | 6.39:1 (bg/card/muted) | secondary text |
| `--ink-3` | `#B4BFCF` | 4.64:1 (bg/card/raised) | `#586274` | 4.55:1 (bg/card/muted) | tertiary text |
| `--primary` (text, links) | `#88C0D0` | 5.03:1 (bg/card) | `#486488` | 4.99:1 (bg/card) | accent text |
| `--destructive` | `#D89FA4` | 4.51:1 (bg/card) | `#984A52` | 5.02:1 (bg/card) | error text |
| `--status-live-ink` | `#ABC496` | 4.55:1 (bg/card/raised) | `#4D683F` | 4.62:1 (bg/card/muted) | live text |
| `--status-failed-ink` | `#DFB0B5` | 4.53:1 (bg/card/raised) | `#984A52` | 4.52:1 (bg/card/muted) | failed text |
| `--status-stopped-ink` | `#EBCB8B` | 5.52:1 (bg/card/raised) | `#865541` | 4.59:1 (bg/card/muted) | stopped text |
| `--status-finished-ink` | `#A0D2DE` | 5.25:1 (bg/card/raised) | `#486488` | 4.50:1 (bg/card/muted) | finished text |

Foreground on fills:

- `--primary-foreground` on `--primary`: dark `#2E3440` on `#88C0D0` = 6.24:1; light `#FFFFFF` on `#486488` = 6.08:1.
- `--secondary-foreground` / `--accent-foreground`: dark `#ECEFF4` on `#434C5E` = 7.49:1; light `#2E3440` on `#D8DEE9` = 9.25:1.

## Non-text tokens (3:1 target)

| Token | Dark hex | Dark ratio (worst surface) | Light hex | Light ratio (worst surface) | Use |
|---|---|---|---|---|---|
| `--ring` (focus) | `#88C0D0` | 6.24:1 (bg) | `#5E81AC` | 3.31:1 (bg) | focus ring, 3:1 |
| `--status-live` dot | `#A3BE8C` | 4.23:1 (raised) | `#4D683F` | 5.12:1 (bg) | live dot |
| `--status-failed` dot | `#D98A91` | 3.28:1 (raised) | `#984A52` | 5.02:1 (bg) | failed dot (dark: lighter Aurora red, see notes) |
| `--status-stopped` dot | `#D08770` | 3.03:1 (raised) | `#865541` | 5.09:1 (bg) | stopped dot |
| `--status-finished` dot | `#88C0D0` | 4.31:1 (raised) | `#486488` | 4.99:1 (bg) | finished dot |

## Speaker colours (3:1 target)

| Slot | Dark hex | Ratio vs dark card `#3B4252` | Light hex | Ratio vs light card and page (worst) |
|---|---|---|---|---|
| 1 | `#88C0D0` | 5.03:1 | `#5D8598` | 3.27:1 |
| 2 | `#EBCB8B` | 6.44:1 | `#897F68` | 3.25:1 |
| 3 | `#A3BE8C` | 4.94:1 | `#6F866F` | 3.24:1 |
| 4 | `#B48EAD` | 3.55:1 | `#927895` | 3.23:1 |
| 5 | `#81A1C1` | 3.74:1 | `#6883A1` | 3.22:1 |
| 6 | `#D08770` | 3.54:1 | `#AA7366` | 3.22:1 |
| unknown | `#9AA5B6` | 4.04:1 | `#6B778C` | 3.71:1 |

## Notes

- Glass cards (`.live-card`) are translucent: 78% of the card colour in dark, 80% in light, with a 14 px backdrop blur. Text is checked against the opaque card colour, not against the blurred aurora behind it.
- The aurora (opacity 0.25 dark, 0.18 light) sits behind page text in the top 40vh. It is not part of the ratios above.
- Changed (Nordic round): the dark failed dot is `#D98A91`, a lighter Aurora red, not `#BF616A`. `#BF616A` read 2.11:1 on the raised chip and 2.46:1 on the card, below the 3:1 target. `#D98A91` reads 3.28:1 on the raised chip and 3.83:1 on the card. The light dot and both dark and light `-ink` text tokens are unchanged.
- Known gap: the dark stopped dot `#D08770` reads 3.03:1 on the raised chip (just above the 3:1 non-text target, with no margin).
- Adopted: `top-bar.tsx` and `run-picker.tsx` use the status utilities (`bg-status-*` for dots, `text-status-*-ink` for text). No palette classes (`-red-`, `-emerald-`, `-amber-` and the like) remain in `live/web/src`. `header-menu.tsx`, `stage-card.tsx` and `conn-banner.tsx` had none.
- Motion: the card entrance is the `.live-card` CSS keyframe only. The run-switch cross-fade is `.run-fade` (opacity, 200 ms). Both are off under reduced motion and Easy view, and no animation touches height, width or top.
