/** One run of a text diff. Unchanged text has neither flag set. */
export interface DiffPart {
  value: string;
  added?: boolean;
  removed?: boolean;
}

// The same scripts as the transcript's CJK check. CJK characters carry more meaning each, so a character diff reads better.
const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\p{Script=Bopomofo}]/u;

function cjkHeavy(text: string): boolean {
  let cjk = 0;
  let total = 0;
  for (const ch of text) {
    if (/\s/.test(ch)) continue;
    total++;
    if (CJK.test(ch)) cjk++;
  }
  return total > 0 && cjk / total >= 0.5;
}

/** Diff of two texts: by character for CJK-heavy text, by word (keeping spaces) otherwise. The diff library loads on first use. */
export async function diffParts(a: string, b: string): Promise<DiffPart[]> {
  const { diffChars, diffWordsWithSpace } = await import("diff");
  const changes = cjkHeavy(a + b) ? diffChars(a, b) : diffWordsWithSpace(a, b);
  return changes.map((c) => ({
    value: c.value,
    ...(c.added ? { added: true } : {}),
    ...(c.removed ? { removed: true } : {}),
  }));
}
