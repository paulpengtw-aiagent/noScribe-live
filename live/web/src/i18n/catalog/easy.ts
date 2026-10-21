import type { Locale } from "../core";

// Easy view (大字模式): the header toggle, the stage card's "Show details" disclosure, and the status words
// that easy view shows with an icon (the icon glyph is drawn in components/live/easy-toggle.tsx).
const en = {
  /** Toggle label in the header (desktop: full label; phone header: the short one). */
  toggle: "Easy view",
  toggleShort: "Easy",
  /** Stage card disclosure that reveals the secondary stats: device, latency, real-time factor, language. */
  moreInfo: "Show details",
  /** Status words shown while easy view is on. "Stopped" covers a run that stopped without a report. */
  status: {
    live: "Live",
    loading: "Loading",
    finished: "Finished",
    failed: "Failed",
    stopped: "Stopped",
    canceled: "Canceled",
    reconnecting: "Reconnecting",
  },
};

export type EasyMessages = typeof en;

const zhTW: EasyMessages = {
  toggle: "大字模式",
  toggleShort: "大字",
  moreInfo: "顯示詳細資訊",
  status: {
    live: "轉錄中",
    loading: "載入中",
    finished: "完成",
    failed: "失敗",
    stopped: "意外停止",
    canceled: "已取消",
    reconnecting: "重新連線中",
  },
};

export const easy = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
