import type { ContextDoc } from "./types";

/** File types the context panel accepts. Keep in sync with the file input's `accept` attribute. */
export const CONTEXT_ACCEPT = ".docx,.pdf,.txt,.md";

/** The document kind for a file name, or null when the extension is not supported. */
export function docKind(name: string): ContextDoc["kind"] | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".docx")) return "docx";
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".txt") || lower.endsWith(".md")) return "text";
  return null;
}

const CJK_CHAR = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\p{Script=Bopomofo}]/u;

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("Reading the file was cancelled.", "AbortError");
}

/** Raw text of a .docx through mammoth. Loaded only when a Word file is parsed. */
async function readDocx(file: File, signal?: AbortSignal): Promise<string> {
  const mammoth = await import("mammoth");
  throwIfAborted(signal);
  const arrayBuffer = await file.arrayBuffer();
  throwIfAborted(signal);
  const { value } = await mammoth.extractRawText({ arrayBuffer });
  return value;
}

/** The fields of a pdf.js text item that this module reads. */
interface PdfTextItem {
  str: string;
  hasEOL?: boolean;
  transform?: number[];
  width?: number;
}

function isTextItem(item: unknown): item is PdfTextItem {
  return typeof item === "object" && item !== null && typeof (item as { str?: unknown }).str === "string";
}

/** Two runs share a line when their baselines (transform[5]) match. Without positions, assume they do. */
function sameLine(a: PdfTextItem, b: PdfTextItem): boolean {
  const ya = a.transform?.[5];
  const yb = b.transform?.[5];
  return typeof ya !== "number" || typeof yb !== "number" || Math.abs(ya - yb) < 1;
}

/** A gap between two runs on one line is a word space. CJK text never gets a space between characters. */
function needsSpace(out: string, prev: PdfTextItem, next: PdfTextItem): boolean {
  const last = out.charAt(out.length - 1);
  const first = next.str.charAt(0);
  if (!last || /\s/.test(last) || /\s/.test(first)) return false;
  if (CJK_CHAR.test(last) || CJK_CHAR.test(first)) return false;
  const x0 = prev.transform?.[4];
  const x1 = next.transform?.[4];
  const width = prev.width;
  if (typeof x0 !== "number" || typeof x1 !== "number" || typeof width !== "number") return false;
  return x1 - (x0 + width) > 1;
}

/** Joins one page's text items: a new line where the baseline changes or the item ends a line. */
function pageText(items: readonly unknown[]): string {
  let out = "";
  let prev: PdfTextItem | null = null;
  for (const raw of items) {
    if (!isTextItem(raw)) continue;
    if (raw.str.length > 0) {
      if (prev && !sameLine(prev, raw)) {
        if (!out.endsWith("\n")) out += "\n";
      } else if (prev && needsSpace(out, prev, raw)) {
        out += " ";
      }
      out += raw.str;
      prev = raw;
    }
    if (raw.hasEOL && !out.endsWith("\n")) out += "\n";
  }
  return out;
}

/** Text layer of a .pdf through pdf.js. Loaded only when a PDF is parsed. */
async function readPdf(file: File, signal?: AbortSignal): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  if (!pdfjs.GlobalWorkerOptions.workerSrc) {
    pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
  }
  throwIfAborted(signal);
  const data = new Uint8Array(await file.arrayBuffer());
  throwIfAborted(signal);
  const task = pdfjs.getDocument({ data });
  const doc = await task.promise;
  try {
    const pages: string[] = [];
    for (let n = 1; n <= doc.numPages; n += 1) {
      throwIfAborted(signal);
      const page = await doc.getPage(n);
      const content = await page.getTextContent();
      pages.push(pageText(content.items));
      page.cleanup();
    }
    return pages.join("\n\n");
  } finally {
    // Destroying the loading task tears down the document and its worker.
    await task.destroy();
  }
}

/** Plain text (.txt, .md). UTF-8 first; a file that is not valid UTF-8 is decoded as Big5, common for Traditional Chinese notes. */
async function readText(file: File): Promise<string> {
  const bytes = await file.arrayBuffer();
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder("big5").decode(bytes);
  }
}

/**
 * Extracts plain text from a context file. Rejects with an Error whose message is readable when the
 * type is unsupported, the file cannot be read, or it holds no text. Aborting `signal` rejects with an AbortError.
 */
export async function parseFile(file: File, signal?: AbortSignal): Promise<string> {
  const kind = docKind(file.name);
  if (!kind) throw new Error(`"${file.name}" is not a supported type. Use .docx, .pdf, .txt or .md.`);
  throwIfAborted(signal);
  let text: string;
  try {
    if (kind === "docx") text = await readDocx(file, signal);
    else if (kind === "pdf") text = await readPdf(file, signal);
    else text = await readText(file);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    const reason = err instanceof Error ? err.message : String(err);
    throw new Error(`Could not read "${file.name}": ${reason}`);
  }
  throwIfAborted(signal);
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error(
      kind === "pdf"
        ? `"${file.name}" has no selectable text (scanned PDFs are not supported).`
        : `"${file.name}" has no text.`,
    );
  }
  return trimmed;
}
