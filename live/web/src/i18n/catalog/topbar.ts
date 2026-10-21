import type { Locale } from "../core";

// Header strings: product name, run and connection state, the other-live switch, the theme and language
// toggles, and the latency and clock hints that live-view.ts builds.
const en = {
  appName: "noScribe Live",
  languageLabel: "Language",
  switchLanguage: "Switch language to Chinese (Traditional)",
  /** Button label on the English page; it names the language the button switches to. */
  languageShort: "中",
  /** Header menu's language row on the English page: the endonym of the language it switches to. */
  languageEndonym: "中文（繁體）",
  switchTheme: { light: "Switch to light theme", dark: "Switch to dark theme" },
  /** Screen-reader label of the logo's busy orb. */
  processing: "Processing…",
  /** Icon menu (compact header) that holds the theme and language switches. */
  menuLabel: "Theme and language",
  /** Run state words. "loading" is a running run with no segment yet. */
  runStatus: { running: "Live", loading: "Loading", finished: "Finished", error: "Failed", canceled: "Canceled", stale: "Stopped" },
  runDisconnected: "Disconnected",
  connConnected: "Connected",
  connConnecting: "Connecting…",
  connReconnecting: "Reconnecting…",
  otherLive: "Another transcription is running → Switch",
  /** The same switch on the Easy phone header, short enough to keep the header to one row. */
  otherLiveShort: "Live run → Switch",
  clockOf: (transcribed: string, duration: string) => `${transcribed} of ${duration}`,
  latency: {
    noSamples:
      "Time from the CLI finishing a segment to it appearing here. Measured on segments that arrive while this page is open.",
    stats: (last: string, median: string, split: string) =>
      `Time from the CLI finishing a segment to it appearing here. Last ${last} · median ${median}${split}.`,
    split: (tail: string, push: string) => ` (tail ${tail} + push ${push})`,
  },
};

export type TopbarMessages = typeof en;

const zhTW: TopbarMessages = {
  appName: "noScribe Live",
  languageLabel: "語言",
  switchLanguage: "切換語言為英文",
  languageShort: "EN",
  languageEndonym: "English",
  switchTheme: { light: "切換為淺色主題", dark: "切換為深色主題" },
  processing: "處理中…",
  menuLabel: "主題與語言",
  runStatus: { running: "即時", loading: "載入中", finished: "已完成", error: "失敗", canceled: "已取消", stale: "意外停止" },
  runDisconnected: "連線中斷",
  connConnected: "已連線",
  connConnecting: "連線中…",
  connReconnecting: "重新連線中…",
  otherLive: "另一個轉錄正在進行 → 切換",
  otherLiveShort: "有新轉錄 → 切換",
  clockOf: (transcribed: string, duration: string) => `${transcribed} / ${duration}`,
  latency: {
    noSamples: "從 CLI 完成一段到它出現在這裡的時間。以本頁開啟期間收到的各段測量。",
    stats: (last: string, median: string, split: string) =>
      `從 CLI 完成一段到它出現在這裡的時間。最近 ${last} · 中位數 ${median}${split}。`,
    split: (tail: string, push: string) => `（尾端 ${tail} + 推播 ${push}）`,
  },
};

export const topbar = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
