# Crimson palette: tokens and contrast

The second colour family of the live viewer. It sits next to Nordic and works with both light and dark. The
palette is chosen in the theme menu (Nordic or Crimson) and stored in localStorage as `noscribe-live-palette`
("nordic" or "crimson"). The light or dark choice is stored as `noscribe-live-theme`, as before. index.html sets
`<html data-palette>` before first paint, and the CSS keys off that attribute:

- `html[data-palette="crimson"]:not(.dark)`: Crimson light tokens (in `src/index.css`)
- `html.dark[data-palette="crimson"]`: Crimson dark tokens (in `src/index.css`)
- `html[data-easy="true"][data-palette="crimson"][data-theme=...]`: Easy-view overrides (in `src/easy.css`)

Colours only: no logo, mascot or pattern. Primary red `#93272C`, navy `#003865`, black `#2D2926`, cool greys
`#D9D9D6` `#C8C9C7` `#75787B` `#53565A`, cream `#F7F3E8`, accents `#F5E1A4` `#A4BCC2` `#0077C8`, silver `#8A8D8F`,
gold `#B9975B` (sparingly). Source colours: from the brand manual (its Pantone references are not reproduced here).

Ratios below are WCAG 2.x relative-luminance contrast, computed by a script (the same formulas as the WCAG spec).
Each text token must reach 4.5:1 (AA) on every surface it sits on, and the Easy view 7:1. The values are the
minimum over the surfaces listed in each heading.

### Light (page #F7F3E8, card #FBF9F3, raised #EDE7D6)
| Role | Token | Value | Min ratio (page / card / raised) | Need |
|---|---|---|---|---|
| foreground | `--foreground` | #2D2926 | 11.67:1 | 4.5:1 (AA) |
| muted | `--muted-foreground` | #53565A | 5.97:1 | 4.5:1 (AA) |
| ink-3 | `--ink-3` | #5B5E62 | 5.28:1 | 4.5:1 (AA) |
| primary (text) | `--primary` | #93272C | 6.62:1 | 4.5:1 (AA) |
| navy (text) | `--secondary` | #003865 | 9.70:1 | 4.5:1 (AA) |
| live ink | `--status-live-ink` | #276B4E | 5.15:1 | 4.5:1 (AA) |
| loading ink | `--status-loading-ink` | #6E5417 | 5.78:1 | 4.5:1 (AA) |
| failed ink | `--status-failed-ink` | #A8163D | 5.97:1 | 4.5:1 (AA) |
| stopped ink | `--status-stopped-ink` | #9C4506 | 5.20:1 | 4.5:1 (AA) |
| finished ink | `--status-finished-ink` | #003865 | 9.70:1 | 4.5:1 (AA) |
| time ink | `--time-ink` | #003865 | 9.70:1 | 4.5:1 (AA) |

### Dark (page #0B1622, card #0F1D2C, raised #1A2B3E)
| Role | Token | Value | Min ratio (page / card / raised) | Need |
|---|---|---|---|---|
| foreground | `--foreground` | #F2EEE4 | 12.42:1 | 4.5:1 (AA) |
| muted | `--muted-foreground` | #C8C9C7 | 8.66:1 | 4.5:1 (AA) |
| ink-3 | `--ink-3` | #B4B9C0 | 7.29:1 | 4.5:1 (AA) |
| primary (text) | `--primary` | #F08A8F | 5.99:1 | 4.5:1 (AA) |
| live ink | `--status-live-ink` | #6CC59A | 6.92:1 | 4.5:1 (AA) |
| loading ink | `--status-loading-ink` | #F5E1A4 | 11.10:1 | 4.5:1 (AA) |
| failed ink | `--status-failed-ink` | #FF8A80 | 6.30:1 | 4.5:1 (AA) |
| stopped ink | `--status-stopped-ink` | #F2A65A | 7.11:1 | 4.5:1 (AA) |
| finished ink | `--status-finished-ink` | #A4BCC2 | 7.23:1 | 4.5:1 (AA) |
| time ink | `--time-ink` | #9CC3DD | 7.72:1 | 4.5:1 (AA) |

### Easy view, light (7:1)
| Role | Token | Value | Min ratio (page / card / raised) | Need |
|---|---|---|---|---|
| foreground | `--foreground` | #000000 | 17.00:1 | 7:1 |
| muted | `--muted-foreground` | #2D2926 | 11.67:1 | 7:1 |
| ink-3 | `--ink-3` | #3A3733 | 9.58:1 | 7:1 |
| live ink | `--status-live-ink` | #164D36 | 7.91:1 | 7:1 |
| loading ink | `--status-loading-ink` | #5A4310 | 7.57:1 | 7:1 |
| failed ink | `--status-failed-ink` | #8E1B15 | 7.34:1 | 7:1 |
| stopped ink | `--status-stopped-ink` | #6E3404 | 7.89:1 | 7:1 |
| finished ink | `--status-finished-ink` | #002B4F | 11.66:1 | 7:1 |

### Easy view, dark (7:1)
| Role | Token | Value | Min ratio (page / card / raised) | Need |
|---|---|---|---|---|
| foreground | `--foreground` | #FFFFFF | 14.39:1 | 7:1 |
| muted | `--muted-foreground` | #F2EEE4 | 12.42:1 | 7:1 |
| ink-3 | `--ink-3` | #EDE9E0 | 11.88:1 | 7:1 |
| live ink | `--status-live-ink` | #BDEBD2 | 10.95:1 | 7:1 |
| loading ink | `--status-loading-ink` | #FBEFC8 | 12.53:1 | 7:1 |
| failed ink | `--status-failed-ink` | #FFC2BC | 9.39:1 | 7:1 |
| stopped ink | `--status-stopped-ink` | #FFD3A0 | 10.33:1 | 7:1 |
| finished ink | `--status-finished-ink` | #CFE7F5 | 11.24:1 | 7:1 |

### Status pairs
- Light Failed #A8163D vs Stopped #9C4506: dE76 39.4, deuteranopia dE 26.1
- Dark Failed #FF8A80 vs Stopped #F2A65A: dE76 33.5, deuteranopia dE 21.7
- Light Live #276B4E vs Loading #6E5417: dE76 43.3, deuteranopia dE 29.9
- Dark Live #6CC59A vs Loading #F5E1A4: dE76 43.0, deuteranopia dE 29.3

### Non-text
- Ring: light #0077C8 3.80:1; dark #A4BCC2 7.23:1
- Light status dots (min vs page/card/raised): failed 5.97, stopped 5.20, live 5.15, finished 9.70
- Dark status dots: failed 6.30, stopped 7.11, live 6.92, loading 11.10
- Speaker fills (min vs light card and dark card): #B8424A 3.18, #3B6E9E 3.17, #A8843E 3.31, #2F8F87 3.69, #8A8D8F 3.17, #0077C8 3.63

## Speaker palette (src/lib/speakers.ts)

- Fills (timeline blocks, waveform bars, speaker chips), theme-independent: `#b8424a #3b6e9e #a8843e #2f8f87 #8a8d8f #0077c8`. Each is at least 3:1 against both the Crimson light card and the dark card.
- Light text and legend dots: `#93272c #003865 #7a5a1e #0061a8 #24665f #53565a`, at least 4.5:1 on the light card.
- Dark text and legend dots: `#f08a8f #a4bcc2 #f5e1a4 #7fb8e6 #6cc5bd #c8c9c7`, at least 4.5:1 on the dark card.

## Orb and aurora

- Orb ink gradient (src/lib/orb-renderer.ts): dark `#f08a8f → #f5e1a4 → #7fb8e6`; light `#93272c → #7a5a1e → #003865`.
- Aurora (src/index.css, the `--aurora-*` tokens; src/components/live/aurora-background.tsx needs no change because it reads them): light `#a4bcc2 #b9975b #93272c #003865` at opacity 0.30; dark `#1f4e7a #b9975b #7a1f25 #2a5f8f` at opacity 0.45.
