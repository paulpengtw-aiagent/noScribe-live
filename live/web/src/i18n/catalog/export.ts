const en = {
  /** Run header: downloads the transcript as an OpenDocument text file. */
  label: "Download .odt",
  liveHint: "Available when the transcription finishes",
  done: "Downloaded",
  failed: "Download failed. Try again.",
};

export type ExportMessages = typeof en;

const zhTW: ExportMessages = {
  label: "下載 .odt",
  liveHint: "轉錄完成後即可下載",
  done: "已下載",
  failed: "下載失敗，請再試一次",
};

export const exportArea = { en, "zh-TW": zhTW };
