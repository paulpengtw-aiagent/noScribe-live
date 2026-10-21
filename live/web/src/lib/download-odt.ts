/** Language of the exported text: the app's locale, zh-TW or en. */
export type ExportLang = "zh-TW" | "en";

/** The file name from Content-Disposition: RFC 5987 filename* when present, else the plain filename. */
function fileNameFrom(disposition: string | null, fallback: string): string {
  if (disposition) {
    const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    if (star) {
      try {
        return decodeURIComponent(star[1].trim());
      } catch {
        // A malformed escape falls through to the plain name.
      }
    }
    const plain = /filename="([^"]+)"/i.exec(disposition);
    if (plain) return plain[1];
  }
  return fallback;
}

/**
 * Downloads a run as an .odt file (GET /api/runs/{id}/export.odt), the same request the run header's export button
 * makes. Rejects when the server answers with an error, for example 409 while the run is still live.
 */
export async function downloadOdt(runId: string, lang: ExportLang): Promise<void> {
  const url = `/api/runs/${encodeURIComponent(runId)}/export.odt?lang=${lang}`;
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`export failed: HTTP ${res.status}`);
  const blob = await res.blob();
  const name = fileNameFrom(res.headers.get("Content-Disposition"), `${runId}.odt`);
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 1000);
}
