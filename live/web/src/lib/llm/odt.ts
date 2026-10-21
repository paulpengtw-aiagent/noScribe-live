import { strToU8, zipSync } from "fflate";

// OpenDocument (.odt) export built in the page, used when a run has accepted AI corrections. A port of
// live/server/export_odt.py: the same paragraph grouping, speaker names, styles and part order. The caller passes the
// text the page shows (converted to Traditional Chinese and corrected), so nothing is converted here.

const ODT_MEDIA_TYPE = "application/vnd.oasis.opendocument.text";
const PAUSE_BREAK_S = 1.5;
const PARAGRAPH_SOFT_S = 30;
const PARAGRAPH_HARD_S = 45;
const FOOTER = {
  en: "Chinese text is shown in Traditional Chinese (Taiwan).",
  "zh-TW": "中文以臺灣正體字顯示。",
} as const;
// The same ranges as the server's _CJK pattern.
const CJK = /[　-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯가-힯]/u;
const SENTENCE_END = /[。！？!?…][\s"'”’」』）)]*$/;
const NUMBERED_SPEAKER = /^S[0-9]+$/;

/** A segment as the export sees it: `text` is the final text, already converted and corrected. */
export interface OdtSegment {
  index: number;
  start: number;
  end: number;
  speaker: string;
  text: string;
}

export interface OdtInput {
  title: string;
  segments: OdtSegment[];
  lang: "en" | "zh-TW";
  /** Run start in Unix seconds, or null when unknown. */
  startedT: number | null;
  duration: number | null;
  model: string | null;
  speakers: string[];
  /** Extra line under the subtitle, for example the AI corrections note. */
  note?: string;
}

interface Para {
  start: number;
  segs: OdtSegment[];
}

interface Blk {
  speaker: string;
  start: number;
  paras: Para[];
}

/** m:ss, or h:mm:ss from one hour (the page's formatElapsed). */
export function clock(seconds: number): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.trunc(seconds)) : 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Local date and time parts of a Unix-seconds timestamp, as the server formats them in its local time. */
function stampOf(epochSeconds: number): { date: string; hm: string; hms: string } {
  const d = new Date(epochSeconds * 1000);
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  return { date: `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`, hm, hms: `${hm}:${pad2(d.getSeconds())}` };
}

function stemOf(name: string): string {
  const base = name.split(/[\\/]/).pop() || name;
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(0, dot) : base;
}

/** `<audio stem>_YYYY-MM-DD_HHMM.odt` with the run start, or `<stem>.odt` when the start is unknown. Same as the server. */
export function exportFileName(audioName: string | null, runId: string, startedT: number | null): string {
  const stem = stemOf(audioName || runId);
  if (startedT === null) return `${stem}.odt`;
  const d = stampOf(startedT);
  return `${stem}_${d.date}_${d.hm.replace(":", "")}.odt`;
}

/** Groups segments into speaker turns and paragraphs. Port of groupBlocks() in live/server/export_odt.py. */
function groupBlocks(segments: OdtSegment[]): Blk[] {
  const blocks: Blk[] = [];
  let prev: OdtSegment | null = null;
  for (const seg of segments) {
    const overlap = seg.speaker.startsWith("//");
    const speaker = overlap ? seg.speaker.slice(2) : seg.speaker;
    let block: Blk | undefined = blocks[blocks.length - 1];
    if (!block || (!overlap && block.speaker !== speaker)) {
      block = { speaker, start: seg.start, paras: [] };
      blocks.push(block);
    }
    let para: Para | undefined = block.paras[block.paras.length - 1];
    const joins = para !== undefined && prev !== null && (overlap || !startsParagraph(para, prev, seg));
    if (!para || !joins) {
      para = { start: seg.start, segs: [] };
      block.paras.push(para);
    }
    para.segs.push(seg);
    prev = seg;
  }
  return blocks;
}

function startsParagraph(para: Para, prev: OdtSegment, seg: OdtSegment): boolean {
  const length = prev.end - para.start;
  if (seg.start - prev.end >= PAUSE_BREAK_S) return true;
  if (length >= PARAGRAPH_HARD_S) return true;
  return length >= PARAGRAPH_SOFT_S && SENTENCE_END.test(prev.text.trimEnd());
}

function isCjk(ch: string): boolean {
  return CJK.test(ch);
}

/** Whitespace collapsed and trimmed. */
function clean(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/** The separator drawn before a segment: a space between two neighbours of the same script class, none otherwise. */
function boundarySpace(prevText: string, nextText: string): string {
  const a = prevText.trimEnd().slice(-1);
  const b = nextText.trimStart().slice(0, 1);
  if (!a || !b) return "";
  return isCjk(a) === isCjk(b) ? " " : "";
}

function paragraphText(segs: OdtSegment[]): string {
  let out = "";
  let prev: OdtSegment | null = null;
  for (const seg of segs) {
    if (prev) out += boundarySpace(prev.text, seg.text);
    out += clean(seg.text.trim());
    prev = seg;
  }
  return out;
}

/** Port of speaker_name(): "S00" becomes "Speaker 1" (or 講者 1), by order of first appearance. */
function speakerName(label: string, speakers: string[], lang: "en" | "zh-TW"): string {
  const key = label.startsWith("//") ? label.slice(2) : label;
  if (!key) return "";
  if (!NUMBERED_SPEAKER.test(key)) return key;
  const pos = speakers.indexOf(key);
  const number = pos >= 0 ? pos + 1 : Number(key.slice(1)) + 1;
  return lang === "zh-TW" ? `講者 ${number}` : `Speaker ${number}`;
}

/** Removes characters XML cannot carry, then escapes the text. Tab, newline and carriage return are kept. */
function xmlText(text: string): string {
  let safe = "";
  for (const ch of text) {
    const c = ch.codePointAt(0) ?? 0;
    if ((c < 0x20 && c !== 0x09 && c !== 0x0a && c !== 0x0d) || c === 0xfffe || c === 0xffff) continue;
    safe += ch;
  }
  return safe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function para(style: string, text: string): string {
  return `<text:p text:style-name="${style}">${xmlText(text)}</text:p>`;
}

function subtitle(input: OdtInput, duration: number | null): string {
  const labels = input.lang === "zh-TW" ? ["時長", "模型"] : ["Duration", "Model"];
  const parts: string[] = [];
  if (input.startedT !== null) {
    const d = stampOf(input.startedT);
    parts.push(`${d.date} ${d.hm}`);
  }
  if (duration !== null) parts.push(`${labels[0]} ${clock(duration)}`);
  if (input.model) parts.push(`${labels[1]} ${input.model}`);
  return parts.join(" · ");
}

const XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n';
const NS_OFFICE =
  'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" ' +
  'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" ' +
  'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" ' +
  'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" ' +
  'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"';

function contentXml(body: string): string {
  return (
    XML_HEADER +
    `<office:document-content ${NS_OFFICE} office:version="1.2">` +
    "<office:automatic-styles/>" +
    `<office:body><office:text>${body}</office:text></office:body>` +
    "</office:document-content>"
  );
}

function metaXml(title: string, lang: "en" | "zh-TW", startedT: number | null): string {
  const d = stampOf(startedT || Date.now() / 1000);
  const created = `${d.date}T${d.hms}`;
  return (
    XML_HEADER +
    '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" ' +
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" ' +
    'xmlns:dc="http://purl.org/dc/elements/1.1/" office:version="1.2">' +
    "<office:meta>" +
    "<meta:generator>noScribe Live</meta:generator>" +
    `<dc:title>${xmlText(title)}</dc:title>` +
    `<dc:description>${xmlText(FOOTER[lang])}</dc:description>` +
    `<dc:language>${lang}</dc:language>` +
    `<dc:date>${created}</dc:date>` +
    "</office:meta>" +
    "</office:document-meta>"
  );
}

const MANIFEST_XML =
  XML_HEADER +
  '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">' +
  `<manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="${ODT_MEDIA_TYPE}"/>` +
  '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>' +
  '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>' +
  '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>' +
  "</manifest:manifest>";

// Nord palette: ink #2E3440, muted ink #4C566A, frost #5E81AC. Noto Sans TC for Chinese, Inter for Latin.
const STYLES_XML =
  XML_HEADER +
  `<office:document-styles ${NS_OFFICE} office:version="1.2">` +
  "<office:font-face-decls>" +
  '<style:font-face style:name="Noto Sans TC" svg:font-family="\'Noto Sans TC\'" ' +
  'style:font-family-generic="swiss" style:font-pitch="variable"/>' +
  '<style:font-face style:name="Inter" svg:font-family="Inter" ' +
  'style:font-family-generic="swiss" style:font-pitch="variable"/>' +
  '<style:font-face style:name="Geist Mono" svg:font-family="\'Geist Mono\'" ' +
  'style:font-family-generic="modern" style:font-pitch="fixed"/>' +
  "</office:font-face-decls>" +
  "<office:styles>" +
  '<style:default-style style:family="paragraph">' +
  '<style:text-properties style:font-name="Noto Sans TC" ' +
  'fo:font-family="\'Noto Sans TC\', Inter, sans-serif" style:font-name-asian="Noto Sans TC" ' +
  'style:font-family-asian="\'Noto Sans TC\', sans-serif" fo:font-size="11pt" fo:color="#2E3440" ' +
  'fo:language="zh" fo:country="TW"/>' +
  "</style:default-style>" +
  '<style:style style:name="Standard" style:family="paragraph" style:class="text"/>' +
  '<style:style style:name="Title" style:family="paragraph" style:class="text" style:parent-style-name="Standard">' +
  '<style:paragraph-properties fo:margin-bottom="0.12cm"/>' +
  '<style:text-properties fo:font-size="20pt" fo:font-weight="bold" fo:color="#2E3440"/>' +
  "</style:style>" +
  '<style:style style:name="Subtitle" style:family="paragraph" style:class="text" style:parent-style-name="Standard">' +
  '<style:paragraph-properties fo:margin-bottom="0.5cm"/>' +
  '<style:text-properties fo:font-size="10.5pt" fo:color="#4C566A"/>' +
  "</style:style>" +
  '<style:style style:name="Speaker" style:family="paragraph" style:class="text" style:parent-style-name="Standard">' +
  '<style:paragraph-properties fo:margin-top="0.45cm" fo:margin-bottom="0.12cm" fo:keep-with-next="always"/>' +
  '<style:text-properties fo:font-size="11pt" fo:font-weight="bold" fo:color="#5E81AC"/>' +
  "</style:style>" +
  '<style:style style:name="Body" style:family="paragraph" style:class="text" style:parent-style-name="Standard">' +
  '<style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="0.2cm" fo:line-height="150%"/>' +
  '<style:text-properties fo:font-size="11pt" fo:color="#2E3440"/>' +
  "</style:style>" +
  '<style:style style:name="Footer" style:family="paragraph" style:class="text" style:parent-style-name="Standard">' +
  '<style:paragraph-properties fo:margin-top="0.6cm"/>' +
  '<style:text-properties fo:font-size="9pt" fo:color="#4C566A"/>' +
  "</style:style>" +
  '<style:style style:name="Timestamp" style:family="text">' +
  '<style:text-properties style:font-name="Geist Mono" ' +
  'fo:font-family="\'Geist Mono\', \'DejaVu Sans Mono\', monospace" fo:font-size="8.5pt" fo:color="#4C566A"/>' +
  "</style:style>" +
  "</office:styles>" +
  "<office:automatic-styles>" +
  '<style:page-layout style:name="Mpm1"><style:page-layout-properties fo:page-width="21cm" ' +
  'fo:page-height="29.7cm" style:print-orientation="portrait" fo:margin-top="2cm" fo:margin-bottom="2cm" ' +
  'fo:margin-left="2.2cm" fo:margin-right="2.2cm"/></style:page-layout>' +
  "</office:automatic-styles>" +
  '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="Mpm1"/>' +
  "</office:master-styles>" +
  "</office:document-styles>";

/**
 * The whole .odt file as bytes. Part order: mimetype first and stored (ODF 1.2 part 3, section 3.3), then content,
 * styles, meta and manifest. fflate keeps object key order, so the mimetype entry goes first.
 */
export function buildOdt(input: OdtInput): Uint8Array {
  const { lang } = input;
  const segments = [...input.segments].sort((a, b) => a.index - b.index);
  const last = segments[segments.length - 1];
  const duration = input.duration ?? (last ? last.end : null);
  const body: string[] = [para("Title", input.title), para("Subtitle", subtitle(input, duration))];
  if (input.note) body.push(para("Subtitle", input.note));
  for (const block of groupBlocks(segments)) {
    const name = speakerName(block.speaker, input.speakers, lang);
    if (name) body.push(para("Speaker", name));
    for (const p of block.paras) {
      const text = paragraphText(p.segs);
      if (!text) continue;
      body.push(
        `<text:p text:style-name="Body"><text:span text:style-name="Timestamp">${clock(p.start)}</text:span> ${xmlText(text)}</text:p>`,
      );
    }
  }
  body.push(para("Footer", FOOTER[lang]));
  return zipSync({
    mimetype: [strToU8(ODT_MEDIA_TYPE), { level: 0 }],
    "content.xml": [strToU8(contentXml(body.join(""))), { level: 6 }],
    "styles.xml": [strToU8(STYLES_XML), { level: 6 }],
    "meta.xml": [strToU8(metaXml(input.title, lang, input.startedT)), { level: 6 }],
    "META-INF/manifest.xml": [strToU8(MANIFEST_XML), { level: 6 }],
  });
}
