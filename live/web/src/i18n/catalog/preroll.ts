const en = {
  terminalAria: "Live run log",
  status: {
    waiting: "Waiting for a transcription",
    converting: "Preparing audio",
    diarizing: "Identifying speakers",
    loading: "Loading model",
    listening: "Listening",
    transcribing: "Transcribing",
    finished: "Finished",
    error: "Failed",
    canceled: "Canceled",
  },
  elapsed: (time: string) => `elapsed ${time}`,
  lines: {
    audio: (name: string) => `audio  ${name}`,
    convert: "converting audio…",
    segmentation: "speaker detection  segmentation",
    embeddings: "embeddings",
    speakers: (count: number) => `speakers found  ${count}`,
    model: (model: string) => `loading model  ${model}…`,
    device: "device",
    language: (code: string) => `language  ${code}`,
    firstSegment: "first segment",
  },
  loadedIn: (seconds: string) => `loaded in ${seconds} s`,
  done: "✓",
};

const zhTW: typeof en = {
  terminalAria: "即時執行記錄",
  status: {
    waiting: "等待轉錄開始",
    converting: "準備音訊",
    diarizing: "辨識講者",
    loading: "載入模型",
    listening: "聆聽中",
    transcribing: "轉錄中",
    finished: "已完成",
    error: "失敗",
    canceled: "已取消",
  },
  elapsed: (time: string) => `已花費 ${time}`,
  lines: {
    audio: (name: string) => `音訊  ${name}`,
    convert: "正在轉換音訊…",
    segmentation: "講者偵測  分段",
    embeddings: "聲音比對",
    speakers: (count: number) => `找到講者  ${count}`,
    model: (model: string) => `載入模型  ${model}…`,
    device: "裝置",
    language: (code: string) => `語言  ${code}`,
    firstSegment: "第一段",
  },
  loadedIn: (seconds: string) => `載入耗時 ${seconds} 秒`,
  done: "✓",
};

export const preroll = { en, "zh-TW": zhTW };
export type PrerollMessages = typeof en;
