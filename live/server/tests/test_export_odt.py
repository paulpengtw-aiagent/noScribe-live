"""Tests for GET /api/runs/{id}/export.odt and server/export_odt.py.

Run from live/:  .venv/bin/python -m pytest server/tests/test_export_odt.py
"""

from __future__ import annotations

import io
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from odf import teletype
from odf.opendocument import load
from odf.text import P

from server.app import create_app
from server.export_odt import Segment, _paragraph_text, clock, export_filename, group_blocks, to_traditional_tw

ODT = b"application/vnd.oasis.opendocument.text"
TOKEN = "test-token-123"
MANIFEST_NS = "{urn:oasis:names:tc:opendocument:xmlns:manifest:1.0}"


def make_app(tmp_path: Path, token: str | None = None):
    app = create_app(tmp_path / "feeds", tmp_path / "static", token=token)
    return app, app.state.registry


def feed_run(registry, run_id: str, *, audio: str = "/media/demo-en-zh.mp3", finished: bool = True) -> None:
    """A small two-speaker run: S00 talks, then S01 answers after a short pause. Chinese text is Simplified."""
    t0 = time.time()
    events = [
        {"type": "run_start", "t": t0, "seq": 0, "run_id": run_id, "audio_file": audio, "model": "breeze-asr-25"},
        {"type": "audio", "t": t0 + 1, "seq": 1, "run_id": run_id, "duration": 125.0},
        {"type": "diarization", "t": t0 + 2, "seq": 2, "run_id": run_id, "speakers": ["S00", "S01"]},
        {"type": "segment", "t": t0 + 3, "seq": 3, "run_id": run_id, "index": 0, "start": 0.0, "end": 2.0,
         "speaker": "S00", "text": "Hello there."},
        {"type": "segment", "t": t0 + 4, "seq": 4, "run_id": run_id, "index": 1, "start": 2.2, "end": 4.0,
         "speaker": "S00", "text": "这是一个测试。"},
        {"type": "segment", "t": t0 + 5, "seq": 5, "run_id": run_id, "index": 2, "start": 5.0, "end": 7.0,
         "speaker": "S01", "text": "软件和头发。"},
    ]
    if finished:
        events.append({"type": "run_end", "t": t0 + 6, "seq": 6, "run_id": run_id, "status": "finished"})
    for event in events:
        registry.ingest(event, server_t=time.time())


def odt_parts(body: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def paragraphs_of(path: Path) -> list[str]:
    doc = load(str(path))
    return [teletype.extractText(p) for p in doc.getElementsByType(P)]


def seg(index: int, start: float, end: float, speaker: str = "S00", text: str = "x.") -> Segment:
    return Segment(index=index, start=start, end=end, speaker=speaker, text=text)


# --- endpoint: status codes, headers, language -------------------------------------------------------------------------


def test_unknown_run_is_404(tmp_path):
    app, _ = make_app(tmp_path)
    resp = TestClient(app).get("/api/runs/nope/export.odt")
    assert resp.status_code == 404
    assert resp.json() == {"error": "unknown run"}


def test_running_run_is_409_json(tmp_path):
    app, registry = make_app(tmp_path)
    feed_run(registry, "live-1", finished=False)
    resp = TestClient(app).get("/api/runs/live-1/export.odt")
    assert resp.status_code == 409
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["error"] == "run is still running"
    assert resp.json()["status"] == "running"


def test_finished_run_is_odt_with_attachment_name(tmp_path):
    app, registry = make_app(tmp_path)
    feed_run(registry, "done-1")
    resp = TestClient(app).get("/api/runs/done-1/export.odt?lang=en")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.oasis.opendocument.text"
    stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime(registry.get("done-1").started_t))
    assert resp.headers["content-disposition"] == f'attachment; filename="demo-en-zh_{stamp}.odt"'
    assert resp.content.startswith(b"PK")


def test_non_ascii_audio_name_gets_rfc5987_filename(tmp_path):
    app, registry = make_app(tmp_path)
    feed_run(registry, "uni-1", audio="/media/採訪 demo.mp3")
    resp = TestClient(app).get("/api/runs/uni-1/export.odt?lang=en")
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=")
    stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime(registry.get("uni-1").started_t))
    assert f"filename*=UTF-8''%E6%8E%A1%E8%A8%AA%20demo_{stamp}.odt" in disposition
    assert disposition.isascii()


def test_lang_defaults_follow_accept_language(tmp_path):
    app, registry = make_app(tmp_path)
    feed_run(registry, "lang-1")
    client = TestClient(app)
    zh = client.get("/api/runs/lang-1/export.odt", headers={"Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"})
    en = client.get("/api/runs/lang-1/export.odt", headers={"Accept-Language": "fr-FR,fr;q=0.9"})
    forced = client.get("/api/runs/lang-1/export.odt?lang=en", headers={"Accept-Language": "zh-TW"})
    assert "講者 1" in " ".join(paragraphs_of(_write(tmp_path, "zh.odt", zh.content)))
    assert "Speaker 1" in " ".join(paragraphs_of(_write(tmp_path, "en.odt", en.content)))
    assert "Speaker 1" in " ".join(paragraphs_of(_write(tmp_path, "forced.odt", forced.content)))


def test_token_gate_covers_the_export_route(tmp_path):
    app, registry = make_app(tmp_path, token=TOKEN)
    feed_run(registry, "gated-1")
    client = TestClient(app)
    assert client.get("/api/runs/gated-1/export.odt").status_code == 401
    ok = client.get("/api/runs/gated-1/export.odt?lang=en", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "application/vnd.oasis.opendocument.text"


# --- file structure ---------------------------------------------------------------------------------------------------


def _download(tmp_path: Path, lang: str = "en") -> bytes:
    app, registry = make_app(tmp_path)
    feed_run(registry, "file-1")
    resp = TestClient(app).get(f"/api/runs/file-1/export.odt?lang={lang}")
    assert resp.status_code == 200
    return resp.content


def _write(tmp_path: Path, name: str, body: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(body)
    return path


def test_mimetype_is_first_and_stored(tmp_path):
    body = _download(tmp_path)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        infos = archive.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == ODT
    # Stored means the bytes sit uncompressed right after the 30-byte local header and the 8-byte name.
    assert body[38:38 + len(ODT)] == ODT


def test_all_parts_present_and_xml_parses(tmp_path):
    parts = odt_parts(_download(tmp_path))
    assert set(parts) == {"mimetype", "content.xml", "styles.xml", "meta.xml", "META-INF/manifest.xml"}
    for name in ("content.xml", "styles.xml", "meta.xml", "META-INF/manifest.xml"):
        ET.fromstring(parts[name])  # raises on malformed XML


def test_manifest_lists_every_part(tmp_path):
    parts = odt_parts(_download(tmp_path))
    root = ET.fromstring(parts["META-INF/manifest.xml"])
    listed = {entry.get(f"{MANIFEST_NS}full-path") for entry in root.iter(f"{MANIFEST_NS}file-entry")}
    assert {"/", "content.xml", "styles.xml", "meta.xml"} <= listed
    assert root.find(f"{MANIFEST_NS}file-entry[@{MANIFEST_NS}full-path='/']").get(
        f"{MANIFEST_NS}media-type"
    ) == "application/vnd.oasis.opendocument.text"


def test_styles_are_named_and_nord_coloured(tmp_path):
    styles = odt_parts(_download(tmp_path))["styles.xml"].decode("utf-8")
    for name in ("Title", "Subtitle", "Speaker", "Timestamp", "Body"):
        assert f'style:name="{name}"' in styles
    assert "#5E81AC" in styles and "#4C566A" in styles
    assert "Noto Sans TC" in styles and "Inter" in styles


def test_odfpy_reads_speakers_timestamps_and_traditional_text(tmp_path):
    body = _download(tmp_path, lang="en")
    texts = paragraphs_of(_write(tmp_path, "read.odt", body))
    joined = "\n".join(texts)
    assert texts[0] == "demo-en-zh.mp3"
    assert "Speaker 1" in texts and "Speaker 2" in texts
    assert "Duration 2:05" in texts[1] and "Model breeze-asr-25" in texts[1]
    assert "0:00 Hello there." in joined
    # Simplified input comes out Traditional (Taiwan); the converted characters are present, the source ones are not.
    assert "這是一個測試。" in joined
    assert "軟件和頭髮。" in joined
    assert "这是" not in joined and "软件" not in joined
    assert "Chinese text is shown in Traditional Chinese (Taiwan)." in joined


def test_zh_document_uses_chinese_labels(tmp_path):
    texts = paragraphs_of(_write(tmp_path, "zh.odt", _download(tmp_path, lang="zh-TW")))
    assert "講者 1" in texts and "講者 2" in texts
    assert any("時長 2:05" in t for t in texts)
    assert "中文以臺灣正體字顯示。" in texts


# The closing note: plain language, the same text as the body footer and as meta.xml dc:description.
NOTE = {"en": "Chinese text is shown in Traditional Chinese (Taiwan).", "zh-TW": "中文以臺灣正體字顯示。"}


@pytest.mark.parametrize("lang", ["en", "zh-TW"])
def test_closing_note_is_plain_language_in_body_and_meta(tmp_path, lang):
    body = _download(tmp_path, lang=lang)
    parts = odt_parts(body)
    assert NOTE[lang] in paragraphs_of(_write(tmp_path, "note.odt", body))
    description = ET.fromstring(parts["meta.xml"]).find(".//{http://purl.org/dc/elements/1.1/}description")
    assert description is not None and description.text == NOTE[lang]
    for name in ("content.xml", "meta.xml"):
        xml = parts[name].decode("utf-8")
        assert "OpenCC" not in xml and "s2tw" not in xml


# --- paragraph grouping mirrors web/src/lib/transcript-blocks.ts ----------------------------------------------------


def test_speaker_change_starts_a_new_block():
    blocks = group_blocks([seg(0, 0, 1, "S00"), seg(1, 1.1, 2, "S01")])
    assert [b.speaker for b in blocks] == ["S00", "S01"]


def test_overlap_segment_joins_the_current_block_inline():
    blocks = group_blocks([seg(0, 0, 1, "S00"), seg(1, 1.1, 2, "//S01"), seg(2, 2.1, 3, "S00")])
    assert len(blocks) == 1
    assert len(blocks[0].paragraphs[0].segments) == 3


def test_pause_of_one_and_a_half_seconds_breaks_a_paragraph():
    short_gap = group_blocks([seg(0, 0, 1), seg(1, 2.4, 3)])        # gap 1.4 s: same paragraph
    long_gap = group_blocks([seg(0, 0, 1), seg(1, 2.5, 3)])         # gap 1.5 s: new paragraph
    assert len(short_gap[0].paragraphs) == 1
    assert len(long_gap[0].paragraphs) == 2


def test_soft_limit_breaks_only_after_a_sentence_end():
    # The break is judged on the previous segment end minus the paragraph start: 31 s here.
    no_end = [seg(0, 0, 31, text="a long clause"), seg(1, 31.1, 35, text="still going")]
    with_end = [seg(0, 0, 31, text="a long clause?"), seg(1, 31.1, 35, text="next")]
    assert len(group_blocks(no_end)[0].paragraphs) == 1   # 31 s, but no sentence end at the boundary
    assert len(group_blocks(with_end)[0].paragraphs) == 2


def test_hard_limit_breaks_at_45_seconds_regardless():
    segs = [seg(0, 0, 46, text="no stop"), seg(1, 46.1, 50, text="more")]
    assert len(group_blocks(segs)[0].paragraphs) == 2


# --- Simplified to Traditional (Taiwan) ---------------------------------------------------------------------------


def test_conversion_applies_only_to_cjk_text():
    assert to_traditional_tw("这是") == "這是"
    assert to_traditional_tw("Plain English 123") == "Plain English 123"


def test_export_filename_stamps_the_run_start_in_local_time():
    started = time.mktime((2026, 10, 21, 18, 54, 0, 0, 0, -1))
    assert export_filename("04-codeswitch-zh-en.mp3", started) == "04-codeswitch-zh-en_2026-10-21_1854.odt"
    assert export_filename("/media/04-codeswitch-zh-en.mp3", None) == "04-codeswitch-zh-en.odt"


def test_clock_is_m_ss_then_h_mm_ss_like_the_screen():
    assert clock(0) == "0:00"
    assert clock(5.9) == "0:05"
    assert clock(65) == "1:05"
    assert clock(3599) == "59:59"
    assert clock(3600) == "1:00:00"
    assert clock(3723.9) == "1:02:03"


def test_segments_join_with_a_space_only_between_two_cjk_or_two_non_cjk_neighbours():
    segs = [seg(0, 0, 1, text="这是"), seg(1, 1, 2, text="一个"), seg(2, 2, 3, text="test"), seg(3, 3, 4, text="好")]
    assert _paragraph_text(segs) == "這是 一個test好"
    assert _paragraph_text([seg(0, 0, 1, text="Hello"), seg(1, 1, 2, text="there.")]) == "Hello there."
    # An empty segment between two neighbours breaks the join, as on the page (neighbours are compared raw).
    assert _paragraph_text([seg(0, 0, 1, text="软件"), seg(1, 1, 2, text=""), seg(2, 2, 3, text="好")]) == "軟件好"


def test_variant_characters_match_the_page_for_common_words():
    # Expected values are the page's converter output (opencc-js cn to tw), computed with node.
    page = {
        "櫃台": "櫃臺", "柜台": "櫃檯", "台灣": "臺灣", "台湾": "臺灣", "后来": "後來", "里面": "裡面",
        "干净": "乾淨", "头发": "頭髮", "软件": "軟件", "数据库": "數據庫", "网络": "網絡", "面条": "麵條",
        "理发": "理髮", "后台": "後臺", "周末": "週末", "干燥": "乾燥", "复制粘贴": "複製粘貼",
        "这是一个测试。": "這是一個測試。",
    }
    for simplified, expected in page.items():
        assert to_traditional_tw(simplified) == expected, simplified


def test_known_gap_single_variant_characters_follow_s2tw():
    # opencc-js keeps 托 (and 栗, 樑, 硷 differ too); s2tw converts it. The gap is listed in live/README.md.
    assert to_traditional_tw("托") == "託"


# --- LibreOffice smoke test (skipped when soffice is not installed) -----------------------------------------------


@pytest.mark.skipif(shutil.which("soffice") is None, reason="soffice (LibreOffice) is not installed")
def test_odt_converts_to_pdf_with_libreoffice(tmp_path):
    odt = _write(tmp_path, "smoke.odt", _download(tmp_path, lang="zh-TW"))
    out_dir = tmp_path / "pdf"
    out_dir.mkdir()
    subprocess.run(
        [
            "soffice",
            "-env:UserInstallation=file:///tmp/nslive-lo-profile",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(odt),
        ],
        check=False,
        timeout=60,
        capture_output=True,
    )
    assert (out_dir / "smoke.pdf").is_file()
