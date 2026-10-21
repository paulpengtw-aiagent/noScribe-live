# noScribe Live

noScribe Live is a localhost viewer that shows a noScribe CLI transcription streaming in real time. The page does not start transcriptions. It watches runs of the noScribe CLI started with `--live-feed`, and shows each transcript as it streams in. If you open it mid-run, it catches up from a snapshot.

![Midstream view of a run](docs/05-midstream-later.png)

Paths below are relative to the repo root unless noted.

## Run the viewer

```sh
live/run.sh              # serves http://localhost:8765
live/run.sh --rebuild    # forces a rebuild of the frontend in live/web
```

`run.sh` creates `live/.venv` (with `uv` for Python 3.11, otherwise `python3 -m venv`), installs `live/requirements.txt` when it changes, and builds `live/web` with pnpm (npm if pnpm is missing) when `live/web/dist` is missing or its sources changed since the last build. So after `git pull` the next start rebuilds the page by itself. The check compares file contents: the fingerprint of the sources is stamped into `live/web/dist/.build-stamp` after each successful build, so a bare `touch` does not trigger a rebuild. `--rebuild` forces a rebuild; `SKIP_WEB_BUILD=1` skips the check. npm runs with `--no-package-lock`, so it never writes `live/web/package-lock.json`; an old stray one from earlier npm runs can be deleted. Without a build, the server shows a placeholder page. Environment variables:

- `PORT`: port to serve on (default `8765`).
- `SKIP_WEB_BUILD=1`: never run pnpm or npm; serve whatever is in `live/web/dist`.
- `NOSCRIBE_PY`: Python with noScribe installed. It only changes the command that `run.sh` prints.
- `HOST`: bind address (default `127.0.0.1`). `HOST=0.0.0.0` listens on all interfaces.
- `LIVE_TOKEN`: if set, every path needs this token. Open `http://HOST:8765/?token=VALUE` once; a cookie (7 days) then keeps the browser in, and `curl -H "Authorization: Bearer VALUE"` also works. Without it nothing is gated. `python -m server --token VALUE` does the same, but `LIVE_TOKEN` keeps the value out of `ps`.

## Share the viewer through a tunnel

1. Start the gated viewer: `LIVE_TOKEN=... PORT=8766 SKIP_WEB_BUILD=1 live/run.sh`.
2. Run `live/stress/tunnel-bore.sh 8766`. It keeps a bore.pub TCP tunnel up on a fixed remote port, so the URL (`http://bore.pub:N`, also in `live/logs/tunnel-url.txt`) stays the same across reconnects. The port is remembered in `live/logs/bore-port`.
3. Open `<URL>/?token=<token>` once; that sets a cookie.

Needs the `bore` client: download the static musl build from https://github.com/ekzhang/bore/releases into `.tools/` (or set `BORE=...`).
Cloudflare quick tunnels buffer SSE, and localhost.run rotates its URL, which is why bore is used.
Caveat: bore is plain HTTP (no TLS), so the token and cookie travel unencrypted. Use it for public test audio only.
Alternative: `live/stress/tunnel.sh` (localhost.run: HTTPS, but the URL changes on every reconnect).

## Transcribe alongside it

From the repo root, in another terminal:

```sh
PYTHONDONTWRITEBYTECODE=1 /home/cheng/noScribe/venv/bin/python -m noScribe --no-gui --model breeze-asr-25 --speaker-detection auto --timestamps --live-feed live/feeds/ INPUT OUTPUT.html
```

- Any Python environment with noScribe's requirements works. In this container the read-only host venv `/home/cheng/noScribe/venv` is reused; `PYTHONDONTWRITEBYTECODE=1` keeps it untouched.
- Models are found in `~/.config/noScribe/whisper_models`. Link the host models there:

  ```sh
  mkdir -p ~/.config/noScribe/whisper_models
  for m in breeze-asr-25 breeze-asr-26 precise; do ln -sfn /mnt/data/noScribe-models/$m ~/.config/noScribe/whisper_models/$m; done
  ```

- `--live-feed DIR/` writes one `<run_id>.ndjson` per job. You can set `NOSCRIBE_LIVE_FEED` instead of the flag. Without either, noScribe behaves exactly as before. The event format is in [FEED.md](FEED.md).
- The GPU is shared. Check `nvidia-smi` and run one job at a time.

## Demo clip

`live/samples/make-demo-clip.sh` downloads two public-domain LibriVox recordings and builds `live/samples/demo-en-zh.mp3` (3:22, two speakers alternating):

- EN: Abraham Lincoln, "Gettysburg Address" (English)
- ZH: Lu Xun, 呐喊 自序 (preface to "Call to Arms"), read in Mandarin

The script needs `curl`, `ffmpeg`, `ffprobe` and `awk`.

## Rehearse without a GPU

```sh
cd live && .venv/bin/python -m server.replay path/to/recorded.ndjson --feeds feeds --speed 1
```

This replays a recorded feed as a new live run. `--max-gap` caps long pauses (default 5 s).

## Measured on this machine

Real run, 2026-10-20 ([`docs/e2e-arrivals.tsv`](docs/e2e-arrivals.tsv)). breeze-asr-25 on an NVIDIA GeForce RTX 5060 Ti (CUDA, compute_type `default`, float16), 202.4 s bilingual clip:

- Wall time 50.2 s, RTF 0.25 (real-time factor: processing time over audio length). This includes a 20 s model load and about 15 s of diarization.
- Whisper alone (model ready to end): RTF 0.07.
- All 50 segments reached the browser while the CLI was running. The last arrival came 0.7 s before the CLI process exited.
- CLI to browser latency per segment: median 36 ms, p95 70 ms, max 77 ms. Latency is the browser receive time minus the `t` the CLI wrote into the feed line (same machine clock). The file-to-server tail has a median of 30 ms, mostly the 50 ms poll; server-to-browser push has a median of 6 ms.

faster-whisper yields segments per 30 s decoding window, so they arrive in bursts about every 1-2 s. The UI smooths the bursts with a streaming reveal.

## Screenshots

- `docs/01-waiting.png`: before a run
- `docs/02-diarizing.png`: diarizing
- `docs/03-loading-model.png`: loading the model (thinking state)
- `docs/04-midstream.png`, `docs/05-midstream-later.png`: segments arriving one at a time (desktop, earlier and later)
- `docs/06-mobile-midstream.png`: mid-run on mobile
- `docs/07-finished.png`: after the run finished
- `docs/08-reopened-after-run-light.png`: opened after the run, catching up from the snapshot (light theme)

## How it works

- `noScribe/live_feed.py`: opt-in NDJSON writer. The format is documented in [FEED.md](FEED.md).
- `live/server`: FastAPI. It tails `live/feeds`. `GET /api/stream` is server-sent events with `hello` (server time and run list), `snapshot` (catch-up for a run) and `feed` (one event). It also serves `GET /api/runs` and `GET /api/runs/{id}/peaks`.
- Proxies: `/api/stream` sends `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`, a 2 KB comment after `retry`, and `: ping` every 15 s. Do not put compression middleware in front of it.
- Killed runs: a run with no `run_end` is "stale" once its CLI pid (from `run_start`) is gone and it has been quiet for 5 s. Without a pid, the 30-minute rule applies. A check every 2 s pushes status changes to open streams as `runs` messages.
- Latest (`/api/stream?run=latest`) follows the newest run that is still live, or the newest run when none is. Summaries carry `live` (status is running), `inferred_end_t` (`last_t` for a stale run, `ended_t` for an ended one, null while running) and `output_name` (basename of `output_file` if that file exists, else null).
- `GET /api/runs/{id}/peaks`: 404 for an unknown run, a run without audio, or a missing audio file; 422 `{"error": "audio could not be decoded", "detail": "..."}` when ffprobe or ffmpeg cannot read the file; 500 only for a server failure such as a missing ffmpeg.
- `GET /api/runs/{id}/export.odt?lang=en|zh-TW`: the transcript as an OpenDocument text file (stdlib only, no LibreOffice). 404 for an unknown run, 409 JSON while it is still running. Paragraphs follow the page's rules. The file name is `<audio stem>_YYYY-MM-DD_HHMM.odt` (server local time at run_start). Timestamps read M:SS, or H:MM:SS from one hour, as the screen does. Segments get a space between them where the page puts one (both sides CJK, or both non-CJK).
- Export text: Simplified Chinese is converted with OpenCC `s2tw` (`opencc-python-reimplemented`); the footer and meta do not name it. The page converts with opencc-js `cn` to `tw`. The two agree on common words (櫃台→櫃臺, 柜台→櫃檯, 台灣→臺灣, 后来→後來, 干净→乾淨), but about 40 of 61,000 random CJK inputs differ on single variant characters (托, 擡, 栗, 樑, 硷 among them). Exact parity needs the opencc-js cn-to-tw dictionary ported to the server; not done.
- `live/web`: React, Vite, TypeScript, Tailwind v4, shadcn/ui and motion.

## UI components and licensing

- From the AICSS free MIT registry, installed unmodified with `pnpm dlx shadcn@latest add https://www.aicss.dev/r/orbs.json https://www.aicss.dev/r/streaming-text.json https://www.aicss.dev/r/thinking-state.json` into `live/web/src/components/aicss/`:
  - `Orb` is used as the status pills and the brand glyph.
  - `ThinkingState` is the thinking label.
  - `StreamingText` is adapted into `streaming-text-inline.tsx`.
- No AICSS Pro components are used.
- Built here: the canvas activity orb (`live/web/src/lib/orb-renderer.ts`), the timeline, the layout and the status chips.
- Chinese segment text is shown in Traditional (Taiwan) through `opencc-js` (cn→tw), converted for display only and loaded lazily; the feed and the saved HTML are unchanged.
- From the ObsidianUI shadcn registry (MIT), installed with `pnpm dlx shadcn@latest add https://www.obsidianui.dev/r/alert.json https://www.obsidianui.dev/r/skeleton.json https://www.obsidianui.dev/r/sonner.json https://www.obsidianui.dev/r/command.json https://www.obsidianui.dev/r/popover.json https://www.obsidianui.dev/r/input.json` into `live/web/src/components/ui/`: `Alert`, `Skeleton`, `Sonner` (theme passed as a prop; next-themes not used), `Command` (with its `Dialog` dependency), `Popover` and `Input`.

Licence verdicts (checked 2026-10-21; evidence, install URLs and candidates in [docs/ui-libraries-nordic.md](docs/ui-libraries-nordic.md)):

- AICSS (free registry): MIT for free components and the CLI, "Free components and the CLI are MIT-licensed on GitHub and npm" ([licence](https://www.aicss.dev/license); [MIT text](https://raw.githubusercontent.com/kvnkld/aicss/main/LICENSE)). Verdict: USE, free items only; Pro is excluded.
- ObsidianUI: MIT, "Components are MIT licensed" ([terms](https://www.obsidianui.dev/terms), section 05; [repo LICENSE](https://github.com/Atharvsinh-codez/ObsidianUI/blob/main/LICENSE)). Verdict: USE.
- AffectUI: "Items marked as free are open source under the MIT license" ([terms](https://www.affectui.com/terms), section 4; [llms.txt](https://www.affectui.com/llms.txt), "40 items are free and open source (MIT)"). Verdict: USE, free-tagged items only; Pro is excluded ([Pro licence](https://www.affectui.com/license)).
- uiarc: "Free: MIT" ([licence](https://uiarc.dev/license); [terms](https://uiarc.dev/terms), "The free library is MIT licensed"). Verdict: USE, free items only; Pro is excluded.
- animate-ui — MIT + Commons Clause; approved by the owner for consulting use (2026-10-22). The Commons Clause bars selling or redistributing the components in their original form ([LICENSE.md](https://raw.githubusercontent.com/imskyleen/animate-ui/main/LICENSE.md)).

Showreel round, checked 2026-10-21. Details, evidence URLs and install commands are in [docs/ui-libraries-showreel.md](docs/ui-libraries-showreel.md).

| Source | Item | Repo | Licence and evidence | Verdict |
| --- | --- | --- | --- | --- |
| ObsidianUI | Slider, `web/src/components/ui/slider.tsx` | [Atharvsinh-codez/ObsidianUI](https://github.com/Atharvsinh-codez/ObsidianUI) | MIT, LICENSE "MIT License, Copyright (c) 2026 ObsidianUI" | USE (installed) |
| Magic UI | Terminal, `web/src/components/ui/terminal.tsx` | [magicuidesign/magicui](https://github.com/magicuidesign/magicui) | MIT, GitHub licence "MIT License" | USE (installed) |
| NumberFlow | Sliding number, `web/src/components/ui/sliding-number.tsx` (npm `@number-flow/react`) | [barvian/number-flow](https://github.com/barvian/number-flow) | MIT, GitHub licence "MIT License"; npm `license` MIT | USE (installed) |
| animate-ui | sliding-number, typing-text, rolling-text, morphing-text, radix/base/react-aria slider | [imskyleen/animate-ui](https://github.com/imskyleen/animate-ui) | "MIT + Commons Clause License Condition" (LICENSE.md); GitHub reports NOASSERTION | DON'T: not plain MIT |
| allshadcn | tailwindcss-motion, bundui-components | tool pages, no repo linked | page claims "MIT-licensed"; not checked against a repo LICENSE | DON'T install: claim only |
| allshadcn | skiper-ui, berlix-ui | tool pages, no repo linked | no licence named on the page | DON'T: unverified |
| allshadcn | number-flow | [barvian/number-flow](https://github.com/barvian/number-flow) | MIT (API-verified, as above) | USE (as NumberFlow) |
| shadcn.io | templates (331+) | per template | sampled JSON-LD `license` = `https://opensource.org/licenses/MIT`; each template carries its own licence | Check each template before use; none used |

## Tests

```sh
uvx --with pytest pytest tests/test_live_feed.py --noconftest -q                          # hook, from the repo root
cd live && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest    # backend
```

## Known gaps

- Chinese is converted to Traditional (Taiwan) for display only (opencc-js cn→tw); Whisper output carries no punctuation, and none is added.
- There are no automated frontend tests.
