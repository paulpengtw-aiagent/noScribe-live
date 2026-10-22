import type { Locale } from "../core";

// LLM context-document panel strings. Counts and sizes are passed in already formatted for the locale.
const en = {
  title: "Context documents",
  /** One line under the title: what the documents are for. */
  hint: "Notes, a glossary, or source documents that help the model fix names and terms.",
  textLabel: "Notes",
  textPlaceholder: "Paste names, terms, or background notes here.",
  dropTitle: "Drop files here",
  dropActive: "Release to add the files",
  dropHint: "Word (.docx), PDF, text (.txt) or Markdown (.md). Up to 30 files and 50 MB in total.",
  chooseFiles: "Choose files",
  status: {
    queued: "Waiting",
    parsing: "Reading",
    ok: "Ready",
    error: "Could not read",
    /** A file refused when added (limits or type). */
    refused: "Not added",
  },
  /** Character count of one file. */
  chars: (n: string) => `${n} characters`,
  /** Accessible name of a row's remove button. */
  removeLabel: (name: string) => `Remove ${name}`,
  fileCount: (n: number) => (n === 1 ? "1 file" : `${n} files`),
  charCount: (n: string) => `${n} characters`,
  tokenCount: (n: string) => `about ${n} tokens`,
  limitFiles: "Too many files. The limit is 30.",
  limitSize: "The files are too large together. The limit is 50 MB.",
  unsupported: "This file type is not supported.",
  parseFailed: "This file could not be read.",
  /** Shown when the context is larger than the token budget. */
  retrievalNote: "The context is longer than the budget, so the most relevant passages are selected per batch.",
};

export type LlmContextMessages = typeof en;

const zhTW: LlmContextMessages = {
  title: "參考文件",
  hint: "筆記、詞彙表或原始文件，協助模型修正人名與專有名詞。",
  textLabel: "筆記",
  textPlaceholder: "在此貼上人名、專有名詞或背景說明。",
  dropTitle: "將檔案拖曳到這裡",
  dropActive: "放開即可加入檔案",
  dropHint: "支援 Word (.docx)、PDF、純文字 (.txt) 與 Markdown (.md)。最多 30 個檔案，合計 50 MB。",
  chooseFiles: "選擇檔案",
  status: {
    queued: "等待中",
    parsing: "讀取中",
    ok: "已就緒",
    error: "無法讀取",
    refused: "未加入",
  },
  chars: (n: string) => `${n} 字`,
  removeLabel: (name: string) => `移除 ${name}`,
  fileCount: (n: number) => `${n} 個檔案`,
  charCount: (n: string) => `${n} 字`,
  tokenCount: (n: string) => `約 ${n} tokens`,
  limitFiles: "檔案數量超過上限（30 個）。",
  limitSize: "檔案合計超過 50 MB 上限。",
  unsupported: "不支援此檔案類型。",
  parseFailed: "無法讀取此檔案。",
  retrievalNote: "參考資料超過預算，每一批次會挑選最相關的段落。",
};

export const llmContext = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
