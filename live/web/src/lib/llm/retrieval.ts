import { estimateTokens, type ContextDoc } from "./types";

/** Result of selecting context for one correction batch. */
export interface BuiltContext {
  /** Free text first, then the selected passages in document order, separated by blank lines. */
  text: string;
  /** True when at least one passage did not fit in the budget. */
  truncated: boolean;
  /** Number of document passages included in `text`. */
  passages: number;
  /** Estimated tokens of the whole context (free text plus every passage), before any selection. */
  totalTokens: number;
}

/** Target size of one passage, in characters. */
const PASSAGE_CHARS = 600;

const CJK_CHAR = "\\p{Script=Han}\\p{Script=Hiragana}\\p{Script=Katakana}\\p{Script=Hangul}\\p{Script=Bopomofo}";

/** One CJK character, a run of other letters or digits, a run of whitespace, or a run of other symbols. */
const TOKEN = new RegExp(
  `([${CJK_CHAR}])|((?:(?![${CJK_CHAR}])[\\p{L}\\p{N}])+)|(\\s+)|([^\\p{L}\\p{N}\\s]+)`,
  "gu",
);

/**
 * Character n-grams for matching. CJK text yields bigrams of adjacent characters; Latin text yields
 * words and adjacent word pairs. Text is NFKC-normalised and lowercased. A symbol run breaks adjacency.
 */
function ngrams(text: string): Set<string> {
  const out = new Set<string>();
  let prevKind: "cjk" | "word" | null = null;
  let prev = "";
  for (const m of text.normalize("NFKC").toLowerCase().matchAll(TOKEN)) {
    if (m[1] !== undefined) {
      if (prevKind === "cjk") out.add(prev + m[1]);
      prevKind = "cjk";
      prev = m[1];
    } else if (m[2] !== undefined) {
      out.add(m[2]);
      if (prevKind === "word") out.add(`${prev} ${m[2]}`);
      prevKind = "word";
      prev = m[2];
    } else if (m[4] !== undefined) {
      prevKind = null;
    }
  }
  return out;
}

/** Splits a paragraph longer than `target` at sentence ends, hard-cutting any sentence still too long. */
function splitLong(paragraph: string, target: number): string[] {
  const units: string[] = [];
  for (const sentence of paragraph.split(/(?<=[。！？；!?;])/u)) {
    for (let i = 0; i < sentence.length; i += target) units.push(sentence.slice(i, i + target));
  }
  const pieces: string[] = [];
  let current = "";
  for (const unit of units) {
    if (current && current.length + unit.length > target) {
      pieces.push(current);
      current = unit;
    } else {
      current += unit;
    }
  }
  if (current) pieces.push(current);
  return pieces.map((p) => p.trim()).filter((p) => p.length > 0);
}

/**
 * Splits document text into passages of about `target` characters. Paragraphs (blank-line separated)
 * are kept whole when they fit, and short ones are packed together. Longer paragraphs are cut at sentence ends.
 */
export function splitPassages(text: string, target: number = PASSAGE_CHARS): string[] {
  const paragraphs = text
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n+/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  const passages: string[] = [];
  let current = "";
  for (const paragraph of paragraphs) {
    const pieces = paragraph.length > target ? splitLong(paragraph, target) : [paragraph];
    for (const piece of pieces) {
      if (current && current.length + 1 + piece.length > target) {
        passages.push(current);
        current = piece;
      } else {
        current = current ? `${current}\n${piece}` : piece;
      }
    }
  }
  if (current) passages.push(current);
  return passages;
}

interface Passage {
  /** Position in document order across all sources. */
  order: number;
  /** Text as it is placed in the context, with the source name as a header. */
  block: string;
  /** The passage body, used for matching. */
  body: string;
  tokens: number;
  score: number;
}

/**
 * Selects the context to send with one correction batch. The free text always comes first. Then the
 * passages are chosen by n-gram overlap with `query` (the batch's segment texts), highest score first,
 * until `budgetTokens` (by estimateTokens) is used. If everything fits, every passage is included in
 * document order. Pure function: the same inputs always give the same output.
 */
export function buildContext(
  docs: ContextDoc[],
  freeText: string,
  query: string,
  budgetTokens: number,
): BuiltContext {
  const free = freeText.trim();
  const freeTokens = free.length > 0 ? estimateTokens(free) : 0;
  const budget = Number.isNaN(budgetTokens) ? 0 : budgetTokens;

  const passages: Passage[] = [];
  for (const doc of docs) {
    if (doc.status !== "ok" || !doc.text || doc.text.trim().length === 0) continue;
    for (const body of splitPassages(doc.text)) {
      const block = `[${doc.name}]\n${body}`;
      passages.push({ order: passages.length, block, body, tokens: estimateTokens(block), score: 0 });
    }
  }

  const totalTokens = passages.reduce((sum, p) => sum + p.tokens, freeTokens);
  let chosen: Passage[] = passages;

  if (totalTokens > budget) {
    const queryGrams = ngrams(query);
    const bodyGrams = passages.map((p) => ngrams(p.body));
    // Document frequency of each query n-gram across passages, for inverse weighting.
    const df = new Map<string, number>();
    for (const grams of bodyGrams) {
      for (const g of grams) if (queryGrams.has(g)) df.set(g, (df.get(g) ?? 0) + 1);
    }
    const n = passages.length;
    passages.forEach((p, i) => {
      let sum = 0;
      for (const g of bodyGrams[i]) {
        if (queryGrams.has(g)) sum += Math.log(1 + n / (1 + (df.get(g) ?? 0)));
      }
      // Dividing by the square root of the passage size keeps long passages from winning by length alone.
      p.score = sum / Math.sqrt(bodyGrams[i].size + 1);
    });

    const ranked = [...passages].sort((a, b) => b.score - a.score || a.order - b.order);
    let used = freeTokens;
    chosen = [];
    for (const p of ranked) {
      if (used + p.tokens > budget) break;
      used += p.tokens;
      chosen.push(p);
    }
    chosen.sort((a, b) => a.order - b.order);
  }

  const text = [free, ...chosen.map((p) => p.block)].filter((s) => s.length > 0).join("\n\n");
  return {
    text,
    truncated: chosen.length < passages.length,
    passages: chosen.length,
    totalTokens,
  };
}
