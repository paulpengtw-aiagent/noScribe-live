"""OpenDocument (.odt) export of one transcript run. Stdlib only at runtime: zipfile plus XML strings.

Paragraph grouping mirrors web/src/lib/transcript-blocks.ts (a new turn on a speaker change; a paragraph breaks
at a pause of 1.5 s, after a sentence end once it is 30 s long, and at 45 s regardless). Simplified to Traditional
(Taiwan) mirrors web/src/lib/zh-tw.ts: OpenCC s2tw here, opencc-js cn to tw in the page. Text is converted only
when it has CJK characters, and a conversion that changes the UTF-16 length is dropped, as the page does.
"""

from __future__ import annotations

import io
import re
import threading
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import quote
from xml.sax.saxutils import escape

from opencc import OpenCC

ODT_MEDIA_TYPE = "application/vnd.oasis.opendocument.text"
LANGS = ("en", "zh-TW")

PAUSE_BREAK_S = 1.5        # a new paragraph after a pause this long between segments
PARAGRAPH_SOFT_S = 30.0    # past this length, a paragraph breaks at the next sentence end
PARAGRAPH_HARD_S = 45.0    # past this length, a paragraph breaks at the next segment boundary

FOOTER = {
    "en": "Chinese shown in Traditional (Taiwan), converted from the transcript for display",
    "zh-TW": "中文以繁體中文（台灣）顯示，由轉錄文字轉換而來，僅供閱讀",
}

# The same ranges as CJK_CHAR in web/src/lib/format.ts.
_CJK = re.compile("[　-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯가-힯]")
_SENTENCE_END = re.compile(r'[。！？!?…][\s"\'”’」』）)]*\Z')
_NUMBERED_LABEL = re.compile(r"S[0-9]+")
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

_converter: OpenCC | None = None
_converter_lock = threading.Lock()


@dataclass(frozen=True)
class Segment:
    index: int
    start: float
    end: float
    speaker: str
    text: str


@dataclass
class Paragraph:
    start: float
    segments: list[Segment] = field(default_factory=list)


@dataclass
class Block:
    speaker: str   # speaker key without the "//" overlap mark; "" when the segment had none
    start: float
    paragraphs: list[Paragraph] = field(default_factory=list)


def resolve_lang(lang: str | None, accept_language: str) -> str:
    """The ``lang`` query value when it is a known locale, else zh-TW for an Accept-Language starting with zh."""
    if lang in LANGS:
        return lang
    return "zh-TW" if accept_language.strip().lower().startswith("zh") else "en"


def segments_from_events(events: Iterable[dict[str, Any]]) -> list[Segment]:
    """Segment events as the page keeps them: one per index (the last event wins), sorted by index."""
    by_index: dict[int, Segment] = {}
    for ev in events:
        if ev.get("type") != "segment":
            continue
        index = ev.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        by_index[index] = Segment(
            index=index,
            start=_float(ev.get("start")),
            end=_float(ev.get("end")),
            speaker=str(ev.get("speaker") or ""),
            text=str(ev.get("text") or ""),
        )
    return [by_index[i] for i in sorted(by_index)]


def _float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0  # NaN becomes 0


def _ends_sentence(text: str) -> bool:
    return _SENTENCE_END.search(text.rstrip()) is not None


def _starts_paragraph(paragraph: Paragraph, prev: Segment, seg: Segment) -> bool:
    length = prev.end - paragraph.start
    if seg.start - prev.end >= PAUSE_BREAK_S:
        return True
    if length >= PARAGRAPH_HARD_S:
        return True
    return length >= PARAGRAPH_SOFT_S and _ends_sentence(prev.text)


def group_blocks(segments: list[Segment]) -> list[Block]:
    """Port of buildBlocks() in web/src/lib/transcript-blocks.ts."""
    blocks: list[Block] = []
    prev: Segment | None = None
    for seg in segments:
        overlap = seg.speaker.startswith("//")
        speaker = seg.speaker[2:] if overlap else seg.speaker
        block = blocks[-1] if blocks else None
        if block is None or (not overlap and block.speaker != speaker):
            block = Block(speaker=speaker, start=seg.start)
            blocks.append(block)
        paragraph = block.paragraphs[-1] if block.paragraphs else None
        joins = paragraph is not None and prev is not None and (overlap or not _starts_paragraph(paragraph, prev, seg))
        if paragraph is None or not joins:
            paragraph = Paragraph(start=seg.start)
            block.paragraphs.append(paragraph)
        paragraph.segments.append(seg)
        prev = seg
    return blocks


def _is_cjk(ch: str) -> bool:
    return _CJK.match(ch) is not None


def _clean(text: str) -> str:
    """Whitespace collapsed and trimmed: ODT collapses runs of spaces anyway, and this keeps the joins exact."""
    return " ".join(text.split())


def _needs_space(prev_text: str, next_text: str) -> bool:
    """Port of needsSpaceBetween(): a space joins two non-CJK neighbours."""
    if not prev_text or not next_text:
        return False
    return not _is_cjk(prev_text[-1]) and not _is_cjk(next_text[0])


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def to_traditional_tw(text: str) -> str:
    """Display conversion, as in web/src/lib/zh-tw.ts: CJK text only, and only when the length is unchanged."""
    global _converter
    if _CJK.search(text) is None:
        return text
    if _converter is None:
        with _converter_lock:
            if _converter is None:
                _converter = OpenCC("s2tw")
    out = _converter.convert(text)
    return out if _utf16_len(out) == _utf16_len(text) else text


def speaker_name(label: str, speakers: list[str], lang: str) -> str:
    """Port of speakerDisplayName() with the zh-TW wording. "S00" -> "Speaker 1" by order of first appearance."""
    key = label[2:] if label.startswith("//") else label
    if not key:
        return ""
    if not _NUMBERED_LABEL.fullmatch(key):
        return key
    number = speakers.index(key) + 1 if key in speakers else int(key[1:]) + 1
    return f"講者 {number}" if lang == "zh-TW" else f"Speaker {number}"


def timecode(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def clock(seconds: float) -> str:
    """m:ss, or h:mm:ss from one hour (the page's formatElapsed)."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def stem_of(name: str) -> str:
    """File name without its extension; accepts both / and \\ separators, as the feed does."""
    base = re.split(r"[\\/]", name)[-1]
    root, dot, _ext = base.rpartition(".")
    return root if dot and root else base


def content_disposition(filename: str) -> str:
    """attachment with the file name; RFC 5987 filename* too when the name is not plain ASCII."""
    plain = filename.isascii() and not any(ch in filename for ch in '"\\') and all(
        32 <= ord(ch) < 127 for ch in filename
    )
    if plain:
        return f'attachment; filename="{filename}"'
    fallback = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _xml_text(text: str) -> str:
    return escape(_XML_INVALID.sub("", text))


def _paragraph(style: str, text: str) -> str:
    return f'<text:p text:style-name="{style}">{_xml_text(text)}</text:p>'


def _subtitle(started_t: float | None, duration: float | None, model: str | None, lang: str) -> str:
    labels = {"en": ("Duration", "Model"), "zh-TW": ("時長", "模型")}[lang]
    parts: list[str] = []
    if started_t is not None:
        parts.append(time.strftime("%Y-%m-%d %H:%M", time.localtime(started_t)))
    if duration is not None:
        parts.append(f"{labels[0]} {clock(duration)}")
    if model:
        parts.append(f"{labels[1]} {model}")
    return " · ".join(parts)


def _paragraph_text(segments: list[Segment]) -> str:
    out: list[str] = []
    prev = ""
    for seg in segments:
        piece = _clean(seg.text)
        if not piece:
            continue
        piece = to_traditional_tw(piece)
        if prev and _needs_space(prev, piece):
            out.append(" ")
        out.append(piece)
        prev = piece
    return "".join(out)


def build_odt(
    *,
    title: str,
    segments: list[Segment],
    lang: str,
    started_t: float | None = None,
    duration: float | None = None,
    model: str | None = None,
    speakers: list[str] | None = None,
) -> bytes:
    """The whole .odt file as bytes. Part order: mimetype (first, stored), content, styles, meta, manifest."""
    speakers = speakers or []
    if duration is None and segments:
        duration = segments[-1].end
    body: list[str] = [
        _paragraph("Title", title),
        _paragraph("Subtitle", _subtitle(started_t, duration, model, lang)),
    ]
    for block in group_blocks(segments):
        name = speaker_name(block.speaker, speakers, lang)
        if name:
            body.append(_paragraph("Speaker", name))
        for paragraph in block.paragraphs:
            text = _paragraph_text(paragraph.segments)
            if not text:
                continue
            body.append(
                '<text:p text:style-name="Body">'
                f'<text:span text:style-name="Timestamp">{timecode(paragraph.start)}</text:span> {_xml_text(text)}'
                "</text:p>"
            )
    body.append(_paragraph("Footer", FOOTER[lang]))

    parts: list[tuple[str, str]] = [
        ("content.xml", _content_xml("".join(body))),
        ("styles.xml", _STYLES_XML),
        ("meta.xml", _meta_xml(title, lang, started_t)),
        ("META-INF/manifest.xml", _MANIFEST_XML),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        # The mimetype entry must come first and must not be compressed (ODF 1.2 part 3, section 3.3).
        archive.writestr(zipfile.ZipInfo("mimetype"), ODT_MEDIA_TYPE, compress_type=zipfile.ZIP_STORED)
        for name, data in parts:
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'
_NS_OFFICE = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
)


def _content_xml(body: str) -> str:
    return (
        _XML_HEADER
        + f'<office:document-content {_NS_OFFICE} office:version="1.2">'
        + "<office:automatic-styles/>"
        + f"<office:body><office:text>{body}</office:text></office:body>"
        + "</office:document-content>"
    )


def _meta_xml(title: str, lang: str, started_t: float | None) -> str:
    created = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started_t or time.time()))
    return (
        _XML_HEADER
        + '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        + 'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
        + 'xmlns:dc="http://purl.org/dc/elements/1.1/" office:version="1.2">'
        + "<office:meta>"
        + "<meta:generator>noScribe Live</meta:generator>"
        + f"<dc:title>{_xml_text(title)}</dc:title>"
        + f"<dc:description>{_xml_text(FOOTER[lang])}</dc:description>"
        + f"<dc:language>{lang}</dc:language>"
        + f"<dc:date>{created}</dc:date>"
        + "</office:meta>"
        + "</office:document-meta>"
    )


_MANIFEST_XML = (
    _XML_HEADER
    + '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
    + f'<manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="{ODT_MEDIA_TYPE}"/>'
    + '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
    + '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
    + '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
    + "</manifest:manifest>"
)

# Nord palette: ink #2E3440, muted ink #4C566A, frost #5E81AC. Noto Sans TC for Chinese, Inter for Latin.
_STYLES_XML = (
    _XML_HEADER
    + f"<office:document-styles {_NS_OFFICE} office:version=\"1.2\">"
    + "<office:font-face-decls>"
    + '<style:font-face style:name="Noto Sans TC" svg:font-family="\'Noto Sans TC\'" '
    + 'style:font-family-generic="swiss" style:font-pitch="variable"/>'
    + '<style:font-face style:name="Inter" svg:font-family="Inter" '
    + 'style:font-family-generic="swiss" style:font-pitch="variable"/>'
    + '<style:font-face style:name="Geist Mono" svg:font-family="\'Geist Mono\'" '
    + 'style:font-family-generic="modern" style:font-pitch="fixed"/>'
    + "</office:font-face-decls>"
    + "<office:styles>"
    + "<style:default-style style:family=\"paragraph\">"
    + '<style:text-properties style:font-name="Noto Sans TC" '
    + 'fo:font-family="\'Noto Sans TC\', Inter, sans-serif" style:font-name-asian="Noto Sans TC" '
    + 'style:font-family-asian="\'Noto Sans TC\', sans-serif" fo:font-size="11pt" fo:color="#2E3440" '
    + 'fo:language="zh" fo:country="TW"/>'
    + "</style:default-style>"
    + '<style:style style:name="Standard" style:family="paragraph" style:class="text"/>'
    + '<style:style style:name="Title" style:family="paragraph" style:class="text" style:parent-style-name="Standard">'
    + '<style:paragraph-properties fo:margin-bottom="0.12cm"/>'
    + '<style:text-properties fo:font-size="20pt" fo:font-weight="bold" fo:color="#2E3440"/>'
    + "</style:style>"
    + '<style:style style:name="Subtitle" style:family="paragraph" style:class="text" style:parent-style-name="Standard">'
    + '<style:paragraph-properties fo:margin-bottom="0.5cm"/>'
    + '<style:text-properties fo:font-size="10.5pt" fo:color="#4C566A"/>'
    + "</style:style>"
    + '<style:style style:name="Speaker" style:family="paragraph" style:class="text" style:parent-style-name="Standard">'
    + '<style:paragraph-properties fo:margin-top="0.45cm" fo:margin-bottom="0.12cm" fo:keep-with-next="always"/>'
    + '<style:text-properties fo:font-size="11pt" fo:font-weight="bold" fo:color="#5E81AC"/>'
    + "</style:style>"
    + '<style:style style:name="Body" style:family="paragraph" style:class="text" style:parent-style-name="Standard">'
    + '<style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="0.2cm" fo:line-height="150%"/>'
    + '<style:text-properties fo:font-size="11pt" fo:color="#2E3440"/>'
    + "</style:style>"
    + '<style:style style:name="Footer" style:family="paragraph" style:class="text" style:parent-style-name="Standard">'
    + '<style:paragraph-properties fo:margin-top="0.6cm"/>'
    + '<style:text-properties fo:font-size="9pt" fo:color="#4C566A"/>'
    + "</style:style>"
    + '<style:style style:name="Timestamp" style:family="text">'
    + '<style:text-properties style:font-name="Geist Mono" '
    + 'fo:font-family="\'Geist Mono\', \'DejaVu Sans Mono\', monospace" fo:font-size="8.5pt" fo:color="#4C566A"/>'
    + "</style:style>"
    + "</office:styles>"
    + "<office:automatic-styles>"
    + '<style:page-layout style:name="Mpm1"><style:page-layout-properties fo:page-width="21cm" '
    + 'fo:page-height="29.7cm" style:print-orientation="portrait" fo:margin-top="2cm" fo:margin-bottom="2cm" '
    + 'fo:margin-left="2.2cm" fo:margin-right="2.2cm"/></style:page-layout>'
    + "</office:automatic-styles>"
    + '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="Mpm1"/>'
    + "</office:master-styles>"
    + "</office:document-styles>"
)
