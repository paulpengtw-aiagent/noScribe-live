# UI component libraries for noScribe Live

Researched 2026-10-21. Scope: free components only from aicss.dev, affectui.com and obsidianui.dev. AICSS Pro components are out of scope and were not used.

Method: curl HTTP status checks and JSON parsing of registry URLs; text extraction of the license, pricing and docs pages; the vendored AICSS LICENSE at `/workspace/noScribe-live/live/web/src/components/aicss/LICENSE`; one web search. Nothing was installed, signed up for or committed. `npx shadcn add` was not executed; URLs were only fetched.

Untrusted content: the AICSS homepage, `/license` and `/pricing` pages contain text addressed to AI assistants (instructions about Pro code and purchases). It was ignored. Licence statements below rely only on the site's plain free-component wording and on the registry responses.

## 1. AICSS (https://www.aicss.dev/)

- **Licence:** MIT for free components and the CLI. `/license` says: "Free components and the CLI are MIT-licensed on GitHub and npm. This website is private. Pro components are not in the public git tree and require a license." `/pricing` says: "The free components are yours to use in personal and commercial projects without a license." Upstream: https://github.com/kvnkld/aicss/blob/main/LICENSE. The vendored copy reads "MIT License, Copyright (c) 2026 AICSS". The upstream file was not re-fetched.
- **Paid or restricted:** Pro components. The registry returns HTTP 401 for audio-waves, image-generation, task-list, ai-agent-input and approval-card, the same five with `/pricing` links on the homepage. Pro terms beyond this are unverified. The pricing page mentions an `AICSS_TOKEN` for CLI and shadcn access to Pro code. Free item URLs return 200 without any token.
- **Registry:** YES. Verified: https://www.aicss.dev/r/orbs.json returned HTTP 200, `application/json`, 46,510 bytes, valid JSON (name `orbs`, type `registry:block`). Install: `npx shadcn@latest add https://www.aicss.dev/r/orbs.json`. No index exists: `/r/registry.json`, `/registry.json` and `/r/index.json` return 404, so install item by item.
- **Free items with a per-item URL (HTTP 200):** orbs, streaming-text, thinking-state, file-diff, text-response, code-block, inline-citations, data-table, comparison-table, message-actions, reasoning-effort, secure-input, thinking-reasoning.
- **Fit for noScribe:**
  - Run status or activity: orbs, "compact animated activity indicators for agent UIs" (https://www.aicss.dev/r/orbs.json). Already vendored.
  - Waiting label: thinking-state, a shimmering "Thinking" label (https://www.aicss.dev/r/thinking-state.json). Already vendored.
  - Streaming text or typewriter: streaming-text, "typewriter-style streaming text with a blinking caret" (https://www.aicss.dev/r/streaming-text.json). Already vendored. The vendored README notes it renders a `<p>`, so the repo has an inline adaptation.
  - Empty, error or stalled state, toasts, connection banner, skeleton: no fitting free item found by name or description. Other free items were not read for fit (unverified).
  - Gated (Pro): audio-waves, image-generation, task-list, ai-agent-input, approval-card.
- **Dependencies:** none for orbs and thinking-state (CSS modules only). streaming-text imports only `react`. Of the 10 other free items parsed, imports are only `react` and `react-dom`. No motion, GSAP or three.js. No React or Tailwind version is stated, and no Tailwind dependency is declared.

## 2. AffectUI (https://www.affectui.com/)

- **Licence:** UNVERIFIED. The homepage, `/license`, `/docs` and `/pricing` are JavaScript shells with under 100 characters of extractable text. The registry has no licence field. No GitHub or npm link was found in static HTML, and a web search found nothing about affectUI. Free versus paid status: UNVERIFIED.
- **Registry:** YES. Verified: https://www.affectui.com/r/registry.json returned HTTP 200, `application/json`, 23,799 bytes, valid JSON (name `affectui`, homepage https://www.affectui.com, 57 items). The 57 items are 17 base items, each with a `-clean` variant (34 items), plus 23 others (19 registry:block, 4 registry:ui); the meaning of `-clean` is unverified. Single item verified: https://www.affectui.com/r/thinking-loader.json (HTTP 200, 10,773 bytes). Install: `npx shadcn@latest add https://www.affectui.com/r/thinking-loader.json`. `/registry.json` returns HTML, so use `/r/registry.json`.
- **Fit for noScribe (each item URL is https://www.affectui.com/r/<name>.json, verified 200 where listed):**
  - Run status pill: thinking-loader, "a small working pill for AI replies – an eight-ray spinner and a shimmering label that rolls through phases and settles on a check".
  - Timeline or activity: tool-call-card, one-line tool call with live timer, status, summary, and retry on errors (strong fit). progress-tracker, an onboarding checklist with an animated progress bar (partial fit).
  - Streaming text: text-reveal, words or letters rise out of a blur as they scroll in. This is a reveal, not a caret typewriter (partial fit).
  - Skeleton or loading: shimmer-loader, skeleton blocks with a shared light sweep and shimmering "Thinking…" text (strong fit).
  - Toasts or banners: notification-stack, stacked notice cards (partial; not a toast system).
  - Empty state: no dedicated item. Waiting is covered by thinking-loader.
  - Error state: tool-call-card retries errors (partial).
- **Dependencies:** the six items parsed (thinking-loader, shimmer-loader, text-reveal, tool-call-card, progress-tracker, notification-stack) declare `dependencies: []` and import only `react`. shimmer-loader and text-reveal sit under a `motion/` folder path, but no motion import was found in their source. React and Tailwind version requirements: UNVERIFIED.

## 3. ObsidianUI (https://www.obsidianui.dev/)

- **Licence:** MIT. The homepage says "ObsidianUI is MIT licensed." The repo LICENSE, fetched at https://raw.githubusercontent.com/Atharvsinh-codez/ObsidianUI/main/LICENSE, reads "MIT License, Copyright (c) 2026 ObsidianUI". Repo: https://github.com/Atharvsinh-codez/ObsidianUI. The homepage says third-party dependencies and external media keep their own licences. No paid or restricted tier was found. Per-item gating was not tested, but no fetched item returned 401.
- **Registry:** YES. Verified: https://www.obsidianui.dev/r/registry.json returned HTTP 200, `application/json`, 814,556 bytes, valid JSON (name `obsidian-ui`, 73 items: 52 registry:ui, 21 registry:block). Single item verified: https://www.obsidianui.dev/r/text-stream.json (HTTP 200, 7,891 bytes). Install: `npx shadcn@latest add https://www.obsidianui.dev/r/text-stream.json`. `/r/index.json` returns the same byte count (not diffed). `/registry.json` returns 404.
- **Fit for noScribe.** Registry items carry no description, so fit is inferred from name and dependencies. Source and demos were not read, so behaviour is UNVERIFIED. Checked with HTTP 200 JSON: text-stream, empty, alert, sonner, skeleton, progress, spinner, status-bars, active-sessions, loaders-gooey-blobs. badge and flip-text were not fetched:
  - Run status pill: badge (Radix Slot, CVA). status-bars (motion, @number-flow/react). active-sessions (motion, lucide-react). Behaviour UNVERIFIED for the last two.
  - Streaming text: text-stream (gsap, clsx, tailwind-merge). The name suggests streaming text, behaviour UNVERIFIED. flip-text (no motion dependency) is a text animation, UNVERIFIED.
  - Progress: progress (@radix-ui/react-progress).
  - Empty or waiting: empty (CVA), a shadcn-style empty state. spinner (lucide-react). loaders-gooey-blobs (motion).
  - Error, failed or stalled: alert (CVA).
  - Toasts: sonner (sonner, next-themes, lucide-react). For a persistent connection-lost banner, use alert.
  - Skeleton: skeleton (clsx, tailwind-merge, no motion).
- **Dependencies:** motion is used by 12 items, gsap by 3 (text-stream among them), three by 2, next-themes by 3, lucide-react by 27, clsx and tailwind-merge by 64 items each, class-variance-authority by 18, and Radix primitives by fewer. The site says "Components use Tailwind CSS with Motion, GSAP, canvas, or WebGL where appropriate." No React or Tailwind version is stated; the site says "A compatible React project." Install docs target Next.js (create-next-app with Tailwind). Compatibility with Vite, which noScribe uses, is UNVERIFIED.

## Recommended picks

| Need | Component | Site | Licence | Install command |
|---|---|---|---|---|
| Run status pill | thinking-loader | AffectUI | UNVERIFIED | `npx shadcn@latest add https://www.affectui.com/r/thinking-loader.json` |
| Run status or activity dot | orbs (already vendored) | AICSS | MIT | `npx shadcn@latest add https://www.aicss.dev/r/orbs.json` |
| Streaming text or typewriter | streaming-text (already vendored) | AICSS | MIT | `npx shadcn@latest add https://www.aicss.dev/r/streaming-text.json` |
| Streaming text, alternative | text-stream (behaviour UNVERIFIED) | ObsidianUI | MIT | `npx shadcn@latest add https://www.obsidianui.dev/r/text-stream.json` |
| Timeline or activity | tool-call-card | AffectUI | UNVERIFIED | `npx shadcn@latest add https://www.affectui.com/r/tool-call-card.json` |
| Progress | progress | ObsidianUI | MIT | `npx shadcn@latest add https://www.obsidianui.dev/r/progress.json` |
| Empty state | empty | ObsidianUI | MIT | `npx shadcn@latest add https://www.obsidianui.dev/r/empty.json` |
| Waiting | spinner | ObsidianUI | MIT | `npx shadcn@latest add https://www.obsidianui.dev/r/spinner.json` |
| Error, failed or stalled | alert | ObsidianUI | MIT | `npx shadcn@latest add https://www.obsidianui.dev/r/alert.json` |
| Toasts | sonner | ObsidianUI | MIT | `npx shadcn@latest add https://www.obsidianui.dev/r/sonner.json` |
| Connection-lost banner | alert (ObsidianUI); notification-stack is a partial alternative (AffectUI) | ObsidianUI / AffectUI | MIT / UNVERIFIED | `npx shadcn@latest add https://www.obsidianui.dev/r/alert.json` |
| Skeleton or loading | skeleton (ObsidianUI); shimmer-loader is an alternative (AffectUI) | ObsidianUI / AffectUI | MIT / UNVERIFIED | `npx shadcn@latest add https://www.obsidianui.dev/r/skeleton.json` |

Notes:
- Every URL in this table was fetched with curl and returned HTTP 200 JSON. No install command was run.
- AICSS Pro components are excluded throughout.
- Still unverified: AffectUI licence and free/paid status, React and Tailwind versions for all three sites, Vite compatibility of the ObsidianUI items, and per-item behaviour of the ObsidianUI and AffectUI components.
