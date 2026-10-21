import type { Locale } from "../core";

// LLM settings panel strings. Only the title exists so far; feature work adds keys to `en` and the typed zh-TW object follows.
const en = {
  title: "LLM settings",
};

export type LlmSettingsMessages = typeof en;

const zhTW: LlmSettingsMessages = {
  title: "LLM 設定",
};

export const llmSettings = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
