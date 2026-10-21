#!/usr/bin/env python3
"""UX checks for noScribe Live: sticky follow, reveal and screen-reader output, connection states,
paragraphs and linking, and the run picker. Servers, replays and browsers are started by this script.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I live/stress/test_ux.py [--only stick,reveal,conn,para,picker] [--port 8770]
        [--static DIR] [--python PY] [--work DIR]

Every group starts its own `python -m server` on --port (a fresh feeds dir each time) and its own
replays (`python -m server.replay SRC --speed N --max-gap S`). --port+1 hosts the empty-feeds server and
--port+2 the waveform-note server. WORK (default /tmp/nslive-r4) holds src/ (copies of the recorded feeds;
the originals are read only), feeds/, logs/ and shots/.

The checks read the DOM contract: data-testid hooks, data-following, data-state, data-active,
data-segment-seq / data-segment-index, data-timeline-index, data-status, data-run-id and the
window.__NSLIVE_HEARTBEAT_TIMEOUT_MS override. A failure is annotated "contract absent" when the
element the check needs is missing from the page. Each scenario runs on its own: a crash in one is
reported as a FAIL of that scenario and the rest still run. Exit code 0 only if every check passed.
Every child process is killed on exit.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent            # live/stress
LIVE_DIR = HERE.parent                            # cwd for `python -m server` and `python -m server.replay`
DEFAULT_STATIC = LIVE_DIR / "web" / "dist"
DEFAULT_PY = "/workspace/noScribe-live/live/.venv/bin/python"
DEFAULT_WORK = Path("/tmp/nslive-r4")
FEEDS_SRC = Path("/workspace/noScribe-live/live/feeds")       # read only
DEMO_NAME = "20261020-052449-demo-en-zh.ndjson"              # 50 segments, 2 speakers, EN + ZH
GROUPS = ("stick", "reveal", "conn", "para", "picker")
STAMP = time.strftime("%Y%m%d-%H%M%S")
VIEWPORT = {"width": 1440, "height": 900}

# Runs in every document before the app's scripts: counts EventSource opens and errors and records
# every segment/run_end the stream delivers (from `feed` and from `snapshot` catch-ups).
INIT_JS = r"""
(() => {
  if (window.__nsObs) return;
  const O = { opens: 0, errors: 0, feeds: [] };
  window.__nsObs = O;
  const Native = window.EventSource;
  if (!Native) return;
  const note = (events, runId) => {
    for (const ev of events || []) {
      if (ev && ev.type) O.feeds.push({ run_id: runId, type: ev.type, seq: ev.seq });
    }
  };
  const Wrapped = function EventSource(url, init) {
    const es = new Native(url, init);
    es.addEventListener("open", () => { O.opens += 1; });
    es.addEventListener("error", () => { O.errors += 1; });
    es.addEventListener("snapshot", (e) => {
      try { const d = JSON.parse(e.data); note(d.events, d.run_id); } catch (err) {}
    });
    es.addEventListener("feed", (e) => {
      try { const msg = JSON.parse(e.data); note([msg.event], msg.run_id); } catch (err) {}
    });
    return es;
  };
  Wrapped.prototype = Native.prototype;
  Wrapped.CONNECTING = Native.CONNECTING;
  Wrapped.OPEN = Native.OPEN;
  Wrapped.CLOSED = Native.CLOSED;
  window.EventSource = Wrapped;
})();
"""

# Records, per document: sr-announcer text additions (window.__nsAnn) and, per segment seq, the time it
# first appeared and each change of its text length (window.__nsSegRec). Used by the reveal checks.
REC_JS = r"""
(() => {
  if (window.__nsRecInstalled) return;
  window.__nsRecInstalled = true;
  window.__nsAnn = [];
  window.__nsAnnSeen = new WeakSet();
  window.__nsSegRec = {};
  const note = () => {
    const now = performance.now();
    const ann = document.querySelector('[data-testid="sr-announcer"]');
    if (ann) {
      // One entry per announcer line, recorded when the line first appears (lines are never edited in place).
      for (const child of ann.children) {
        if (window.__nsAnnSeen.has(child)) continue;
        window.__nsAnnSeen.add(child);
        const txt = child.textContent.trim();
        if (txt) window.__nsAnn.push(txt);
      }
    }
    for (const el of document.querySelectorAll('[data-segment-seq]')) {
      const seq = el.getAttribute('data-segment-seq');
      let rec = window.__nsSegRec[seq];
      if (!rec) rec = window.__nsSegRec[seq] = { appear: now, log: [] };
      const len = el.textContent.trim().length;
      const last = rec.log.length ? rec.log[rec.log.length - 1][1] : -1;
      if (len !== last) rec.log.push([now, len]);
    }
  };
  new MutationObserver(note).observe(document, { subtree: true, childList: true, characterData: true });
  note();
})();
"""

RUN_STATE_JS = """() => { const e = document.querySelector('[data-testid="run-state"]');
  return e ? { state: e.getAttribute('data-state'), text: e.textContent.trim() } : {}; }"""
METRICS_JS = """() => { const s = document.querySelector('[data-testid="transcript-scroll"]');
  return s ? { top: s.scrollTop, client: s.clientHeight, height: s.scrollHeight,
               following: s.getAttribute('data-following') } : null; }"""
IN_VIEW_JS = """(idx) => { const sc = document.querySelector('[data-testid="transcript-scroll"]');
  const el = document.querySelector('[data-segment-index="' + idx + '"]');
  if (!sc || !el) return false;
  const a = sc.getBoundingClientRect(), b = el.getBoundingClientRect();
  return b.height > 0 && b.top >= a.top - 1 && b.bottom <= a.bottom + 1; }"""
TEXT_JS = """(sel) => { const e = document.querySelector(sel); return e ? e.textContent.trim() : null; }"""
ATTR_JS = """([sel, name]) => { const e = document.querySelector(sel); return e ? e.getAttribute(name) : null; }"""
SEG_COUNT_JS = """() => document.querySelectorAll('[data-segment-seq]').length"""
SEQS_JS = """() => Array.from(document.querySelectorAll('[data-segment-seq]')).map((e) => e.getAttribute('data-segment-seq'))"""
TURNS_JS = """() => Array.from(document.querySelectorAll('[data-testid="turn"]')).map((t) => {
  const ps = Array.from(t.querySelectorAll('[data-testid="paragraph"]'));
  const text = ps.map((p) => p.textContent.trim()).join('').trim();
  return { paras: ps.length, empty: text.length === 0, html: t.outerHTML.slice(0, 200) }; })"""
PARA_JS = """() => Array.from(document.querySelectorAll('[data-testid="turn"]')).map((t) => ({
  paras: Array.from(t.querySelectorAll('[data-testid="paragraph"]')).map((p) => {
    const time = p.getAttribute('data-start');
    return { time, hasTime: time !== null };
  }) }))"""
OPTS_JS = """() => Array.from(document.querySelectorAll('[data-testid="run-option"]')).map((e) => ({
  status: e.getAttribute('data-status'), runId: e.getAttribute('data-run-id'), text: e.textContent.trim() }))"""
WAVE_JS = """() => { if (document.querySelector('[data-testid="waveform"]')) return 'waveform';
  if (document.querySelector('[data-peaks="loaded"]')) return 'peaks-loaded';
  return null; }"""


def port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_until(fn: Callable[[], Any], timeout: float, step: float = 0.3) -> Any:
    """Call fn until it returns a truthy value or the timeout passes. Returns the last value."""
    end = time.monotonic() + timeout
    while True:
        try:
            value = fn()
        except Exception:  # page navigating, server restarting, feed line half written
            value = None
        if value or time.monotonic() >= end:
            return value
        time.sleep(step)


def feed_info(path: Path) -> dict[str, Any]:
    """Run id, segment count and segment seqs of a feed file. Lines still being written are skipped."""
    run_id = None
    seqs: list[Any] = []
    ended = False
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            run_id = run_id or ev.get("run_id")
            if ev.get("type") == "segment":
                seqs.append(ev.get("seq"))
            elif ev.get("type") == "run_end":
                ended = True
    return {"run_id": run_id, "segments": len(seqs), "seqs": seqs, "ended": ended}


def feed_texts(path: Path) -> dict[int, int]:
    """seq -> length of the segment text (stripped), as the page should show it."""
    out: dict[int, int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("type") == "segment":
            out[ev["seq"]] = len((ev.get("text") or "").strip())
    return out


def newest_finished_zh() -> Path:
    """Newest *-02-zh-tw-speech.ndjson in the live feeds dir whose run_end status is finished."""
    best = None
    for path in FEEDS_SRC.glob("*-02-zh-tw-speech.ndjson"):
        status = None
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("type") == "run_end":
                    status = ev.get("status")
        except OSError:
            continue
        if status == "finished" and (best is None or path.stat().st_mtime > best.stat().st_mtime):
            best = path
    if best is None:
        raise RuntimeError(f"no finished *-02-zh-tw-speech.ndjson in {FEEDS_SRC}")
    return best


def to_seconds(value: Any) -> float | None:
    """data-start may be seconds or HH:MM:SS(.ms); return seconds or None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        total = 0.0
        for part in str(value).replace(",", ".").split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        return None


# ---- page reads -----------------------------------------------------------------------------------
def seg_count(page: Any) -> int:
    return int(page.evaluate(SEG_COUNT_JS))


def attr_of(page: Any, selector: str, name: str) -> str | None:
    return page.evaluate(ATTR_JS, [selector, name])


def text_of(page: Any, selector: str) -> str | None:
    return page.evaluate(TEXT_JS, selector)


def following(page: Any) -> str | None:
    return attr_of(page, '[data-testid="transcript-scroll"]', "data-following")


def metrics(page: Any) -> dict[str, Any]:
    return page.evaluate(METRICS_JS) or {}


def scroll_top(page: Any) -> float | None:
    return metrics(page).get("top")


def at_bottom(page: Any) -> bool:
    m = metrics(page)
    return bool(m) and m["top"] + m["client"] >= m["height"] - 10


def conn_state(page: Any) -> str | None:
    return attr_of(page, '[data-testid="conn-state"]', "data-state")


def banner_visible(page: Any) -> bool:
    return page.locator('[data-testid="conn-banner"]').is_visible()


def jump_text(page: Any) -> str | None:
    return text_of(page, '[data-testid="jump-to-live"]')


def page_ended(page: Any, run_id: str) -> bool:
    feeds = page.evaluate("() => (window.__nsObs ? window.__nsObs.feeds : [])") or []
    return any(e.get("run_id") == run_id and e.get("type") == "run_end" for e in feeds)


def highlighted(page: Any, idx: int) -> bool:
    sel = f'[data-timeline-index="{idx}"]'
    return attr_of(page, sel, "data-active") == "true" or attr_of(page, sel, "data-hovered") == "true"


# Timeline clicks: the timeline has one hit layer ([data-testid="timeline-hit"]) that maps the pointer x to the
# nearest segment; the per-block [data-timeline-index] buttons are pointer-events-none, so a block is clicked at
# its bounding-box centre with a real mouse click.
def block_centre(page: Any, idx: int) -> tuple[float, float]:
    loc = page.locator(f'[data-timeline-index="{idx}"]').first
    loc.scroll_into_view_if_needed(timeout=5000)
    box = loc.bounding_box(timeout=5000)
    if box is None:
        raise RuntimeError(f"timeline block {idx} has no bounding box")
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def click_block(page: Any, idx: int) -> None:
    x, y = block_centre(page, idx)
    page.mouse.click(x, y)


def open_picker(page: Any) -> None:
    if not page.locator('[data-testid="run-option"]').first.is_visible():
        page.locator('[data-testid="run-picker"]').click(timeout=5000)


PREROLL_DONE_JS = """() => { const p = window.__nslivePreroll; return !p || p.active === false; }"""
FULL_UI_SELECTORS = ('[data-testid="stage-card"]', '[data-testid="transcript-scroll"]')


def full_ui_visible(page: Any) -> bool:
    """True when the pre-roll of a live run has ended and the stage card or the transcript scroller is visible."""
    if not page.evaluate(PREROLL_DONE_JS):
        return False
    return any(page.locator(sel).first.is_visible() for sel in FULL_UI_SELECTORS)


def wait_full_ui(page: Any, timeout: float = 30.0) -> bool:
    """Waits until window.__nslivePreroll is falsy or active === false AND the full UI is on screen. Call it after
    opening a LIVE run and before using the picker, run-state chip, transcript, jump button or timeline."""
    return bool(wait_until(lambda: full_ui_visible(page), timeout, 0.2))


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.port = args.port
        # Servers and replays run with cwd=LIVE_DIR (live/), so a relative --static or --work would resolve under
        # live/ (live/live/web/dist is missing, the server then serves its 429-byte placeholder page). Make them absolute.
        self.static = Path(args.static).resolve()
        self.py = args.python
        self.work = Path(args.work).resolve()
        self.shots = self.work / "shots"
        self.logs = self.work / "logs" / f"ux-{STAMP}"
        self.src = self.work / "src"
        self.feeds_root = self.work / "feeds"
        for directory in (self.shots, self.logs, self.src, self.feeds_root):
            directory.mkdir(parents=True, exist_ok=True)
        self.results: list[tuple[str, bool]] = []
        self.procs: list[subprocess.Popen] = []
        self.counter = 0
        self.demo_src = self.zh_src = self.noaudio_src = self.src

    # ---- sources and processes ----------------------------------------------------------------------
    def prepare_sources(self) -> None:
        self.demo_src = self.src / DEMO_NAME
        shutil.copyfile(FEEDS_SRC / DEMO_NAME, self.demo_src)
        zh_orig = newest_finished_zh()
        self.zh_src = self.src / zh_orig.name
        shutil.copyfile(zh_orig, self.zh_src)
        # The demo with its run_start audio_file pointing at a file that does not exist.
        self.noaudio_src = self.src / "demo-en-zh-missing-audio.ndjson"
        out = []
        for raw in self.demo_src.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(raw)
            except ValueError:
                out.append(raw)
                continue
            if ev.get("type") == "run_start":
                ev["audio_file"] = str(self.work / "missing" / "no-such-audio.mp3")
            out.append(json.dumps(ev, ensure_ascii=False))
        self.noaudio_src.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"sources: demo {DEMO_NAME}, zh {zh_orig.name} (copied to {self.src})", flush=True)

    @staticmethod
    def _env() -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_TOKEN"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # keep .pyc files out of the worktree
        return env

    def _spawn(self, cmd: list[str], log_name: str) -> subprocess.Popen:
        with open(self.logs / log_name, "ab") as log:
            proc = subprocess.Popen(cmd, cwd=LIVE_DIR, stdout=log, stderr=subprocess.STDOUT,
                                    env=self._env(), start_new_session=True)
        self.procs.append(proc)
        return proc

    def url(self, port: int) -> str:
        return f"http://127.0.0.1:{port}/"

    def new_feeds(self, tag: str) -> Path:
        self.counter += 1
        directory = self.feeds_root / f"ux-{tag}-{STAMP}-{os.getpid()}-{self.counter}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def start_server(self, port: int, feeds: Path, tag: str) -> subprocess.Popen:
        cmd = [self.py, "-m", "server", "--port", str(port), "--feeds", str(feeds),
               "--static", str(self.static)]
        return self._spawn(cmd, f"server-{tag}-{port}.log")

    def server_up(self, port: int, timeout: float = 20.0) -> bool:
        def health() -> bool:
            with urllib.request.urlopen(f"{self.url(port)}api/health", timeout=2) as resp:
                return resp.status == 200
        return bool(wait_until(health, timeout))

    def serve(self, port: int, feeds: Path, tag: str) -> subprocess.Popen:
        proc = self.start_server(port, feeds, tag)
        if not self.server_up(port):
            raise RuntimeError(f"server on port {port} did not answer /api/health (logs in {self.logs})")
        return proc

    def api_runs(self, port: int) -> list[dict[str, Any]]:
        try:
            with urllib.request.urlopen(f"{self.url(port)}api/runs", timeout=3) as resp:
                data = json.load(resp)
        except Exception:
            return []
        return data.get("runs", []) if isinstance(data, dict) else data

    def api_status(self, port: int, run_id: str) -> str | None:
        for run in self.api_runs(port):
            if run.get("run_id") == run_id:
                return run.get("status")
        return None

    @staticmethod
    def stop(proc: subprocess.Popen | None, grace: float = 3.0) -> None:
        if proc is None or proc.poll() is not None:
            return
        try:
            os.kill(proc.pid, signal.SIGCONT)  # a SIGSTOPped process cannot act on SIGTERM
        except OSError:
            pass
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    def start_replay(self, src: Path, feeds: Path, speed: float, max_gap: float, tag: str) -> subprocess.Popen:
        cmd = [self.py, "-m", "server.replay", str(src), "--feeds", str(feeds),
               "--speed", str(speed), "--max-gap", str(max_gap)]
        return self._spawn(cmd, f"replay-{tag}.log")

    @staticmethod
    def feeds_now(feeds: Path) -> set[str]:
        return set(glob.glob(str(feeds / "replay-*.ndjson")))

    def new_run(self, feeds: Path, before: set[str], tag: str) -> tuple[Path, str]:
        def fresh() -> Path | None:
            new = sorted(self.feeds_now(feeds) - before)
            return Path(new[0]) if new else None
        path = wait_until(fresh, 15)
        if not path:
            raise RuntimeError(f"{tag}: replay did not create a feed file in {feeds}")
        run_id = wait_until(lambda: feed_info(path)["run_id"], 15)
        if not run_id:
            raise RuntimeError(f"{tag}: feed file {path.name} has no run_start yet")
        return path, run_id

    def reap(self) -> None:
        """Kill children still running at the end of a group (slow replays, servers)."""
        for proc in self.procs:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass

    def new_page(self, browser: Any, reduced: bool = False, extra: str | None = None,
                 recorders: bool = False) -> tuple[Any, Any]:
        kwargs: dict[str, Any] = {"viewport": VIEWPORT}
        if reduced:
            kwargs["reduced_motion"] = "reduce"
        ctx = browser.new_context(**kwargs)
        ctx.add_init_script(INIT_JS)
        if recorders:
            ctx.add_init_script(REC_JS)
        if extra:
            ctx.add_init_script(extra)
        page = ctx.new_page()
        page.on("pageerror", lambda exc: print(f"  page error: {exc}", flush=True))
        return ctx, page

    # ---- reporting ----------------------------------------------------------------------------------
    def check(self, name: str, ok: bool, detail: str) -> None:
        ok = bool(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
        self.results.append((name, ok))

    def scenario(self, name: str, fn: Callable[..., None], *args: Any) -> None:
        """Run one scenario; an exception is a FAIL of that scenario and does not stop the others."""
        try:
            fn(*args)
        except Exception as exc:
            text = str(exc).splitlines()[0][:200] if str(exc) else ""
            self.check(f"{name}: scenario completed", False, f"crashed: {type(exc).__name__}: {text}")

    def shot(self, page: Any, name: str) -> None:
        try:
            page.screenshot(path=str(self.shots / name))
        except Exception as exc:
            print(f"  (screenshot {name} failed: {exc})", flush=True)

    def cleanup(self) -> None:
        self.reap()

    def summary(self) -> bool:
        failed = [name for name, ok in self.results if not ok]
        print(f"SUMMARY: {len(self.results) - len(failed)}/{len(self.results)} checks passed; "
              f"{len(failed)} failed", flush=True)
        for name in failed:
            print(f"  failed: {name}", flush=True)
        print(f"  screenshots: {self.shots}", flush=True)
        print(f"  logs: {self.logs}", flush=True)
        return not failed


# ---- stick: follow mode and the jump button ------------------------------------------------------
def stick_body(h: Harness, page: Any, path: Path, run_id: str) -> None:
    scroller = '[data-testid="transcript-scroll"]'
    jump = page.locator('[data-testid="jump-to-live"]')
    wait_full_ui(page, 60)
    ready = wait_until(lambda: seg_count(page) >= 8 and following(page) == "true", 60, 0.2)
    h.check("stick setup: >= 8 segments with following=true", bool(ready),
            f"segments {seg_count(page)}, following {following(page)!r}")
    if not ready:
        return
    box = page.locator(scroller).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    t0 = time.monotonic()
    page.mouse.wheel(0, -100)
    flipped = wait_until(lambda: following(page) == "false", 0.3, 0.01)
    took_ms = (time.monotonic() - t0) * 1000
    visible = jump.is_visible()
    jtxt = jump_text(page)
    h.check("stick: wheel up detaches follow within 300 ms and shows the jump button",
            bool(flipped) and visible,
            f"following false after {took_ms:.0f} ms, jump visible {visible}, text {jtxt!r}")

    top0, n0 = scroll_top(page), seg_count(page)
    time.sleep(3.0)
    top1, n1 = scroll_top(page), seg_count(page)
    h.check("stick: scrollTop unchanged (+-2 px) for 3 s while segments keep arriving",
            top0 is not None and top1 is not None and abs(top1 - top0) <= 2 and n1 > n0,
            f"scrollTop {top0} -> {top1}, segments {n0} -> {n1}")
    h.shot(page, "stick-1-detached.png")

    jump.click(timeout=5000)
    back = wait_until(lambda: following(page) == "true" and at_bottom(page), 3, 0.1)
    m = metrics(page)
    h.check("stick: jump to live resumes following and reaches the bottom", bool(back),
            f"following {m.get('following')!r}, scrollTop+clientHeight {m.get('top', 0) + m.get('client', 0)}, "
            f"scrollHeight-10 {m.get('height', 0) - 10}")

    click_block(page, 2)
    detached = wait_until(lambda: following(page) == "false", 2, 0.05)
    in_view = wait_until(lambda: page.evaluate(IN_VIEW_JS, 2), 2, 0.1)
    seg_active = attr_of(page, '[data-segment-index="2"]', "data-active")
    tl_active = attr_of(page, '[data-timeline-index="2"]', "data-active")
    h.check("stick: timeline click from the bottom detaches follow, segment 2 in view, active on both",
            bool(detached) and bool(in_view) and seg_active == "true" and tl_active == "true",
            f"following false {bool(detached)}, segment 2 in view {bool(in_view)}, "
            f"data-active segment {seg_active!r}, timeline {tl_active!r}")
    h.shot(page, "stick-2-timeline.png")

    jump.click(timeout=5000)
    wait_until(lambda: following(page) == "true", 3, 0.1)
    page.locator(scroller).focus(timeout=5000)
    page.keyboard.press("PageUp")
    paged = wait_until(lambda: following(page) == "false", 2, 0.05)
    h.check("stick: PageUp in the focused transcript detaches follow", bool(paged),
            f"following {following(page)!r}, scrollTop {scroll_top(page)}")



def stick_end_body(h: Harness, page: Any, run_id: str) -> None:
    scroller = '[data-testid="transcript-scroll"]'
    jump = page.locator('[data-testid="jump-to-live"]')
    wait_full_ui(page, 60)
    ready = wait_until(lambda: seg_count(page) >= 8 and following(page) == "true" and not page_ended(page, run_id),
                       60, 0.2)
    h.check("stick end setup: >= 8 segments with following=true while the run is still live", bool(ready),
            f"segments {seg_count(page)}, following {following(page)!r}, run_end seen {page_ended(page, run_id)}")
    if not ready:
        return
    box = page.locator(scroller).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -100)  # scroll up while the run is still live
    detached = wait_until(lambda: following(page) == "false", 2, 0.05)
    live_at_scroll = not page_ended(page, run_id)
    ended = wait_until(lambda: page_ended(page, run_id), 120, 0.5)
    jt = wait_until(lambda: jump_text(page) == "Jump to end", 3, 0.1)
    jv = jump.is_visible()
    h.check("stick: run_end while scrolled up keeps the jump button visible, reading 'Jump to end'",
            bool(detached) and live_at_scroll and bool(ended) and bool(jt) and jv,
            f"scrolled up while live {bool(detached) and live_at_scroll} (run_end seen at scroll: {not live_at_scroll}), "
            f"run_end seen {bool(ended)}, jump visible {jv}, text {jump_text(page)!r}, following {following(page)!r}")
    h.shot(page, "stick-3-ended-scrolled-up.png")


def stick_end_group(h: Harness, browser: Any) -> None:
    # A fresh replay (speed 0.5, max-gap 30): live through the pre-roll, the setup lag and the scroll-up, so run_end
    # comes after the reader has scrolled up.
    feeds = h.new_feeds("stick-end")
    srv = h.serve(h.port, feeds, "stick-end")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 0.5, 30, "stick-end")
        _path, run_id = h.new_run(feeds, before, "stick-end")
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            h.scenario("stick end", stick_end_body, h, page, run_id)
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


def group_stick(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("stick")
    srv = h.serve(h.port, feeds, "stick")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 0.5, 30, "stick")
        path, run_id = h.new_run(feeds, before, "stick")
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            h.scenario("stick", stick_body, h, page, path, run_id)
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)
    stick_end_group(h, browser)


# ---- reveal: no empty turns, reduced motion, screen-reader announcements -------------------------
def reveal_default_body(h: Harness, browser: Any, feeds: Path) -> None:
    before = h.feeds_now(feeds)
    h.start_replay(h.demo_src, feeds, 1, 30, "reveal-a")
    path, run_id = h.new_run(feeds, before, "reveal-a")
    ctx, page = h.new_page(browser, recorders=True)
    try:
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        wait_full_ui(page, 60)
        samples = empty_hits = max_turns = 0
        first_bad = None
        end = time.monotonic() + 15
        while time.monotonic() < end:
            turns = page.evaluate(TURNS_JS)
            max_turns = max(max_turns, len(turns))
            bad = [t for t in turns if t["empty"]]
            empty_hits += len(bad)
            if bad and first_bad is None:
                first_bad = bad[0]["html"]
            samples += 1
            time.sleep(0.25)
        extra = f", first: {first_bad}" if first_bad else ""
        h.check("reveal: no turn with empty paragraph text (header without text) in 15 s of a speed-1 replay after the pre-roll",
                max_turns > 0 and empty_hits == 0,
                f"samples {samples}, max turns {max_turns}, empty-turn hits {empty_hits}{extra}")
        ended = wait_until(lambda: page_ended(page, run_id), 90, 0.5)
        expected = feed_info(path)["segments"]
        wait_until(lambda: seg_count(page) >= expected, 15, 0.3)  # continuous flow: queue drains <= ~10 s after run_end
        ann = page.evaluate("() => window.__nsAnn || []")
        rendered = seg_count(page)
        partial = [pair for pair in zip(ann, ann[1:]) if pair[1].startswith(pair[0]) and pair[1] != pair[0]]
        example = f", e.g. {partial[0][0][:40]!r} -> {partial[0][1][:40]!r}" if partial else ""
        h.check("reveal: sr-announcer gets one text addition per segment (count == rendered at run_end), no partials",
                bool(ended) and len(ann) == rendered and not partial,
                f"announcements {len(ann)}, segments rendered {rendered} (feed {expected}), "
                f"run_end seen {bool(ended)}, partial pairs {len(partial)}{example}")
        live = attr_of(page, '[data-testid="sr-announcer"]', "aria-live")
        ts_live = attr_of(page, '[data-testid="transcript-scroll"]', "aria-live")
        h.check("reveal: sr-announcer is aria-live=polite; transcript-scroll is not polite",
                live == "polite" and ts_live != "polite",
                f"sr-announcer aria-live {live!r}, transcript-scroll aria-live {ts_live!r}")
        h.shot(page, "reveal-default-end.png")
    finally:
        ctx.close()


def reveal_reduced_body(h: Harness, browser: Any, feeds: Path) -> None:
    before = h.feeds_now(feeds)
    h.start_replay(h.demo_src, feeds, 2, 2, "reveal-b")
    path, run_id = h.new_run(feeds, before, "reveal-b")
    ctx, page = h.new_page(browser, reduced=True, recorders=True)
    try:
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        wait_until(lambda: page_ended(page, run_id), 90, 0.5)
        expect = feed_texts(path)  # read after run_end: at new_run time the file holds only run_start
        wait_until(lambda: seg_count(page) >= len(expect), 15, 0.3)
        rec = page.evaluate("() => window.__nsSegRec || {}")
        problems: list[str] = []
        worst = 0.0
        for seq, length in expect.items():
            r = rec.get(str(seq))
            if r is None:
                problems.append(f"seq {seq} never rendered")
                continue
            full = next((t for t, n in r["log"] if abs(n - length) <= 2), None)
            if full is None:
                problems.append(f"seq {seq} never reached {length} chars")
                continue
            delay = full - r["appear"]
            worst = max(worst, delay)
            if delay > 300:
                problems.append(f"seq {seq} took {delay:.0f} ms")
        rendered = seg_count(page)
        example = f", e.g. {problems[0]}" if problems else ""
        h.check("reveal (reduced motion): each new segment shows its full text within 300 ms",
                not problems and rendered == len(expect),
                f"feed {len(expect)} segments, rendered {rendered}, worst delay {worst:.0f} ms, "
                f"problems {len(problems)}{example}")
        h.shot(page, "reveal-reduced-end.png")
    finally:
        ctx.close()


def group_reveal(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("reveal")
    srv = h.serve(h.port, feeds, "reveal")
    try:
        h.scenario("reveal (default motion)", reveal_default_body, h, browser, feeds)
        h.scenario("reveal (reduced motion)", reveal_reduced_body, h, browser, feeds)
    finally:
        Harness.stop(srv)


# ---- conn: heartbeat, server kill and restart, cold load, empty server, waveform ----------------
def conn_heartbeat(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("conn-heartbeat")
    srv = h.serve(h.port, feeds, "heartbeat")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 0.5, 2, "heartbeat")
        h.new_run(feeds, before, "heartbeat")
        ctx, page = h.new_page(browser, extra="window.__NSLIVE_HEARTBEAT_TIMEOUT_MS = 4000;")
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            wait_full_ui(page, 60)
            wait_until(lambda: seg_count(page) >= 2, 60, 0.3)
            os.kill(srv.pid, signal.SIGSTOP)
            t0 = time.monotonic()
            reconnecting = wait_until(lambda: conn_state(page) == "reconnecting", 10, 0.2)
            took = time.monotonic() - t0
            banner = wait_until(lambda: banner_visible(page), 3, 0.2)
            rs = page.evaluate(RUN_STATE_JS)
            segs = seg_count(page)
            h.check("conn reconnecting: 4 s heartbeat timeout sets data-state reconnecting within 10 s of SIGSTOP",
                    bool(reconnecting), f"conn-state {conn_state(page)!r} after {took:.1f} s")
            h.check("conn reconnecting: banner visible, run-state not Live, transcript keeps segments",
                    bool(banner) and rs.get("text") != "Live" and segs >= 1,
                    f"banner visible {bool(banner)}, run-state {rs}, segments {segs}")
            h.shot(page, "conn-reconnecting.png")
            os.kill(srv.pid, signal.SIGCONT)
            t1 = time.monotonic()
            live = wait_until(lambda: conn_state(page) == "live", 10, 0.2)
            hidden = wait_until(lambda: not banner_visible(page), 3, 0.2)
            h.check("conn resume: SIGCONT returns to live within 10 s and hides the banner",
                    bool(live) and bool(hidden),
                    f"conn-state {conn_state(page)!r} after {time.monotonic() - t1:.1f} s, banner hidden {bool(hidden)}")
            h.shot(page, "conn-resumed.png")
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


def conn_restart(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("conn-restart")
    srv = h.serve(h.port, feeds, "restart-a")
    srv2 = None
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 1, 2, "restart")
        path, run_id = h.new_run(feeds, before, "restart")
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            wait_full_ui(page, 60)
            wait_until(lambda: seg_count(page) >= 3, 60, 0.3)
            before_kill = seg_count(page)
            srv.kill()
            srv.wait(timeout=10)
            banner = wait_until(lambda: banner_visible(page), 10, 0.3)
            time.sleep(3)
            kept = seg_count(page)
            h.check("conn kill: SIGKILL shows the banner and keeps the segments on screen",
                    bool(banner) and kept >= max(3, before_kill),
                    f"banner visible {bool(banner)}, segments before kill {before_kill}, 3 s later {kept}")
            h.shot(page, "conn-killed.png")
            srv2 = h.serve(h.port, feeds, "restart-b")
            live = wait_until(lambda: conn_state(page) == "live", 20, 0.3)
            h.check("conn restart: conn-state live after the server restarts on the same port",
                    bool(live), f"conn-state {conn_state(page)!r}, banner visible {banner_visible(page)}")
            ended = wait_until(lambda: page_ended(page, run_id), 120, 0.5)
            expected = feed_info(path)
            wait_until(lambda: seg_count(page) == expected["segments"], 25, 0.5)
            seqs = page.evaluate(SEQS_JS)
            distinct = set(seqs)
            dup = len(seqs) - len(distinct)
            want = {str(s) for s in expected["seqs"]}
            h.check("conn restart: final segment count == feed file, no duplicate seqs",
                    bool(ended) and len(seqs) == expected["segments"] and dup == 0 and distinct == want,
                    f"rendered {len(seqs)} ({len(distinct)} distinct), feed {expected['segments']}, "
                    f"duplicates {dup}, run_end seen {bool(ended)}")
            h.shot(page, "conn-restarted-end.png")
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)
        if srv2 is not None:
            Harness.stop(srv2)


def conn_cold(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("conn-cold")
    shutil.copyfile(h.zh_src, feeds / "20261021-000000-seed-zh-tw-speech.ndjson")  # finished run, not a replay
    srv = h.serve(h.port, feeds, "cold")
    try:
        ctx = browser.new_context(viewport=VIEWPORT)
        ctx.add_init_script(INIT_JS)
        page = ctx.new_page()
        held: list[Any] = []
        release_at: list[float] = []

        def hold(route: Any) -> None:
            held.append(route)
            if not release_at:
                release_at.append(time.monotonic() + 3.0)

        page.route(lambda url: "/api/stream" in str(url), hold)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            skel_during = False
            onboarding = False
            released = False
            t_end = time.monotonic() + 6.0
            while time.monotonic() < t_end:
                if not released and page.locator('[data-testid="loading-skeleton"]').is_visible():
                    skel_during = True
                if page.locator('[data-testid="onboarding"]').is_visible():
                    onboarding = True
                if release_at and not released and time.monotonic() >= release_at[0]:
                    for route in held:
                        route.continue_()
                    released = True
                time.sleep(0.1)
            rows = wait_until(lambda: seg_count(page) >= 1, 15, 0.3)
            h.check("conn cold load: loading-skeleton visible while the first hello is held for 3 s",
                    skel_during, f"stream requests held {len(held)}, skeleton seen before release {skel_during}")
            h.check("conn cold load: onboarding never shown on a server that has runs",
                    not onboarding, f"onboarding seen {onboarding}")
            h.check("conn cold load: transcript fills after the stream is released",
                    bool(rows), f"segments rendered {seg_count(page)} (zh feed has 46)")
            h.shot(page, "conn-cold-end.png")
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


def conn_empty(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("conn-empty")
    port = h.port + 1
    srv = h.serve(port, feeds, "empty")
    try:
        runs = h.api_runs(port)
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
            onb = wait_until(lambda: page.locator('[data-testid="onboarding"]').is_visible(), 15, 0.3)
            h.check("conn empty server: onboarding visible when the server has zero runs",
                    bool(onb) and not runs, f"runs on server {len(runs)}, onboarding visible {bool(onb)}")
            h.shot(page, "conn-empty-onboarding.png")
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


def conn_waveform_live(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("conn-wave")
    srv = h.serve(h.port, feeds, "wave")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 1, 30, "wave")
        _path, run_id = h.new_run(feeds, before, "wave")
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            kind = None
            ended_then = False
            t0 = time.monotonic()
            while time.monotonic() - t0 < 90:
                kind = page.evaluate(WAVE_JS)
                if kind:
                    ended_then = page_ended(page, run_id)
                    break
                if page_ended(page, run_id):
                    break
                time.sleep(0.3)
            h.shot(page, "conn-waveform-live.png")
            h.check("conn waveform: peaks drawn while the demo is still live (before run_end)",
                    bool(kind) and not ended_then,
                    f"first seen {kind!r} after {time.monotonic() - t0:.1f} s, run_end already seen {ended_then}")
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


def conn_waveform_note(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("conn-note")
    port = h.port + 2
    srv = h.serve(port, feeds, "note")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.noaudio_src, feeds, 3, 2, "note")
        h.new_run(feeds, before, "note")
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
            note = wait_until(lambda: page.locator('[data-testid="waveform-note"]').is_visible(), 30, 0.3)
            wave = page.locator('[data-testid="waveform"]').count()
            h.check("conn waveform-note: a run whose audio file is missing shows waveform-note",
                    bool(note), f"waveform-note visible {bool(note)}, waveform elements {wave}")
            h.shot(page, "conn-waveform-note.png")
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


def group_conn(h: Harness, browser: Any) -> None:
    h.scenario("conn heartbeat", conn_heartbeat, h, browser)
    h.scenario("conn restart", conn_restart, h, browser)
    h.scenario("conn cold load", conn_cold, h, browser)
    h.scenario("conn empty server", conn_empty, h, browser)
    h.scenario("conn waveform (live)", conn_waveform_live, h, browser)
    h.scenario("conn waveform-note", conn_waveform_note, h, browser)


# ---- para: paragraphs, linking, new-run notice ---------------------------------------------------
def para_body(h: Harness, page: Any) -> None:
    turns = page.evaluate(PARA_JS)
    paras = turns[0]["paras"] if len(turns) == 1 else []
    h.check("para: the Chinese run renders as one turn with >= 3 paragraphs",
            len(turns) == 1 and len(paras) >= 3,
            f"turns {len(turns)}, paragraphs per turn {[len(t['paras']) for t in turns]}")
    all_time = bool(paras) and all(p["hasTime"] and p["time"] is not None for p in paras)
    times = [p["time"] for p in paras][:8]
    h.check("para: every paragraph has a paragraph-time with data-start", all_time, f"data-start values {times}")
    secs = [to_seconds(p["time"]) for p in paras]
    inc = bool(secs) and all(s is not None for s in secs) and all(b > a for a, b in zip(secs, secs[1:]))
    h.check("para: paragraph data-start values increase", inc, f"seconds {[s for s in secs][:10]}")
    h.shot(page, "para-paragraphs.png")


def linking_body(h: Harness, page: Any) -> None:
    page.locator('[data-segment-index="4"]').first.hover(timeout=5000)
    hl = wait_until(lambda: highlighted(page, 4), 2, 0.05)
    tl4 = '[data-timeline-index="4"]'
    h.check("para linking: hovering text segment 4 highlights timeline block 4",
            bool(hl), f"timeline 4 data-active {attr_of(page, tl4, 'data-active')!r}, "
                      f"data-hovered {attr_of(page, tl4, 'data-hovered')!r}")
    click_block(page, 5)
    seg5_sel = '[data-segment-index="5"]'
    seg5 = wait_until(lambda: attr_of(page, seg5_sel, "data-active") == "true", 2, 0.05)
    h.check("para linking: clicking timeline block 5 activates text segment 5",
            bool(seg5), f"segment 5 data-active {attr_of(page, seg5_sel, 'data-active')!r}")


def notice_body(h: Harness, page: Any, feeds: Path, zh_run_id: str) -> None:
    open_picker(page)
    page.locator(f'[data-testid="run-option"][data-run-id="{zh_run_id}"]').click(timeout=5000)
    wait_until(lambda: f"run={zh_run_id}" in page.url, 5, 0.1)
    before = h.feeds_now(feeds)
    h.start_replay(h.demo_src, feeds, 1.5, 2, "notice")
    _path, new_id = h.new_run(feeds, before, "notice")
    notice = wait_until(lambda: page.locator('[data-testid="new-run-notice"]').is_visible(), 10, 0.2)
    ntext = text_of(page, '[data-testid="new-run-notice"]') or ""
    kept = f"run={zh_run_id}" in page.url
    h.check("para new-run notice: 'New run started' within 10 s while a finished run is picked; URL ?run= unchanged",
            bool(notice) and "New run started" in ntext and kept,
            f"visible {bool(notice)}, text {ntext[:60]!r}, url {page.url}")
    h.shot(page, "para-new-run-notice.png")
    try:
        # The notice has one button: the localised switch action (en: "Switch"). Click the button, not its text.
        page.locator('[data-testid="new-run-notice"] button').first.click(timeout=5000)
        switched = wait_until(lambda: f"run={new_id}" in page.url, 5, 0.2)
    except Exception as exc:
        switched = False
        print(f"  (switch button click failed: {type(exc).__name__})", flush=True)
    h.check("para new-run notice: the action button shows the new run", bool(switched), f"url {page.url}")


def group_para(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("para")
    srv = h.serve(h.port, feeds, "para")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.zh_src, feeds, 8, 2, "para")
        path, run_id = h.new_run(feeds, before, "para")
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            ended = wait_until(lambda: page_ended(page, run_id), 60, 0.3)
            wait_full_ui(page, 60)
            wait_until(lambda: seg_count(page) >= feed_info(path)["segments"], 15, 0.3)  # queue drains after run_end
            time.sleep(0.5)
            h.check("para setup: Chinese replay at speed 8 reaches run_end on the page", bool(ended),
                    f"run_end seen {bool(ended)}, segments {seg_count(page)}")
            h.scenario("para", para_body, h, page)
            h.scenario("para linking", linking_body, h, page)
            h.scenario("para new-run notice", notice_body, h, page, feeds, run_id)
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


# ---- picker: options, filter, selection, reload, titles -------------------------------------------
def loading_consistent(h: Harness, page: Any, run_id: str) -> tuple[bool, str]:
    """True when the run's option data-status is "loading" exactly while the server reports 0 segments for it.
    The server count is read before and after the option read; a count that moved in between is not judged."""
    def server_segments() -> int | None:
        for run in h.api_runs(h.port):
            if run.get("run_id") == run_id:
                return run.get("segments")
        return None

    before = server_segments()
    opt = next((o for o in page.evaluate(OPTS_JS) if o["runId"] == run_id), None)
    after = server_segments()
    if before is None or opt is None or before != after:
        return False, f"no stable sample: server segments {before} -> {after}, option found {opt is not None}"
    want = "loading" if before == 0 else "live"
    return opt["status"] == want, f"server segments {before}, data-status {opt['status']!r}, want {want!r}"


def picker_body(h: Harness, page: Any, zh_id: str, demo_id: str) -> None:
    wait_full_ui(page, 60)
    open_picker(page)
    wait_until(lambda: page.locator('[data-testid="run-option"]').count() >= 2, 10, 0.2)
    opts = page.evaluate(OPTS_JS)
    statuses = sorted({o["status"] for o in opts if o["status"]})
    h.check("picker: options carry data-status finished and (during the replay) live or loading",
            "finished" in statuses and bool({"live", "loading"} & set(statuses)),
            f"{len(opts)} options, statuses {statuses}")
    # The replay has just started, so the demo option may still be "loading" (0 segments) or already "live".
    verdict = {"ok": False, "detail": "no sample"}

    def settled() -> bool:
        verdict["ok"], verdict["detail"] = loading_consistent(h, page, demo_id)
        return verdict["ok"]

    wait_until(settled, 10, 0.3)
    h.check("picker: demo option data-status is 'loading' iff the server reports 0 segments for the run",
            verdict["ok"], verdict["detail"])
    hhmmss = bool(opts) and all(re.search(r"\d\d:\d\d:\d\d", o["text"]) for o in opts)
    groups = page.locator('[data-testid="run-group"]').count()
    follow = page.locator('[data-testid="run-option-follow"]').count()
    h.check("picker: every option text has HH:MM:SS; at least one run-group",
            hhmmss and groups >= 1, f"HH:MM:SS on all {hhmmss}, groups {groups}, follow-newest options {follow}")
    h.shot(page, "picker-open.png")

    n_all = len(opts)
    page.locator('[data-testid="run-filter"]').fill("zh-tw")
    time.sleep(0.5)
    n_filtered = page.locator('[data-testid="run-option"]').count()
    h.check("picker: typing part of a file name in run-filter reduces the option count",
            1 <= n_filtered < n_all, f"options {n_all} -> {n_filtered} for filter 'zh-tw'")
    page.locator('[data-testid="run-filter"]').fill("")
    time.sleep(0.3)

    open_picker(page)
    page.locator(f'[data-testid="run-option"][data-run-id="{zh_id}"]').click(timeout=5000)
    sel = wait_until(lambda: f"run={zh_id}" in page.url, 5, 0.1)
    title = wait_until(lambda: page.title().startswith("✓ Finished"), 5, 0.2)
    h.check("picker: choosing the finished run sets ?run=<id>; title starts with '✓ Finished'",
            bool(sel) and bool(title), f"url {page.url}, title {page.title()!r}")

    page.reload(wait_until="domcontentloaded")
    time.sleep(1.0)
    restored = f"run={zh_id}" in page.url and page.title().startswith("✓ Finished")
    h.check("picker: page.reload() keeps the same run selected", restored,
            f"url {page.url}, title {page.title()!r}")
    h.shot(page, "picker-reloaded.png")

    open_picker(page)
    page.locator(f'[data-testid="run-option"][data-run-id="{demo_id}"]').click(timeout=5000)
    live = wait_until(lambda: f"run={demo_id}" in page.url and page.title().startswith("● Live"), 8, 0.2)
    h.check("picker: choosing the live run sets ?run=<id>; title starts with '● Live'",
            bool(live), f"url {page.url}, title {page.title()!r}")
    h.shot(page, "picker-live.png")


def group_picker(h: Harness, browser: Any) -> None:
    feeds = h.new_feeds("picker")
    srv = h.serve(h.port, feeds, "picker")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.zh_src, feeds, 8, 2, "picker-zh")
        _path, zh_id = h.new_run(feeds, before, "picker-zh")
        wait_until(lambda: h.api_status(h.port, zh_id) == "finished", 60, 0.5)
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 0.5, 30, "picker-demo")
        _path, demo_id = h.new_run(feeds, before, "picker-demo")
        ctx, page = h.new_page(browser)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            h.scenario("picker", picker_body, h, page, zh_id, demo_id)
        finally:
            ctx.close()
    finally:
        Harness.stop(srv)


GROUP_FUNCS: dict[str, Callable[[Harness, Any], None]] = {
    "stick": group_stick, "reveal": group_reveal, "conn": group_conn, "para": group_para, "picker": group_picker,
}


def _exit_on_term(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)  # unwinds through `finally`, so child processes are killed


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _exit_on_term)
    parser = argparse.ArgumentParser(description="UX checks for noScribe Live.")
    parser.add_argument("--only", default=",".join(GROUPS),
                        help="comma list of groups to run: " + ",".join(GROUPS))
    parser.add_argument("--port", type=int, default=8770,
                        help="port for the main server (+1 empty-feeds server, +2 waveform-note server)")
    parser.add_argument("--static", default=str(DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--python", default=DEFAULT_PY, help="python with the server deps (default: live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir for feeds, shots, logs, src")
    args = parser.parse_args(argv)

    groups = [g.strip() for g in args.only.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        parser.error(f"unknown group(s) {unknown}; choose from {','.join(GROUPS)}")
    busy = [p for p in (args.port, args.port + 1, args.port + 2) if port_busy(p)]
    if busy:
        print(f"FAIL setup: port(s) {busy} already in use; not touching those processes", flush=True)
        return 2
    if not (Path(args.static) / "index.html").is_file():
        print(f"NOTE: {args.static}/index.html is missing; the server serves its placeholder page, "
              "so every UI check will fail", flush=True)

    from playwright.sync_api import sync_playwright  # imported here so --help works without Playwright

    h = Harness(args)
    h.prepare_sources()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for group in groups:
                    print(f"== group {group}", flush=True)
                    try:
                        GROUP_FUNCS[group](h, browser)
                    except Exception as exc:
                        h.check(f"{group}: group completed", False, f"crashed: {exc!r}")
                    finally:
                        h.reap()
            finally:
                browser.close()
    finally:
        h.cleanup()
    return 0 if h.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
