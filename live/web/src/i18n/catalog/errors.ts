import type { Locale } from "../index";

const en = {
  genericError: "Something went wrong",
  details: "Error details",
  endStopped: "Transcription stopped unexpectedly",
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
  details: "詳細錯誤",
  endStopped: "轉錄意外中止",
  endStoppedDetail: "noScribe 在完成前停止了（行程已結束）。",
  endUnreadable: "無法讀取音訊檔（格式不支援或檔案損毀）",
  endFailed: "轉錄失敗",
  endCanceled: "已取消",
  endNoSpeech: "沒有偵測到語音",
  endFinished: "轉錄完成",
  causeGpuMemory: "GPU 記憶體不足",
  causeAudioNotFound: "找不到音訊檔",
};

export const errors = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
