import type { Locale } from "../core";

// LLM context-document panel strings. Only the title exists so far; feature work adds keys to `en` and the typed zh-TW object follows.
const en = {
  title: "Context documents",
};

export type LlmContextMessages = typeof en;

const zhTW: LlmContextMessages = {
  title: "參考文件",
};

export const llmContext = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
