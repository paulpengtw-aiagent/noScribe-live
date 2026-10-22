import type { Locale } from "../core";

// AI correction settings dialog strings (components/live/llm/settings-dialog.tsx).
const en = {
  title: "AI correction settings",
  intro: "Any OpenAI-compatible chat endpoint works, or Anthropic (Claude). This browser calls it directly; there is no server in between.",
  provider: "Provider",
  providerCustom: "Custom (OpenAI-compatible)",
  providerAnthropic: "Anthropic (Claude)",
  anthropicNote:
    "Calls go straight from this browser to api.anthropic.com, with the anthropic-dangerous-direct-browser-access header Anthropic requires for browser calls. Usage is billed to your key. The transcript and context documents are sent to Anthropic. The key stays in this tab (sessionStorage) unless you choose Remember on this browser.",
  baseUrl: "Base URL",
  baseUrlHint: "For example http://localhost:8799/v1. The app adds /chat/completions to it.",
  apiKey: "API key",
  apiKeyHint: "Sent as a Bearer token, and only to the endpoint above. Leave it empty if the endpoint needs no key.",
  showKey: "Show key",
  hideKey: "Hide key",
  model: "Model",
  modelHint: "Any model name the endpoint accepts.",
  temperature: "Temperature",
  temperatureHint: "Optional, from 0 to 2. Leave it empty for the server default.",
  temperatureAnthropic: "Not sent for Anthropic, so this field is off.",
  temperatureInvalid: "Enter a number from 0 to 2, or leave it empty.",
  remember: "Remember on this browser",
  rememberHint:
    "Stores the API key in this browser's localStorage, so it survives closing the tab. Leave this off on a shared computer.",
  privacyLocal: "This endpoint is on this machine or your local network. Transcript text and context documents are sent only there.",
  privacyRemote:
    "This endpoint is not local. Transcript text and context documents will be sent to it and leave this machine.",
  privacyKey: "The API key is sent only to the endpoint configured here.",
  test: "Test connection",
  testing: "Testing...",
  testOk: (ms: number, model: string) => `Connected in ${ms} ms. Model: ${model}.`,
  testOkListed: (ms: number, model: string) => `Key works; ${model} is available (${ms} ms).`,
  testOkNotListed: (model: string) => `Key works, but ${model} is not in the model list. Check the model name.`,
  save: "Save",
  cancel: "Cancel",
  errors: {
    cors: "The browser blocked the request. The endpoint must allow requests from this page's origin (CORS). Check its CORS settings.",
    corsAnthropic:
      "The browser blocked the request (CORS). Browser calls to Anthropic need the anthropic-dangerous-direct-browser-access header; check whether an extension or proxy strips it.",
    network: "Could not reach the endpoint. Check the base URL and that the server is running.",
    auth: (status: number) => `The endpoint rejected the API key (HTTP ${status}).`,
    authAnthropic: "Invalid or revoked key (401).",
    forbidden:
      "This key has no permission (403). Personal or service-account keys that are not scoped to a workspace also need anthropic-workspace-id; use a workspace-scoped key instead.",
    rateLimit: "Too many requests (429). Try again later.",
    overloaded: "The service is temporarily overloaded (529). Try again later.",
    http: (status: number) => `The endpoint returned an error (HTTP ${status}).`,
    json: "The endpoint's reply was not in the expected format.",
    aborted: "The test was canceled.",
  },
};

export type LlmSettingsMessages = typeof en;

const zhTW: LlmSettingsMessages = {
  title: "AI 校正設定",
  intro: "可連接任何相容 OpenAI 的聊天端點，或 Anthropic（Claude）。此瀏覽器會直接呼叫該端點，中間沒有伺服器。",
  provider: "服務來源",
  providerCustom: "自訂（OpenAI 相容）",
  providerAnthropic: "Anthropic (Claude)",
  anthropicNote:
    "呼叫會從此瀏覽器直接送到 api.anthropic.com，並附上 Anthropic 瀏覽器呼叫必須的 anthropic-dangerous-direct-browser-access 標頭。用量計入你的金鑰。逐字稿與參考文件會送到 Anthropic。金鑰只留在此分頁（sessionStorage），除非勾選「記住此瀏覽器」。",
  baseUrl: "基礎網址（Base URL）",
  baseUrlHint: "例如 http://localhost:8799/v1。程式會自動加上 /chat/completions。",
  apiKey: "API 金鑰",
  apiKeyHint: "以 Bearer 權杖傳送，且只傳給上述端點。若端點不需要金鑰，請留空。",
  showKey: "顯示金鑰",
  hideKey: "隱藏金鑰",
  model: "模型",
  modelHint: "端點接受的任何模型名稱。",
  temperature: "溫度（Temperature）",
  temperatureHint: "選填，範圍 0 到 2。留空則使用伺服器預設值。",
  temperatureAnthropic: "Anthropic 不會接收溫度設定，此欄已停用。",
  temperatureInvalid: "請輸入 0 到 2 之間的數字，或留空。",
  remember: "記住此瀏覽器",
  rememberHint: "會把 API 金鑰存在此瀏覽器的 localStorage，關閉分頁後仍會保留。在共用電腦上請保持關閉。",
  privacyLocal: "此端點位於本機或你的區域網路。逐字稿文字與參考文件只會送到這裡。",
  privacyRemote: "此端點不在本機。逐字稿文字與參考文件會送到該端點，並離開這台電腦。",
  privacyKey: "API 金鑰只會送到此處設定的端點。",
  test: "測試連線",
  testing: "測試中...",
  testOk: (ms: number, model: string) => `連線成功，耗時 ${ms} 毫秒。模型：${model}。`,
  testOkListed: (ms: number, model: string) => `金鑰有效；${model} 在可用模型清單中（${ms} 毫秒）。`,
  testOkNotListed: (model: string) => `金鑰有效，但模型清單中沒有 ${model}。請檢查模型名稱。`,
  save: "儲存",
  cancel: "取消",
  errors: {
    cors: "瀏覽器封鎖了這個請求。端點必須允許來自此頁面來源的請求（CORS）。請檢查它的 CORS 設定。",
    corsAnthropic:
      "瀏覽器封鎖了這個請求（CORS）。從瀏覽器呼叫 Anthropic 需要 anthropic-dangerous-direct-browser-access 標頭，請檢查瀏覽器擴充功能或代理是否移除了它。",
    network: "無法連到端點。請檢查基礎網址，並確認伺服器已啟動。",
    auth: (status: number) => `端點拒絕了 API 金鑰（HTTP ${status}）。`,
    authAnthropic: "金鑰無效或已撤銷（401）。",
    forbidden:
      "此金鑰沒有權限（403）。不限工作區的個人或服務帳號金鑰還需要 anthropic-workspace-id，請改用限定工作區的金鑰。",
    rateLimit: "請求過多（429），請稍後再試。",
    overloaded: "服務暫時過載（529），請稍後再試。",
    http: (status: number) => `端點回傳錯誤（HTTP ${status}）。`,
    json: "端點的回覆格式不符合預期。",
    aborted: "測試已取消。",
  },
};

export const llmSettings = { en, "zh-TW": zhTW } satisfies Record<Locale, unknown>;
