# Nordic theme: colour tokens

Source palette: Nord (MIT). Tokens live in `live/web/src/index.css` (`:root, [data-theme="light"]` for light, `.dark, [data-theme="dark"]` for dark). Speaker colours live in `live/web/src/lib/speakers.ts`. The canvas orb's Frost ink gradient lives in `live/web/src/lib/orb-renderer.ts`.

Ratios are WCAG 2.x relative-luminance contrast, computed from the hex values in the files (script: `/tmp/nordic_contrast.py`, `/tmp/nordic_final.py`, not kept in the repo). Text tokens must reach 4.5:1 on every listed surface. Non-text tokens (rings, status dots, speaker colours, timeline edges) must reach 3:1.

## Surfaces

Glass cards are translucent, so ratios are checked against the opaque colour a card composites to over the page (aurora not included).

- Dark: page `#242933` (was `#2E3440`). Glass card `rgba(67, 76, 94, 0.62)` over the page composites to `#373F4E`. Raised chip `#434C5E` (opaque). Opaque `--card` stays `#3B4252`.
- Light: page `#E5E9F0`. Glass card `rgba(236, 239, 244, 0.82)` over the page composites to `#EBEEF3`. Muted fill `#D8DEE9`.
- Card vs page separation: dark 1.38:1. Light 1.05:1. On light the card separates by its white sheen, the Frost hairline and the soft shadow, not by fill contrast. Open question for the boss: darken the light page if the cards need more separation.

## Text tokens

Dark values were computed on the old surfaces. The new page and card are darker, so ratios only rise. Light values were rechecked on the composite card `#EBEEF3`: each is at least 4.5:1, with the old worst case on the muted fill.

| Token | Dark hex | Dark ratio (worst surface) | Light hex | Light ratio (worst surface) | Use |
|---|---|---|---|---|---|
| `--foreground` | `#ECEFF4` | 7.49:1 (bg/card/raised) | `#2E3440` | 9.25:1 (bg/card/muted) | body text |
| `--muted-foreground` | `#B4BFCF` | 4.64:1 (bg/card/raised) | `#434C5E` | 6.39:1 (bg/card/muted) | muted text |
| `--ink-2` | `#D8DEE9` | 6.39:1 (bg/card/raised) | `#434C5E` | 6.39:1 (bg/card/muted) | secondary text |
| `--ink-3` | `#B4BFCF` | 4.64:1 (bg/card/raised) | `#586274` | 4.55:1 (bg/card/muted) | tertiary text |
| `--primary` (text, links) | `#88C0D0` | 5.03:1 (bg/card) | `#486488` | 4.99:1 (bg/card) | accent text |
| `--destructive` | `#D89FA4` | 4.51:1 (bg/card) | `#984A52` | 5.02:1 (bg/card) | error text |
| `--status-live-ink` | `#ABC496` | 4.55:1 (raised) / 5.58:1 (card) | `#4D683F` | 4.62:1 (muted) / 5.36:1 (card) | live text |
| `--status-loading-ink` (new) | `#EBCB8B` | 5.52:1 (raised) / 6.78:1 (card) | `#7A5C00` | 4.63:1 (muted) / 5.38:1 (card) | loading text |
| `--status-failed-ink` | `#F4AAB0` | 4.61:1 (raised) / 5.66:1 (card) | `#8E3340` | 5.76:1 (muted) / 6.69:1 (card) | failed text |
| `--status-stopped-ink` | `#F5B9A0` | 5.07:1 (raised) / 6.22:1 (card) | `#A0481F` | 4.52:1 (muted) / 5.25:1 (card) | stopped text |
| `--status-finished-ink` | `#A0D2DE` | 5.25:1 (raised) | `#486488` | 4.50:1 (muted) | finished text |
| `--time-ink` (timestamps) | `#88C0D0` | 5.29:1 (card) / 4.31:1 (raised) | `#4C6E94` | 4.55:1 (card) / 4.35:1 (page) | run timestamps |

Timestamps: `[data-testid="paragraph-time"]` sets `color: var(--time-ink)`. They sit on the card, so the card figure applies. On the light muted fill the ratio is 3.92:1, below 4.5:1, so timestamps must not sit on the muted fill.

Foreground on fills:

- `--primary-foreground` on `--primary`: dark `#2E3440` on `#88C0D0` = 6.24:1. Light `#FFFFFF` on `#486488` = 6.08:1.
- `--secondary-foreground` / `--accent-foreground`: dark `#ECEFF4` on `#434C5E` = 7.49:1. Light `#2E3440` on `#D8DEE9` = 9.25:1.

## Status (non-text dots: 3:1; text inks: 4.5:1)

Dots and inks differ in hue and lightness between failed and stopped. Dark dots: failed `#E8808A` (rose) against stopped `#EBA07F` (peach), dE76 24.2, relative luminance 0.344 vs 0.443. Light dots: failed `#8E3340` against stopped `#A0481F`, dE76 29.1.

| Token | Dark hex | Dark ratio (worst surface) | Light hex | Light ratio (worst surface) | Use |
|---|---|---|---|---|---|
| `--status-live` dot | `#A3BE8C` | 4.23:1 (raised) | `#4D683F` | 4.62:1 (muted) | live dot |
| `--status-loading` dot (new) | `#EBCB8B` | 5.52:1 (raised) | `#8A6A00` | 3.75:1 (muted) / 4.36:1 (card) | loading dot |
| `--status-failed` dot | `#E8808A` | 3.24:1 (raised) / 3.98:1 (card) | `#8E3340` | 5.76:1 (muted) | failed dot |
| `--status-stopped` dot | `#EBA07F` | 4.05:1 (raised) / 4.97:1 (card) | `#A0481F` | 4.52:1 (muted) | stopped dot |
| `--status-finished` dot | `#88C0D0` | 4.31:1 (raised) | `#486488` | 4.99:1 (bg/card) | finished dot |

Notes:
- The old dark failed dot `#D98A91` read 16.2 dE from the old stopped `#D08770`. The new pair reads 24.2.
- The old dark stopped dot `#D08770` read 3.03:1 on the raised chip, just above target. `#EBA07F` reads 4.05:1.
- `--status-loading` has no yellow-on-light use: the light dot and ink are a deep ochre, since `#EBCB8B` on light would fail 3:1.

## Non-text tokens (3:1 target)

| Token | Dark hex | Dark ratio (worst surface) | Light hex | Light ratio (worst surface) | Use |
|---|---|---|---|---|---|
| `--ring` (focus) | `#88C0D0` | 6.24:1 (bg) | `#5E81AC` | 3.31:1 (bg) | focus ring, 3:1 |
| Timeline block edge | none | n/a | `#4C6E94` | 4.55:1 (card) / 4.35:1 (page) | `.timeline-block[data-timeline-index]` edge |

Light timeline blocks use the pale Frost and Aurora fills with no darkening filter (`--timeline-block-filter: none`, was `brightness(0.6)`, which made them brown). The Frost-deep edge is what carries the 3:1 non-text contrast.

## Speaker colours (3:1 target)

| Slot | Dark hex | Ratio vs dark card (`#3B4252`) | Light hex | Ratio vs light card / page |
|---|---|---|---|---|
| 1 | `#88C0D0` | 5.03:1 | `#4A7F96` | 3.79:1 / 3.62:1 |
| 2 | `#EBCB8B` | 6.44:1 | `#A67C00` | 3.28:1 / 3.13:1 |
| 3 | `#A3BE8C` | 4.94:1 | `#5B7F45` | 3.95:1 / 3.78:1 |
| 4 | `#B48EAD` | 3.55:1 | `#7E5A86` | 4.89:1 / 4.67:1 |
| 5 | `#81A1C1` | 3.74:1 | `#5E81AC` | 3.46:1 / 3.31:1 |
| 6 | `#D08770` | 3.54:1 | `#A4532B` | 4.69:1 / 4.48:1 |
| unknown | `#9AA5B6` | 4.04:1 | `#6B778C` | 3.71:1 (card) |

The light palette is deeper than the pale hues so each slot reaches 3:1 against the light card. Dark palette values are unchanged. `speakerColor` still returns the dark palette on both themes, which is why light timeline blocks rely on the edge above.

## Aurora, glass and motion

- Aurora: a full-width layer, top 0 to 70vh, masked to fade out from 35% of its height to transparent at the bottom, so it has no hard edge. Four blurred radial blobs: teal `#8FBCBB`, green `#A3BE8C`, purple `#B48EAD`, Frost `#88C0D0`. Drift 44 to 58 s on transform only. Opacity 0.40 dark, 0.26 light. Static under `prefers-reduced-motion` and `html[data-easy="true"]`, and paused when the tab is hidden.
- Glass card: dark `rgba(67,76,94,.62)`, 16 px blur, saturate 1.3, Frost hairline `rgba(136,192,208,.28)`, inner highlight `inset 0 1px 0 rgba(236,239,244,.08)`, soft shadow `0 10px 30px -12px rgba(8,10,16,.6)`. Light `rgba(236,239,244,.82)` with a white sheen and a faint Frost tint, Frost hairline `rgba(94,129,172,.22)`, shadow `0 8px 30px rgba(46,52,64,.08)`.
- Progress fill: Frost gradient `#8FBCBB, #88C0D0, #81A1C1`, sized to the visible value (`progress.tsx` sets `background-size` and `background-position`). A sheen crosses on transform. Off under reduced motion and Easy view.
- Speaker dot glow: `[data-speaker-dot][data-streaming="true"]` gets `box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 25%, transparent), 0 0 12px currentColor`. The glow takes `currentColor`, so the dot must also set `color` to its speaker colour.
- Orb: dark ink dots take the Frost gradient `#8FBCBB, #88C0D0, #81A1C1, #5E81AC` across the orb (card contrast 5.08, 5.29, 3.93, 2.63; the dim back dots fade by alpha). Light: `#81A1C1, #5E81AC, #486488`. Applied only when the orb ink is a light colour, so the light theme gets the deeper run.

## Notes

- `--aurora-*` names: `--aurora-1` teal, `--aurora-2` green, `--aurora-3` purple, `--aurora-4` Frost. The old `--aurora-1` frost value was replaced.
- Adopted earlier: `top-bar.tsx` and `run-picker.tsx` use the status utilities (`bg-status-*` for dots, `text-status-*-ink` for text). `--color-status-loading` and `--color-status-loading-ink` are now mapped in the `@theme inline` block.
- Motion: no animation touches height, width or top. The card entrance is the `.live-card` keyframe. The run-switch fade is `.run-fade` (opacity). The progress sheen and aurora drift are transform only.
