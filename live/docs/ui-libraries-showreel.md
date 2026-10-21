# UI libraries for the showreel round (checked 2026-10-21)

Rule for this round: install only items confirmed MIT, Apache-2.0 or ISC. Evidence is the repo LICENSE file, the GitHub licence API (`license.spdx_id`), or the registry package's own licence field. A statement that appears only on a marketing page is recorded as a claim and is not treated as verified.

## Installed

| Item | File | Install command | Evidence | Verdict |
| --- | --- | --- | --- | --- |
| Slider | `live/web/src/components/ui/slider.tsx` | `pnpm dlx shadcn@latest add https://www.obsidianui.dev/r/slider.json -y` | Registry item `slider` at https://www.obsidianui.dev/r/slider.json. Repo https://github.com/Atharvsinh-codez/ObsidianUI; LICENSE https://raw.githubusercontent.com/Atharvsinh-codez/ObsidianUI/main/LICENSE reads "MIT License, Copyright (c) 2026 ObsidianUI"; GitHub API `license.spdx_id` = MIT. | USE |
| Terminal and typing | `live/web/src/components/ui/terminal.tsx` | `pnpm dlx shadcn@latest add https://magicui.design/r/terminal.json -y` | Registry https://magicui.design/r/terminal.json; docs https://magicui.design/docs/components/terminal; repo https://github.com/magicuidesign/magicui, GitHub API `license.spdx_id` = MIT, name "MIT License". | USE |
| Sliding number | `live/web/src/components/ui/sliding-number.tsx` (thin wrapper) | `pnpm add @number-flow/react` (0.6.2) | Repo https://github.com/barvian/number-flow, GitHub API `license.spdx_id` = MIT; npm `@number-flow/react` `license` = MIT; allshadcn page https://allshadcn.com/tools/number-flow/ says "MIT-licensed" (claim, consistent). | USE |

Each installed shadcn file has a header comment with its source URL and licence. `sliding-number.tsx` has one too.

### Install notes

- The ObsidianUI slider added `@radix-ui/react-slider`, `clsx` and `tailwind-merge` to `live/web/package.json`. The CLI asked "The file utils.ts already exists. Would you like to overwrite?", got no answer, and left `src/lib/utils.ts` unchanged. `git status` shows it untouched.
- Magic UI's terminal adds no new package (it uses `motion`, which was already installed).
- Nothing imports these files yet, so the production bundle does not change until a component imports them. Load them lazily with `React.lazy` to keep first-load JS small.

## Not used

### animate-ui: DON'T (not plain MIT)

- Docs: https://animate-ui.com/docs. Relevant items: `sliding-number`, `typing-text`, `rolling-text`, `morphing-text`, `sliding-text` (https://animate-ui.com/docs/primitives/animate-ui/sliding-number and siblings); slider in Radix, Base UI and React Aria (https://animate-ui.com/docs/primitives/radix-ui/slider).
- Repo: https://github.com/imskyleen/animate-ui. GitHub API reports `license` = NOASSERTION ("Other").
- LICENSE.md, https://raw.githubusercontent.com/imskyleen/animate-ui/main/LICENSE.md: "MIT + Commons Clause License Condition", Copyright (c) 2025 Elliot Sutton. The MIT grant covers use "as part of an application, website, or product". The Commons Clause adds: "You may use this Software, including for any commercial purpose, so long as you do not sell or redistribute the components themselves in their original form".
- Verdict: DON'T this round, because the rule admits only MIT, Apache-2.0 or ISC and this licence adds a restriction. Whether the restriction matters for this project is for the owner to decide.
- The animate-ui registry JSON at `https://animate-ui.com/r/<name>.json` returned 404 for the names tried, so no registry install was attempted.

### allshadcn animations category

Source: https://allshadcn.com/tools/category/animations/ lists six tools. Their tool pages expose no repo link in the static HTML, so the table reports the page text. Only NumberFlow was checked against a repo.

| Tool | Page | Licence on page | Repo | Verdict |
| --- | --- | --- | --- | --- |
| number-flow | https://allshadcn.com/tools/number-flow/ | "MIT-licensed" | barvian/number-flow, MIT (API-verified) | USE (installed as NumberFlow) |
| tailwindcss-motion | https://allshadcn.com/tools/tailwindcss-motion/ | "MIT-licensed with 3.1k GitHub stars" (claim) | not linked | DON'T install: claim not checked |
| bundui-components | https://allshadcn.com/tools/bundui-components/ | "MIT-licensed, free to use and modify" (claim) | not linked | DON'T install: claim not checked |
| shadcn-hooks | https://allshadcn.com/tools/shadcn-hooks/ | "MIT license." (claim) | https://github.com/Debbl/shadcn-hooks (not API-checked) | Not needed (hooks, not animation) |
| skiper-ui | https://allshadcn.com/tools/skiper-ui/ | "open-source and free to use"; no licence named | not linked | DON'T: unverified |
| berlix-ui | https://allshadcn.com/tools/berlix-ui/ | "Open-source UI library"; no licence named | not linked | DON'T: unverified |

### Magic UI: other items not checked

The repo is MIT (GitHub API), so other Magic UI items would follow the same licence. Only `terminal` was installed, because it is the only one this round needed.

### shadcn.io templates

- Rule: each template has its own licence. The sampled template entries (solaris, reframe, spherule, max, zel, arete, lightbox, chatly, altshift, prodexa) carry `"license": "https://opensource.org/licenses/MIT"` in their JSON-LD. The site's FAQ "Licensing" answer is not in the static HTML, so the general rule is taken from the per-template metadata.
- Verdict: no template installed. Check each template's own repo LICENSE before use. No animation-specific template was checked in this round's time box.

### Earlier verified kits (unchanged)

AICSS free (MIT), ObsidianUI (MIT; re-checked above), AffectUI free (MIT) and uiarc free (MIT) are recorded in `live/README.md` and `live/docs/ui-libraries-nordic.md` and were not re-checked here, except ObsidianUI.

## APIs

```tsx
import { Slider } from "@/components/ui/slider"           // Radix slider props: value, defaultValue, min, max, step, onValueChange, className

import { Terminal, AnimatedSpan, TypingAnimation } from "@/components/ui/terminal"
// Terminal: children, className, sequence?: boolean, startOnView?: boolean
// AnimatedSpan: children, delay?, className?
// TypingAnimation: children: string, className?, duration?, delay?, as?

import SlidingNumber from "@/components/ui/sliding-number" // default export; named export SlidingNumber too
// Props: value: number, plus NumberFlow props (format, prefix, suffix, trend, animated, ...). See https://github.com/barvian/number-flow
```

## Demo driver

`live/stress/demo_driver.sh` replay step: `--max-gap ${REPLAY_MAX_GAP:-30}` (was `--max-gap 5`), with a header comment for `REPLAY_MAX_GAP`. The cap is in seconds and is set for real-speed pre-roll in demos.
