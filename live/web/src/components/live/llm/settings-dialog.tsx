// AI correction settings: the endpoint, API key, model, temperature and the remember choice. "Test connection" uses the
// values in the form, so nothing is saved until Save. Easy view (html[data-easy="true"]) is handled by the global rules
// for buttons and text sizes; the inputs get their 48 px height from the variant class below.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { LlmSettingsMessages } from "@/i18n/catalog/llmSettings";
import { useI18n } from "@/i18n";
import { testConnection, type TestConnectionResult } from "@/lib/llm/client";
import { DEFAULT_LLM_MODEL, isLocalEndpoint, useLlmSettings } from "@/lib/llm/settings";
import type { LlmError, LlmSettings } from "@/lib/llm/types";
import { cn } from "@/lib/utils";

/** Easy view: 48 px inputs (the global rules already size buttons and text). */
const EASY_INPUT = "[html[data-easy=true]_&]:h-12";

export function LlmSettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange(open: boolean): void }) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="llm-settings-dialog"
        className="flex max-h-[min(44rem,calc(100dvh_-_6rem))] flex-col overflow-hidden sm:max-w-xl"
      >
        <DialogHeader className="shrink-0">
          <DialogTitle className="text-xl">{t.llmSettings.title}</DialogTitle>
          <DialogDescription>{t.llmSettings.intro}</DialogDescription>
        </DialogHeader>
        <SettingsForm onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

/** Blank means no temperature (server default). Otherwise the value must be a number from 0 to 2. */
function parseTemperature(text: string): { valid: boolean; value: number | undefined } {
  const trimmed = text.trim();
  if (trimmed === "") return { valid: true, value: undefined };
  const n = Number(trimmed);
  return Number.isFinite(n) && n >= 0 && n <= 2 ? { valid: true, value: n } : { valid: false, value: undefined };
}

function errorText(error: LlmError, m: LlmSettingsMessages): string {
  const status = error.status ?? 0;
  switch (error.kind) {
    case "cors":
      return m.errors.cors;
    case "network":
      return m.errors.network;
    case "auth":
      return m.errors.auth(status);
    case "http":
      return m.errors.http(status);
    case "json":
      return m.errors.json;
    case "aborted":
      return m.errors.aborted;
  }
}

// Mounted each time the dialog opens (Radix unmounts the content on close), so the fields start from the saved values.
function SettingsForm({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const { settings, apiKey, save } = useLlmSettings();
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl);
  const [key, setKey] = useState(apiKey);
  const [showKey, setShowKey] = useState(false);
  const [model, setModel] = useState(settings.model);
  const [temperature, setTemperature] = useState(settings.temperature === undefined ? "" : String(settings.temperature));
  const [remember, setRemember] = useState(settings.remember);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestConnectionResult | null>(null);
  const testRun = useRef<AbortController | null>(null);

  // Closing the dialog cancels a test that is still in flight.
  useEffect(() => () => testRun.current?.abort(), []);

  const temp = parseTemperature(temperature);
  const draft: LlmSettings = {
    baseUrl: baseUrl.trim(),
    model: model.trim() || DEFAULT_LLM_MODEL,
    temperature: temp.value,
    remember,
  };
  const hasUrl = draft.baseUrl !== "";
  const local = isLocalEndpoint(draft.baseUrl);

  const runTest = async () => {
    testRun.current?.abort();
    const run = new AbortController();
    testRun.current = run;
    setTesting(true);
    setResult(null);
    const outcome = await testConnection(draft, key, run.signal);
    if (run.signal.aborted) return; // the dialog closed or a newer test started
    testRun.current = null;
    setTesting(false);
    setResult(outcome);
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!temp.valid) return;
    save(draft, key);
    onDone();
  };

  return (
    <form className="flex min-h-0 flex-1 flex-col gap-4" onSubmit={onSubmit}>
      <div className="-mx-1 grid min-h-0 flex-1 content-start gap-5 overflow-y-auto px-1 py-1">
        <div className="grid gap-2">
          <label htmlFor="llm-base-url" className="text-sm font-medium">
            {t.llmSettings.baseUrl}
          </label>
          <Input
            id="llm-base-url"
            data-testid="llm-base-url"
            className={EASY_INPUT}
            type="text"
            inputMode="url"
            placeholder="http://localhost:8799/v1"
            autoComplete="off"
            spellCheck={false}
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t.llmSettings.baseUrlHint}</p>
        </div>

        <div className="grid gap-2">
          <label htmlFor="llm-api-key" className="text-sm font-medium">
            {t.llmSettings.apiKey}
          </label>
          <div className="flex gap-2">
            <Input
              id="llm-api-key"
              data-testid="llm-api-key"
              className={cn("flex-1", EASY_INPUT)}
              type={showKey ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
              value={key}
              onChange={(event) => setKey(event.target.value)}
            />
            <Button
              type="button"
              variant="outline"
              size="icon-lg"
              data-testid="llm-key-toggle"
              aria-label={showKey ? t.llmSettings.hideKey : t.llmSettings.showKey}
              title={showKey ? t.llmSettings.hideKey : t.llmSettings.showKey}
              onClick={() => setShowKey((shown) => !shown)}
            >
              {showKey ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">{t.llmSettings.apiKeyHint}</p>
        </div>

        <div className="grid gap-2">
          <label htmlFor="llm-model" className="text-sm font-medium">
            {t.llmSettings.model}
          </label>
          <Input
            id="llm-model"
            data-testid="llm-model"
            className={EASY_INPUT}
            type="text"
            autoComplete="off"
            spellCheck={false}
            placeholder={DEFAULT_LLM_MODEL}
            value={model}
            onChange={(event) => setModel(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t.llmSettings.modelHint}</p>
        </div>

        <div className="grid gap-2">
          <label htmlFor="llm-temperature" className="text-sm font-medium">
            {t.llmSettings.temperature}
          </label>
          <Input
            id="llm-temperature"
            data-testid="llm-temperature"
            className={EASY_INPUT}
            type="number"
            inputMode="decimal"
            min={0}
            max={2}
            step={0.1}
            aria-invalid={!temp.valid}
            value={temperature}
            onChange={(event) => setTemperature(event.target.value)}
          />
          {temp.valid ? (
            <p className="text-muted-foreground text-xs">{t.llmSettings.temperatureHint}</p>
          ) : (
            <p role="alert" className="text-status-failed-ink text-sm">
              {t.llmSettings.temperatureInvalid}
            </p>
          )}
        </div>

        <label
          htmlFor="llm-remember"
          className="flex min-h-12 cursor-pointer items-start gap-3 rounded-md border p-3"
        >
          <input
            id="llm-remember"
            data-testid="llm-remember"
            type="checkbox"
            className="mt-1 size-5 shrink-0 accent-primary"
            checked={remember}
            onChange={(event) => setRemember(event.target.checked)}
          />
          <span className="grid gap-1">
            <span className="text-sm font-medium">{t.llmSettings.remember}</span>
            <span className="text-muted-foreground text-xs">{t.llmSettings.rememberHint}</span>
          </span>
        </label>

        {hasUrl ? (
          <div
            data-testid="llm-privacy"
            role="note"
            className={cn(
              "grid gap-2 rounded-md border p-3 text-sm",
              local ? "border-border" : "border-status-stopped-ink",
            )}
          >
            <p className={local ? undefined : "text-status-stopped-ink"}>
              {local ? t.llmSettings.privacyLocal : t.llmSettings.privacyRemote}
            </p>
            <p>{t.llmSettings.privacyKey}</p>
          </div>
        ) : (
          <p data-testid="llm-privacy" className="text-muted-foreground text-sm">
            {t.llmSettings.privacyKey}
          </p>
        )}

      </div>

      <DialogFooter className="shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-wrap items-center gap-3 sm:grow">
          <Button
            type="button"
            variant="outline"
            data-testid="llm-test"
            disabled={!temp.valid || !hasUrl || testing}
            onClick={() => void runTest()}
          >
            {testing ? t.llmSettings.testing : t.llmSettings.test}
          </Button>
          {result ? (
            <p
              data-testid="llm-test-result"
              data-ok={result.ok ? "true" : "false"}
              data-kind={result.ok ? undefined : result.error.kind}
              role="status"
              className={cn(
                "min-w-0 grow basis-48 text-sm",
                result.ok ? "text-status-live-ink" : "text-status-failed-ink",
              )}
            >
              {result.ok ? t.llmSettings.testOk(result.ms, result.model) : errorText(result.error, t.llmSettings)}
              {!result.ok && (result.error.kind === "http" || result.error.kind === "auth") ? (
                <span className="text-muted-foreground block text-xs">{result.error.message}</span>
              ) : null}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 justify-end gap-2">
          <Button type="button" variant="outline" data-testid="llm-cancel" onClick={onDone}>
            {t.llmSettings.cancel}
          </Button>
          <Button type="submit" data-testid="llm-save" disabled={!temp.valid}>
            {t.llmSettings.save}
          </Button>
        </div>
      </DialogFooter>
    </form>
  );
}
