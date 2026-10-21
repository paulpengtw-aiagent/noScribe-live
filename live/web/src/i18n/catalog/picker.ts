import { plural, type Locale } from "../core";

// Run picker strings: the trigger, the filter box, day headings, status words, counts and empty states.
const en = {
  followNewest: "Follow newest",
  followNewestShort: "Follow newest",
  filterRuns: "Filter runs",
  /** Accessible name of the run list (cmdk Command and CommandList). */
  listLabel: "Runs",
  filterPlaceholder: "Filter by file, run id or status",
  noRuns: "No runs yet.",
  noMatch: (query: string) => `No runs match "${query}".`,
  noStartTime: "No start time",
  status: { live: "Live", loading: "Loading", finished: "Finished", failed: "Failed", stopped: "Stopped", canceled: "Canceled" },
  segments: (n: number) => plural("en", n, { one: `${n} segment`, other: `${n} segments` }),
};

export type PickerMessages = typeof en;

const zhTW: PickerMessages = {
  followNewest: "跟隨最新",
  followNewestShort: "跟隨最新",
  filterRuns: "篩選轉錄紀錄",
  listLabel: "轉錄紀錄",
  filterPlaceholder: "依檔案、轉錄 ID 或狀態篩選",
  noRuns: "尚無轉錄紀錄。",
  noMatch: (query: string) => `沒有符合「${query}」的轉錄。`,
  noStartTime: "未記錄開始時間",
  status: { live: "即時", loading: "載入中", finished: "已完成", failed: "失敗", stopped: "意外停止", canceled: "已取消" },
  segments: (n: number) => `${n} 段`,
};

export const picker = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
