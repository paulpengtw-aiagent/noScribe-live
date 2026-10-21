import type { Locale } from "../index";

const en = {
  genericError: "Something went wrong",
  details: "Error details",
  endStopped: "Stopped unexpectedly",
  endStoppedLine: "■ Stopped unexpectedly",
  endMoreDetails: "Details",
  endStoppedDetail: "noScribe stopped before it finished (the process exited).",
  endUnreadable: "Can't read the audio file (unsupported format or damaged)",
  endFailed: "Transcription failed",
  endCanceled: "Canceled",
  endNoSpeech: "No speech detected",
  endFinished: "Transcription complete",
  causeGpuMemory: "Out of GPU memory",
  causeAudioNotFound: "Audio file not found",
};

export type ErrorsMessages = typeof en;

const zhTW: ErrorsMessages = {
  genericError: "發生錯誤",
  details: "錯誤詳情",
  endStopped: "意外停止",
  endStoppedLine: "■ 轉錄意外停止",
  endMoreDetails: "詳細說明",
  endStoppedDetail: "noScribe 在完成前停止了（程式已結束）。",
  endUnreadable: "無法讀取音訊檔（格式不支援或檔案損毀）",
  endFailed: "轉錄失敗",
  endCanceled: "已取消",
  endNoSpeech: "沒有偵測到語音",
  endFinished: "轉錄完成",
  causeGpuMemory: "GPU 記憶體不足",
  causeAudioNotFound: "找不到音訊檔",
};

export const errors = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
