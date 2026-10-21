# zh-TW review (branch nordic-wip)

Scope: zh-TW halves only, in `live/web/src/i18n/catalog/{app,stage,timeline,transcript,topbar,picker,errors}.ts`.
No keys added or removed. en halves, `easy.ts` and `index.ts` untouched. `timeline.ts` reviewed, no change needed.

## Changes (25 strings, 6 files)

app.ts
- `app.ts:newRunStarted`: 有新的轉錄開始：${name} → 新的轉錄已開始：${name}
- `app.ts:runMissingTitle`: 找不到這場轉錄 → 找不到這份逐字稿
- `app.ts:runMissingBody`: 這個連結指向的轉錄不在目前的清單中。 → 這個連結指向的逐字稿不在目前的清單中。
- `app.ts:runMissingFollow`: 跟隨最新的轉錄 → 跟隨最新的逐字稿
- `app.ts:runMissingAria`: 轉錄 → 逐字稿

stage.ts
- `stage.ts:runStatusLabel`: 執行狀態 → 轉錄狀態
- `stage.ts:listeningForRun`: 等待轉錄中… → 等待轉錄開始…
- `stage.ts:hints.elapsed`: 自執行開始經過的時間。 → 從開始轉錄起經過的時間。
- `stage.ts:hints.language`: 模型在開頭語音中判定的語言 → 模型在開頭的語音中判定的語言
- `stage.ts:hints.latencyUnmeasured`: 抵達的段落測得。 → 抵達的各段測得。
- `stage.ts:hints.latencySplit`: 推送 → 推播

transcript.ts
- `transcript.ts:waiting`: 正在等待語音轉錄 → 正在等待轉錄
- `transcript.ts:jumpToLive`: 跳至即時 → 回到即時

topbar.ts
- `topbar.ts:runStatus.running`: 進行中 → 即時 (en "Live"; matches 即時 in titleLive)
- `topbar.ts:latency.noSamples`: 收到的段落測量。 → 收到的各段測量。
- `topbar.ts:latency.split`: 推送 → 推播

picker.ts
- `picker.ts:followNewest`: 跟隨最新執行 → 跟隨最新的轉錄
- `picker.ts:filterRuns`: 篩選執行 → 篩選轉錄紀錄
- `picker.ts:filterPlaceholder`: 依檔案、執行 ID 或狀態篩選 → 依檔案、轉錄 ID 或狀態篩選
- `picker.ts:noRuns`: 尚無執行紀錄。 → 尚無轉錄紀錄。
- `picker.ts:noMatch`: 「${query}」的執行。 → 「${query}」的轉錄。
- `picker.ts:status.live`: 進行中 → 即時 (en "Live")

errors.ts
- `errors.ts:details`: 詳細錯誤 → 錯誤詳情
- `errors.ts:endStopped`: 意外中止 → 意外停止
- `errors.ts:endStoppedDetail`: （行程已結束） → （程式已結束）

## Glossary enforced

講者, 轉錄 (transcription, and "run" in UI text), 逐字稿 (transcript), 即時 (live), 重新連線, 連線中斷, 音訊檔, 模型, 裝置, 延遲, 語言, 已完成 / 完成, 失敗, 已停止, 已取消, 正在載入… / 載入中…, 跟隨最新, 篩選, 紀錄. Full-width （）、，。：「」 in Chinese text. Mainland-term scan of the zh-TW halves found none (文件, 视频, 信息, 默認, 鏈接, 加載, 屏幕, 用戶, 設置, 運行, 搜索, 菜單, 實時 and similar).

Kept on purpose: 執行 where it means a program or model running (`stage.ts:hints.device`, `stage.ts:hints.speakersNone`). Latin tokens (noScribe, CLI, CUDA, RTF, --live-feed) kept as-is.

## Validation

- `cd live/web && pnpm exec tsc -p tsconfig.app.json --noEmit`: exit 2, 3 errors, all in `live/web/src/components/live/easy-toggle.tsx` (`Property 'easy' does not exist on type 'Messages'`). That file belongs to another agent's untracked easy-catalog work; `easy.ts` and `index.ts` are not wired yet. No errors in the catalog files.
- Catalog diff: every hunk is on the zh-TW side. Line counts match HEAD for all seven files.
