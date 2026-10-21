import type { Locale } from "../index";

const en = {
  title: "Timeline",
  speakers: "Speakers",
  transcribed: (clock: string) => `Transcribed ${clock}`,
  segment: (n: number, name: string) => `Segment ${n}, ${name}`,
  segmentPlain: (n: number) => `Segment ${n}`,
  peaks: {
    undecodable: "Waveform unavailable: the audio file cannot be read",
    missing: "Waveform unavailable: audio file not found",
    failed: "Waveform temporarily unavailable",
  },
};

export type TimelineMessages = typeof en;

const zhTW: TimelineMessages = {
  title: "時間軸",
  speakers: "講者",
  transcribed: (clock: string) => `已轉錄 ${clock}`,
  segment: (n: number, name: string) => `第 ${n} 段，${name}`,
  segmentPlain: (n: number) => `第 ${n} 段`,
  peaks: {
    undecodable: "無法顯示波形：音訊檔無法讀取",
    missing: "無法顯示波形：找不到音訊檔",
    failed: "波形暫時無法載入",
  },
};

export const timeline = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
