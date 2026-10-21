import type { Locale } from "../index";
import { app, type AppMessages } from "./app";
import { easy, type EasyMessages } from "./easy";
import { exportArea, type ExportMessages } from "./export";
import { errors, type ErrorsMessages } from "./errors";
import { picker, type PickerMessages } from "./picker";
import { preroll, type PrerollMessages } from "./preroll";
import { stage, type StageMessages } from "./stage";
import { timeline, type TimelineMessages } from "./timeline";
import { topbar, type TopbarMessages } from "./topbar";
import { transcript, type TranscriptMessages } from "./transcript";

/** Full message tree for one locale. Each area's zh-TW object is typed against its en shape. */
export type Messages = {
  app: AppMessages;
  stage: StageMessages;
  timeline: TimelineMessages;
  transcript: TranscriptMessages;
  topbar: TopbarMessages;
  picker: PickerMessages;
  errors: ErrorsMessages;
  easy: EasyMessages;
  export: ExportMessages;
  preroll: PrerollMessages;
};

export const catalog: Record<Locale, Messages> = {
  en: {
    app: app.en,
    stage: stage.en,
    timeline: timeline.en,
    transcript: transcript.en,
    topbar: topbar.en,
    picker: picker.en,
    errors: errors.en,
    easy: easy.en,
    export: exportArea.en,
    preroll: preroll.en,
  },
  "zh-TW": {
    app: app["zh-TW"],
    stage: stage["zh-TW"],
    timeline: timeline["zh-TW"],
    transcript: transcript["zh-TW"],
    topbar: topbar["zh-TW"],
    picker: picker["zh-TW"],
    errors: errors["zh-TW"],
    easy: easy["zh-TW"],
    export: exportArea["zh-TW"],
    preroll: preroll["zh-TW"],
  },
};
