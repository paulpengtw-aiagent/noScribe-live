# AICSS components (vendored)

Source: the free AICSS shadcn registry at https://www.aicss.dev. Installed with the documented command:

```
pnpm dlx shadcn@latest add https://www.aicss.dev/r/orbs.json https://www.aicss.dev/r/streaming-text.json https://www.aicss.dev/r/thinking-state.json
```

The CLI placed the files in `src/` and they were moved here, byte for byte. Their SHA-256 hashes were checked before and after the move.

License: MIT. The full text is in [LICENSE](./LICENSE), copied from https://github.com/kvnkld/aicss/blob/main/LICENSE.

## Unmodified (from the registry)

- `Orb.tsx`, `Orb.module.css`: the `Orb` component (variants S/B/C/G/M 1–5, `size`, `label`, `pill`).
- `ThinkingState.tsx`, `ThinkingState.module.css`: the shimmering "Thinking" label.
- `StreamingText.tsx`, `StreamingText.module.css`: installed as the registry ships it. The transcript does not use it; it renders a `<p>` with a fixed 14px size and restarts when `text` changes, so it cannot sit inside a paragraph.

## Our adaptations and own code

- `streaming-text-inline.tsx` and `streaming-text-inline.module.css`: adapted from `StreamingText`. The adaptation renders an inline `<span>`, takes a configurable speed with catch-up for backlogs (a segment finishes within about 700 ms), shows a caret only when asked (solid while revealing, blinking when idle), and respects reduced motion.
- `LICENSE`: copied from the AICSS repository, unchanged.
- This README.

## Notes for the surrounding app

- The registry's `ThinkingState` has no reduced-motion rule. `src/index.css` covers it with a global `prefers-reduced-motion` rule. The `Orb` already has its own.
- The `Orb` pill label asks for the family "Inter", but the bundled font registers "Inter Variable". `src/index.css` maps the label onto the app font.
- The AICSS Pro components are not used and were not fetched.
