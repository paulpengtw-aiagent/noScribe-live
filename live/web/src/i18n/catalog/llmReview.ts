import type { Locale } from "../core";

// LLM correction review strings. Only the title exists so far; feature work adds keys to `en` and the typed zh-TW object follows.
const en = {
  title: "Review corrections",
};

export type LlmReviewMessages = typeof en;

const zhTW: LlmReviewMessages = {
  title: "審閱修正",
};

export const llmReview = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
