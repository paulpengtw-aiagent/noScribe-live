# Nordic theme: colour tokens

Source palette: Nord (MIT). Tokens live in `live/web/src/index.css` (`:root, [data-theme="light"]` for light, `.dark, [data-theme="dark"]` for dark). Speaker colours live in `live/web/src/lib/speakers.ts`. The canvas orb's Frost ink gradient lives in `live/web/src/lib/orb-renderer.ts`.

Ratios are WCAG 2.x relative-luminance contrast, computed from the hex values in the files (script: `/tmp/nordic_contrast.py`, `/tmp/nordic_final.py`, not kept in the repo). Text tokens must reach 4.5:1 on every listed surface. Non-text tokens (rings, status dots, speaker colours, timeline edges) must reach 3:1.

## Surfaces

Glass cards are translucent, so ratios are checked against the opaque colour a card composites to over the page (aurora not included).

- Dark: page `#242933` (was `#2E3440`). Glass card `rgba(67, 76, 94, 0.9)` over the page composites to `#40485A` (round 14; was 0.62, `#373F4E`). Raised chip `#434C5E` (opaque). Opaque `--card` stays `#3B4252`.
- Light: page `#E5E9F0`. Glass card `rgba(236, 239, 244, 0.82)` over the page composites to `#EBEEF3`. Muted fill `#D8DEE9`.
- Card vs page separation: dark 1.60:1 (round 14; was 1.38:1). Light 1.05:1. On light the card separates by its white sheen, the Frost hairline and the soft shadow, not by fill contrast. Open question for the boss: darken the light page if the cards need more separation.

## Text tokens

Dark values were recomputed in round 14 on the current surfaces: page `#242933`, card `#40485A` (fill 0.9), raised chip `#434C5E`. Light values were rechecked on the composite card `#EBEEF3`: each is at least 4.5:1, with the old worst case on the muted fill.

| Token | Dark hex | Dark ratio (worst surface) | Light hex | Light ratio (worst surface) | Use |
|---|---|---|---|---|---|
| `--foreground` | `#ECEFF4` | 7.49:1 (bg/card/raised) | `#2E3440` | 9.25:1 (bg/card/muted) | body text |
| `--muted-foreground` | `#CBD3DE` | 5.72:1 (bg/card/raised) | `#434C5E` | 6.39:1 (bg/card/muted) | muted text |
| `--ink-2` | `#D8DEE9` | 6.39:1 (bg/card/raised) | `#434C5E` | 6.39:1 (bg/card/muted) | secondary text |
| `--ink-3` | `#CBD3DE` | 5.72:1 (bg/card/raised) | `#586274` | 4.55:1 (bg/card/muted) | tertiary text |
| `--primary` (text, links) | `#88C0D0` | 4.56:1 (bg/card) | `#486488` | 4.99:1 (bg/card) | accent text |
| `--destructive` | `#EACBCD` | 6.04:1 (bg/card) | `#984A52` | 5.02:1 (bg/card) | error text |
| `--status-live-ink` | `#C7D8B9` | 5.73:1 (raised) / 6.06:1 (card) | `#4D683F` | 4.62:1 (muted) / 5.36:1 (card) | live text |
| `--status-loading-ink` (new) | `#ECCF93` | 5.72:1 (raised) / 6.04:1 (card) | `#7A5C00` | 4.63:1 (muted) / 5.38:1 (card) | loading text |
| `--status-failed-ink` | `#F8C6CA` | 5.72:1 (raised) / 6.04:1 (card) | `#8E3340` | 5.76:1 (muted) / 6.69:1 (card) | failed text |
| `--status-stopped-ink` | `#F7C8B4` | 5.70:1 (raised) / 6.02:1 (card) | `#A0481F` | 4.52:1 (muted) / 5.25:1 (card) | stopped text |
| `--status-finished-ink` | `#B0D9E3` | 5.70:1 (raised) / 6.02:1 (card) | `#486488` | 4.50:1 (muted) | finished text |
| `--time-ink` (timestamps) | `#B4D8E2` | 6.02:1 (card) / 5.69:1 (raised) | `#4C6E94` | 4.55:1 (card) / 4.35:1 (page) | run timestamps |

Timestamps: `[data-testid="paragraph-time"]` sets `color: var(--time-ink)`. They sit on the card, so the card figure applies. On the light muted fill the ratio is 3.92:1, below 4.5:1, so timestamps must not sit on the muted fill.

Foreground on fills:

- `--primary-foreground` on `--primary`: dark `#2E3440` on `#88C0D0` = 6.24:1. Light `#FFFFFF` on `#486488` = 6.08:1.
- `--secondary-foreground` / `--accent-foreground`: dark `#ECEFF4` on `#434C5E` = 7.49:1. Light `#2E3440` on `#D8DEE9` = 9.25:1.

## Status (non-text dots: 3:1; text inks: 4.5:1)

Dots and inks differ in hue and lightness between failed and stopped. Dark dots: failed `#E8808A` (rose) against stopped `#EBA07F` (peach), dE76 24.2, relative luminance 0.344 vs 0.443. Light dots: failed `#8E3340` against stopped `#A0481F`, dE76 29.1.

| Token | Dark hex | Dark ratio (worst surface) | Light hex | Light ratio (worst surface) | Use |
|---|---|---|---|---|---|
| `--status-live` dot | `#A3BE8C` | 4.23:1 (raised) / 4.47:1 (card) | `#4D683F` | 4.62:1 (muted) | live dot |
| `--status-loading` dot (new) | `#EBCB8B` | 5.52:1 (raised) / 5.84:1 (card) | `#8A6A00` | 3.75:1 (muted) / 4.36:1 (card) | loading dot |
| `--status-failed` dot | `#E8808A` | 3.24:1 (raised) / 3.42:1 (card) | `#8E3340` | 5.76:1 (muted) | failed dot |
| `--status-stopped` dot | `#EBA07F` | 4.05:1 (raised) / 4.28:1 (card) | `#A0481F` | 4.52:1 (muted) | stopped dot |
| `--status-finished` dot | `#88C0D0` | 4.31:1 (raised) / 4.56:1 (card) | `#486488` | 4.99:1 (bg/card) | finished dot |

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

- Aurora: a full-width layer, top 0 to 70vh, masked to fade out from 35% of its height to transparent at the bottom, so it has no hard edge. Four blurred radial blobs, each 80vmax, spread left to right across the header: teal `#8FBCBB`, green `#A3BE8C`, purple `#B48EAD`, Frost `#88C0D0`. Drift 44 to 58 s on transform only. Opacity 0.50 dark (round 14; round 13 was 0.25, before that 0.40), 0.46 light (was 0.26). Static under `prefers-reduced-motion` and `html[data-easy="true"]`, and paused when the tab is hidden.
  - Header text budget, round 13 (no header glass; superseded by Round 14 below). Worst case = one blob at its full stop alpha, composited over the page in sRGB, so the layer opacity is the alpha. Dark (page `#242933`) at 0.25: `--foreground` `#ECEFF4` 7.41 to 8.35:1; `--muted-foreground` `#B4BFCF` 4.59 to 5.18:1 (Frost is the minimum). Two blobs overlapping at their 55% stop (0.14 effective each): muted 4.55 to 4.81:1, foreground 7.35 to 7.76:1. The pre-change 0.40 gave muted 3.30 to 3.97:1, so the old aurora already failed the rule.
  - Light (page `#E5E9F0`) at 0.46: `--foreground` `#2E3440` 7.15 to 8.22:1; `--muted-foreground` `#434C5E` 4.94 to 5.68:1 (purple is the minimum). Two blobs stacked at full alpha, a stricter case: muted 4.61 to 4.98:1.
  - Dark, two blobs stacked at full alpha, a stricter case than the layout reaches: muted about 3.0 to 3.4:1 at 0.26. This is the known limit of the dark theme.
  - Glass cards sit above the aurora and show it through their 90% fill (round 14; was 62%). Round 14 measured card text under the aurora: it is below 4.5:1 even at round 13's 0.25 (see Round 14).
  - Visibility: light's peak alpha rises 1.8x (0.26 to 0.46). Round 13's dark peak fell (0.40 to 0.25) because the text budget capped it; round 14 is 0.50. Each dark blob covers about 1.7x the area (62 to 80 vmax), spread across the header. The dark glow reads wider, not brighter.
- Glass card: dark `rgba(67,76,94,.9)` (round 14; was .62), 16 px blur, saturate 1.3, Frost hairline `rgba(136,192,208,.28)`, inner highlight `inset 0 1px 0 rgba(236,239,244,.08)`, soft shadow `0 10px 30px -12px rgba(8,10,16,.6)`. Light `rgba(236,239,244,.82)` with a white sheen and a faint Frost tint, Frost hairline `rgba(94,129,172,.22)`, shadow `0 8px 30px rgba(46,52,64,.08)`.
- Progress fill: Frost gradient `#8FBCBB, #88C0D0, #81A1C1`, sized to the visible value (`progress.tsx` sets `background-size` and `background-position`). `progress.tsx` takes `live?: boolean` (default false). Only when live does the indicator get `data-live="true"`, and then a translucent white sheen (0.3 alpha) crosses on transform every 2.5 s. Static when not live, under reduced motion and in Easy view.
- Speaker dot glow: `[data-speaker-dot][data-streaming="true"]` gets `box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 25%, transparent), 0 0 12px currentColor`. The glow takes `currentColor`, so the dot must also set `color` to its speaker colour.
- Orb: dark ink dots take the Frost gradient `#8FBCBB, #88C0D0, #5E81AC` across the orb, three stops at 0, 50 and 100%. Against the glass composite `#40485A` (round 14; was `#373F4E`: 5.08, 5.29, 2.63): 4.37, 4.56 and 2.26:1. The far end sits below 3:1, as before, and the dim back dots fade by alpha. Against the raised chip `#434C5E`: 4.14, 4.31 and 2.14:1. A soft Aurora rim light (`#A3BE8C` at 0.6 alpha on the halo's rim band) is drawn once into the cached halo sprite. It adds no per-frame work and about 0.04 to 0.08 effective alpha. Light: `#81A1C1, #5E81AC, #486488`, unchanged. Applied only when the orb ink is a light colour, so the light theme gets the deeper run.

## Round 14: dark aurora 2x, header glass, card check

Dark only. Light is unchanged: its header keeps `color-mix(in oklab, var(--background) 80%, transparent)` and the 24 px blur it had.

Changes:
- `--aurora-opacity` (dark) 0.25 to 0.50, so every blob's visible peak doubles. Blob stops and drift are unchanged.
- Header glass: `--header-fill` dark `rgba(36, 41, 51, 0.6)` (was `bg-background/80`, i.e. 0.8) and `--header-blur` `blur(12px) saturate(1.2)` (was 24 px). Applied by `.header-glass` in `index.css` on the header root in `top-bar.tsx`. The hairline bottom edge is the existing `border-b border-hairline`.

Method. Stdlib script `/tmp/nordic_aurora/contrast.py`, not kept in the repo. Worst case = one blob at its full stop (alpha 1) times the layer opacity, over `#242933`. Overlapping blobs cannot exceed this: the aurora is one group composited at the layer opacity, and the brightest blob bounds any mix. Header = `rgba(36,41,51,a)` over `saturate(1.2)` of that composite. Glass card = 7% white sheen (the card top, the worst point) over `rgba(67,76,94,.62)` over `saturate(1.3)` of that composite. Blur is ignored; it barely changes a smooth peak. The model reproduces round 13's 4.59:1 (muted over Frost, no fill, 0.25). Frost is the worst blob in every case.

Header text (worst over blobs), before to after:
- foreground `#ECEFF4`: 11.47 to 8.27
- muted `#B4BFCF`: 7.11 to 5.13
- ink-2 `#D8DEE9`: 9.78 to 7.06
- primary/time `#88C0D0`: 6.61 to 4.77
- Surface: `#29313B` to `#364854` (Frost). Without the glass at 0.50, muted falls to 2.67:1. Header alpha sensitivity at 0.50: 0.55 gives 4.51:1, 0.60 gives 4.77:1, 0.65 gives 5.04:1 (primary, the worst).

Glass-card text (worst over blobs, all dark text tokens), before to after. The card was not measured under the aurora before this round. These figures are at the 0.62 fill; the fill was raised to 0.90 later in round 14 (see Card fill).
- foreground: 6.24 to 5.14
- ink-2: 5.32 to 4.38
- muted: 3.87 to 3.18
- primary/time: 3.59 to 2.96
- destructive: 3.22 to 2.65
- live-ink: 3.79 to 3.12; loading-ink: 4.60 to 3.79; failed-ink: 3.84 to 3.16; stopped-ink: 4.22 to 3.48; finished-ink: 4.37 to 3.60
- Surface: `#4B5969` to `#536677` (Frost).

Page-level text over the aurora (outside cards and the header): none exists. For reference only: muted 4.59 at 0.25, 2.67 at 0.50 (foreground 4.30). Everything else that sits on the page is opaque or inside a card:
- ConnBanner (`conn-banner.tsx`): `Alert` with `bg-card`/`bg-popover`, opaque `#3B4252`.
- Toasts (sonner): `--normal-bg: var(--popover)`, opaque. `new-run-notice.tsx` uses `toast.custom`; its background was not checked.
- Loading skeleton, RunLoading, RunMissing, the onboarding hint and the transcript placeholder all sit inside `.live-card`, so the card figures cover them.

Easy view: `html[data-easy="true"] .aurora` dims the layer to 0.6x; it is not off. That gives 0.30 here, and the header figures above stay above 4.5:1 at that level.

Card fill, round 14 (dark only). The 0.62 fill could not hold 4.5:1 for the card text, so the fill and the text were changed together.
- `--glass-card` (dark) `rgba(67, 76, 94, 0.62)` to `rgba(67, 76, 94, 0.9)`. Blur, hairline, highlight, shadow and the 7% white sheen are unchanged. Light is unchanged.
- The fill alone cannot reach 4.5:1. The sheen sets a floor: at fill 1.00 the card top is `#4F5768` and muted is still 3.88:1 (worst blob Frost; at 1.00 foreground 6.26, ink-2 5.34, time 3.61, destructive 3.24, live-ink 3.80, loading-ink 4.62, failed-ink 3.86, stopped-ink 4.24, finished-ink 4.39). With no text change, nine tokens fail at 0.62 and eight still fail at 0.90 (muted 3.68, time 3.42, destructive 3.07, live-ink 3.61, loading-ink 4.39, failed-ink 3.66, stopped-ink 4.02, finished-ink 4.16). Foreground (5.94) and ink-2 (5.07) pass at 0.90.
- Fill 0.90 is the ceiling used. Within the ceiling it needs the smallest text change. Lower fills need bigger ones: at 0.75 muted to `#D4DAE3`, time to `#C2DFE7`, destructive to `#EDD4D6`; at 0.62 muted to `#DCE1E8`, time to `#CDE5EB`, destructive to `#F1DCDD`.
- Text tokens, minimal lightness nudge (hue and saturation kept, target 4.52:1 as a 0.02 margin against compositing rounding), at fill 0.90: muted/ink-3 `#B4BFCF` to `#CBD3DE`; time-ink `#88C0D0` to `#B4D8E2`; destructive `#D89FA4` to `#EACBCD`; live-ink `#ABC496` to `#C7D8B9`; loading-ink `#EBCB8B` to `#ECCF93`; failed-ink `#F4AAB0` to `#F8C6CA`; stopped-ink `#F5B9A0` to `#F7C8B4`; finished-ink `#A0D2DE` to `#B0D9E3`. `--primary` stays `#88C0D0`: its only text use is the link button variant, not card text.

Worst case at fill 0.90 (worst blob Frost), token to ratio:

| Token | Worst-case ratio |
|---|---|
| `--foreground` `#ECEFF4` | 5.94 |
| `--muted-foreground` and `--ink-3` `#CBD3DE` | 4.54 |
| `--ink-2` `#D8DEE9` | 5.07 |
| `--time-ink` `#B4D8E2` | 4.52 |
| `--destructive` `#EACBCD` | 4.54 |
| `--status-live-ink` `#C7D8B9` | 4.55 |
| `--status-loading-ink` `#ECCF93` | 4.54 |
| `--status-failed-ink` `#F8C6CA` | 4.54 |
| `--status-stopped-ink` `#F7C8B4` | 4.53 |
| `--status-finished-ink` `#B0D9E3` | 4.53 |

Method: the stdlib model `/tmp/nordic_aurora/contrast.py` with the card fill as a parameter (`/tmp/nordic_aurora/round14.py`, not kept in the repo). Worst case = one blob at its full stop times the layer opacity 0.50 over `#242933`, then the 7% sheen over `rgba(67,76,94,a)` over saturate(1.3). Blur ignored, as before. The lightened inks also clear 4.5:1 on the raised chip (5.69 to 5.73, dark table above).

## Notes

- `--aurora-*` names: `--aurora-1` teal, `--aurora-2` green, `--aurora-3` purple, `--aurora-4` Frost. The old `--aurora-1` frost value was replaced.
- Adopted earlier: `top-bar.tsx` and `run-picker.tsx` use the status utilities (`bg-status-*` for dots, `text-status-*-ink` for text). `--color-status-loading` and `--color-status-loading-ink` are now mapped in the `@theme inline` block.
- Motion: no animation touches height, width or top. The card entrance is the `.live-card` keyframe. The run-switch fade is `.run-fade` (opacity). The progress sheen and aurora drift are transform only.
- Open question for the boss (round 14): the dark card fill is now 0.90 (the aurora shows through about 10% of a card) and eight dark text tokens were lightened to hold 4.5:1 under the aurora. Confirm that trade-off, or choose a lower fill with the larger text changes above. Removing the 7% sheen (the floor) is the other lever; not tested.
