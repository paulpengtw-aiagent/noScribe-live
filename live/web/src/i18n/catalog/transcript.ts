import type { Locale } from "../index";

const en = {
  transcriptLabel: "Transcript",
  waiting: "Waiting for a transcription",
  waitingHint: "Start a noScribe run with --live-feed and it appears here as it is transcribed.",
  copy: "Copy",
  copied: "Copied",
  segmentsHint: "Segments appear here as soon as the model hears speech.",
  jumpToLive: "Jump to live",
  jumpToEnd: "Jump to end",
  model: (model: string) => `Model ${model}`,
  overlap: (speaker: string) => `overlap · ${speaker}`,
  speakerNumber: (n: number) => `Speaker ${n}`,
  srLine: (speaker: string, text: string) => `${speaker}: ${text}`,
};

export type TranscriptMessages = typeof en;

const zhTW: TranscriptMessages = {
  transcriptLabel: "逐字稿",
  waiting: "正在等待語音轉錄",
  waitingHint: "使用 --live-feed 啟動 noScribe 轉錄，轉錄時內容會即時顯示在這裡。",
  copy: "複製",
  copied: "已複製",
  segmentsHint: "模型一聽到語音，內容就會顯示在這裡。",
  jumpToLive: "跳至即時",
  jumpToEnd: "跳至結尾",
  model: (model: string) => `模型 ${model}`,
  overlap: (speaker: string) => `重疊 · ${speaker}`,
  speakerNumber: (n: number) => `講者 ${n}`,
  srLine: (speaker: string, text: string) => `${speaker}：${text}`,
};

export const transcript = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
