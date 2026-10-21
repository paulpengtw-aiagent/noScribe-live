import { plural, type Locale } from "../core";

const en = {
  /** Connection overlay. */
  connLost: "Connection lost — reconnecting…",
  connAttempt: (attempt: number) => `Attempt ${attempt}`,
  connAttemptRetry: (attempt: number, seconds: number) => `Attempt ${attempt} · retrying in ${seconds} s`,
  connLastUpdate: (time: string) => `Last update ${time}`,
  /** Tab title: "<status> – <file>". The product name is the title when no run is shown. */
  titleIdle: "Live Speech-to-Text",
  titleReconnecting: (name: string) => `⚠ Reconnecting – ${name}`,
  titleLive: (name: string) => `● Live – ${name}`,
  titleStopped: (name: string) => `■ Stopped – ${name}`,
  titleFinished: (name: string) => `✓ Finished – ${name}`,
  titleFailed: (name: string) => `✕ Failed – ${name}`,
  titleCanceled: (name: string) => `○ Canceled – ${name}`,
  /** New-run toast. */
  newRunStarted: (name: string) => `New run started: ${name}`,
  newRunSwitch: "Switch",
  /** Page placeholder before the first hello. */
  loadingLabel: "Loading",
  /** Transcript column when the requested run is not on the server's list. */
  runMissingTitle: "This transcript was not found",
  runMissingBody: "The transcript this link points to is not in the current list.",
  runMissingFollow: "Follow the newest transcript",
  runMissingAria: "Transcript",
  /** Transcript column while a picked run's snapshot is awaited (loading, never "not found"). */
  runLoading: "Loading transcript…",
  /** Added to the run-loading placeholder after about 8 s without the snapshot. */
  runLoadingSlow: "This is taking longer than usual…",
  /** Toaster container label and the toast close button label. */
  toastsAria: "Notifications",
  toastClose: "Close notification",
  /** Persistent notice for a followed run that failed. */
  failedRunToast: (name: string) => `${name} failed`,
  failedRunView: "View",
  /** CLI log on phones (below 640 px): the toggle between six lines and the full bounded height. */
  cliLogExpand: "Expand",
  cliLogCollapse: "Collapse",
  /** Transcription-complete dialog, shown once when a run this page was watching live finishes. */
  runCompleteTitle: "Transcription complete",
  runCompleteLength: (time: string) => `Length ${time}`,
  runCompleteSegments: (n: number) => plural("en", n, { one: `${n} segment`, other: `${n} segments` }),
  runCompleteSpeakers: (n: number) => plural("en", n, { one: `${n} speaker`, other: `${n} speakers` }),
  runCompleteKeep: "Keep viewing",
};

export type AppMessages = typeof en;

const zhTW: AppMessages = {
  connLost: "連線中斷，正在重新連線…",
  connAttempt: (attempt) => `第 ${attempt} 次重新連線`,
  connAttemptRetry: (attempt, seconds) => `第 ${attempt} 次重新連線 · ${seconds} 秒後重試`,
  connLastUpdate: (time) => `最後更新 ${time}`,
  titleIdle: "即時語音轉文字",
  titleReconnecting: (name) => `⚠ 重新連線中 – ${name}`,
  titleLive: (name) => `● 即時 – ${name}`,
  titleStopped: (name) => `■ 意外停止 – ${name}`,
  titleFinished: (name) => `✓ 已完成 – ${name}`,
  titleFailed: (name) => `✕ 失敗 – ${name}`,
  titleCanceled: (name) => `○ 已取消 – ${name}`,
  newRunStarted: (name) => `新的轉錄已開始：${name}`,
  newRunSwitch: "切換",
  loadingLabel: "正在載入",
  runMissingTitle: "找不到這份逐字稿",
  runMissingBody: "這個連結指向的逐字稿不在目前的清單中。",
  runMissingFollow: "跟隨最新的逐字稿",
  runMissingAria: "逐字稿",
  runLoading: "正在載入逐字稿…",
  runLoadingSlow: "載入時間比平常久…",
  toastsAria: "通知",
  toastClose: "關閉通知",
  failedRunToast: (name) => `${name} 轉錄失敗`,
  failedRunView: "查看",
  cliLogExpand: "展開",
  cliLogCollapse: "收合",
  runCompleteTitle: "轉錄完成",
  runCompleteLength: (time) => `長度 ${time}`,
  runCompleteSegments: (n) => plural("zh-TW", n, { one: `${n} 段`, other: `${n} 段` }),
  runCompleteSpeakers: (n) => plural("zh-TW", n, { one: `${n} 位講者`, other: `${n} 位講者` }),
  runCompleteKeep: "繼續查看",
};

export const app = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
