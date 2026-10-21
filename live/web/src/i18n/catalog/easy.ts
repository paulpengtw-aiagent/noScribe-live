import type { Locale } from "../core";

// Easy view (大字模式): the header toggle, the stage card's "More info" disclosure, and the status words
// that easy view shows with an icon (the icon glyph is drawn in components/live/easy-toggle.tsx).
const en = {
  /** Toggle label in the header and in the compact header menu. */
  toggle: "Easy view",
  /** Stage card disclosure that reveals the secondary stats: device, latency, real-time factor, language. */
  moreInfo: "More info",
  /** Status words shown while easy view is on. "Stopped" covers a canceled run and a run that stopped without a report. */
  status: {
    live: "Live",
    finished: "Finished",
    failed: "Failed",
    stopped: "Stopped",
    reconnecting: "Reconnecting",
  },
};

export type EasyMessages = typeof en;

const zhTW: EasyMessages = {
  toggle: "大字模式",
  moreInfo: "更多資訊",
  status: {
    live: "轉錄中",
    finished: "完成",
    failed: "失敗",
    stopped: "已停止",
    reconnecting: "重新連線中",
  },
};

export const easy = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
