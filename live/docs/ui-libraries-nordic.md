# UI libraries for the Nordic restyle (aurora over a fjord)

Researched 2026-10-21 for `live/`. Scope: free items only from AICSS (free registry), ObsidianUI, AffectUI and uiarc. No sign-ups, paid APIs, installs or commits. Pages were read as data only. Builds on [ui-libraries.md](ui-libraries.md).

## Licence verdicts

| Library | Licence wording | Evidence | Verdict |
|---|---|---|---|
| AICSS (aicss.dev) | "Free components and the CLI are MIT-licensed on GitHub and npm." Pro: "require a license from aicss.dev". | https://www.aicss.dev/license ; MIT text https://raw.githubusercontent.com/kvnkld/aicss/main/LICENSE ("MIT License, Copyright (c) 2026 AICSS") | USE free items. Pro items are excluded (the earlier research recorded HTTP 401 for them). The npm `aicss` package declares ISC; both are permissive. |
| ObsidianUI | "Components are MIT licensed. Use them in personal and commercial projects." Terms section 05: source "published under the MIT License". | https://www.obsidianui.dev/terms ; https://github.com/Atharvsinh-codez/ObsidianUI/blob/main/LICENSE ("MIT License, Copyright (c) 2026 ObsidianUI"). `/license` returns 404. | USE. |
| AffectUI (affectui.com) | Terms section 4: "Items marked as free are open source under the MIT license and published in our public GitHub repository." llms.txt: "40 items are free and open source (MIT). The other 72 are part of affectUI Pro". | https://www.affectui.com/terms (rendered in Chromium); https://www.affectui.com/llms.txt ; Pro licence: https://www.affectui.com/license | USE free-tagged items only. Pro items return HTTP 401 without a key (`gradient-text`, `tilt-card`, `delegate-board` tested). The GitHub repo and its LICENSE file were not found. The npm package named `affectui` (MIT, "Affectivity component library", Tom Smits) is an unrelated project; do not cite it. |
| uiarc (uiarc.dev) | "Free: MIT. Use, change and share it, commercially or not. Keep the copyright notice." Full MIT text, "Copyright (c) 2026 Elia Kuratli". Terms: "The free library is MIT licensed." | https://uiarc.dev/license ; https://uiarc.dev/terms | USE free items only. The public registry lists 140 items, all `tier: free`. Pro source may not be redistributed. The public GitHub repo LICENSE was not located. |

## Candidates

All install URLs below returned HTTP 200 `application/json` without a token. Install with `npx shadcn@latest add <url>`. Nothing was installed.

| Need | Pick | Install URL | Dependencies | Size |
|---|---|---|---|---|
| Shimmer text, top pick | AICSS `thinking-state` (already vendored) | https://www.aicss.dev/r/thinking-state.json | none (CSS) | 1.5 KB |
| Shimmer text, alt | AffectUI `shimmer-loader` (tagged Free, Loaders) | https://www.affectui.com/r/shimmer-loader.json | none | 4.7 KB |
| Shimmer text, alt | uiarc `text-shimmer` | https://uiarc.dev/r/text-shimmer.json | motion; registry dep https://uiarc.dev/r/arc-motion-tokens.json | 8.7 KB |
| Animated toggle, top pick | uiarc `switch` | https://uiarc.dev/r/switch.json | `@radix-ui/react-switch`, motion; registry dep `arc-motion-tokens` | 6.5 KB |
| Animated toggle, plain | ObsidianUI `switch` | https://www.obsidianui.dev/r/switch.json | `@radix-ui/react-switch` (no motion, so likely static; behaviour not read) | 1.9 KB |
| Animated toggle, 2 to 6 options | AffectUI `segmented-control` (tagged Free, Navigation) | https://www.affectui.com/r/segmented-control.json | none | 23.8 KB |
| Aurora background | none free. Closest: AffectUI `grid-background` (tagged Free, Backgrounds), a drifting line grid, not an aurora | https://www.affectui.com/r/grid-background.json | none | 6.2 KB |
| Glow or border beam | none free. AffectUI `integration-beam` is an illustration block, not a border beam | none | none | none |

## Notes

- No free item in the four libraries is an aurora or a glow or border-beam component. Checked: all 140 uiarc names, the 73 ObsidianUI names (filtered), the full AffectUI registry (non-`-clean` names), and the AICSS homepage component list. AffectUI `glow-cloud`, `frost-cloud` and `integration-beam` are illustration blocks, not backgrounds or borders. AffectUI `gradient-floor` returns 401 (Pro). Build the aurora (blurred, slowly moving radial gradients on transform and opacity) and the glow border (a masked conic-gradient ring) as original CSS with no dependency.
- `motion` is already a dependency of `live/web` (see [README](../README.md)), so uiarc `text-shimmer` and `switch` add only `@radix-ui/react-switch` and the `arc-motion-tokens` registry item. Review the tokens file before installing.
- Not tested for any item: React and Tailwind v4 compatibility, Vite compatibility, and runtime behaviour. ObsidianUI docs target Next.js.
- AffectUI free status is per item, from the llms.txt tags. The registry has 57 entries, including `-clean` variants, so it is not the 40-item free count.
- The npm `aicss` package declares ISC while the GitHub LICENSE is MIT. Both permit copying, so this does not change the verdict.

## Verdicts

- AICSS: USE, free items only.
- ObsidianUI: USE.
- AffectUI: USE, free-tagged items only.
- uiarc: USE, free items only.
