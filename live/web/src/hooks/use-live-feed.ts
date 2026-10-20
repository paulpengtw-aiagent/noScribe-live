import { useEffect, useReducer, useState } from "react";
import { INITIAL_LIVE_STATE, liveReducer } from "@/lib/live-state";
import type { FeedPayload, HelloPayload, RunsPayload, SegmentEvent, SnapshotPayload } from "@/lib/live-types";

export type Connection = "connecting" | "live" | "reconnecting";

/** A stream that stays down this long without reopening is shown as reconnecting. */
const DOWN_AFTER_MS = 2000;
/** Retry delays for a stream the browser gave up on: 1 s, 2 s, 4 s, ... capped at 10 s. */
const RETRY_BASE_MS = 1000;
const RETRY_MAX_MS = 10000;

/** Debug surface for automated checks: one entry per live segment. */
export interface LiveArrival {
  run_id: string;
  index: number;
  t: number;
  server_t: number | null;
  recvAt: number;
  start: number;
  end: number;
}

declare global {
  interface Window {
    __noscribeLive?: { arrivals: LiveArrival[] };
  }
}

function recordArrival(runId: string, ev: SegmentEvent, recvAt: number) {
  const debug = (window.__noscribeLive ??= { arrivals: [] });
  debug.arrivals.push({
    run_id: runId,
    index: ev.index,
    t: ev.t,
    server_t: ev.server_t ?? null,
    recvAt,
    start: ev.start,
    end: ev.end,
  });
}

function parse<T>(ev: MessageEvent<string>): T | null {
  try {
    return JSON.parse(ev.data) as T;
  } catch {
    return null;
  }
}

/**
 * Follows the SSE stream for `runParam` ("latest" or a run id).
 * EventSource reconnects by itself while the server answers 200. When the browser
 * gives up (readyState CLOSED, e.g. after a non-200 response) we retry with backoff.
 * Each connect starts with hello and a snapshot, so every snapshot simply replaces
 * the run state and feed lines that were already applied are dropped by seq.
 */
export function useLiveFeed(runParam: string) {
  const [state, dispatch] = useReducer(liveReducer, INITIAL_LIVE_STATE);
  // The link state records which run id it belongs to, so a switch reads as "connecting" at once.
  const [link, setLink] = useState<{ runParam: string; state: Connection }>({ runParam, state: "connecting" });
  const connection: Connection = link.runParam === runParam ? link.state : "connecting";

  useEffect(() => {
    let closed = false;
    let source: EventSource | null = null;
    let downTimer: number | undefined;
    let retryTimer: number | undefined;
    let failures = 0;
    const setConnection = (next: Connection) => setLink({ runParam, state: next });

    const cancelDownTimer = () => {
      window.clearTimeout(downTimer);
      downTimer = undefined;
    };

    // Any error means the stream is down. It only shows as reconnecting if it
    // does not reopen within DOWN_AFTER_MS; only a new hello clears it.
    const markDown = () => {
      if (downTimer !== undefined) return;
      downTimer = window.setTimeout(() => {
        downTimer = undefined;
        setConnection("reconnecting");
      }, DOWN_AFTER_MS);
    };

    const connect = () => {
      if (closed) return;
      const es = new EventSource(`/api/stream?run=${encodeURIComponent(runParam)}`);
      source = es;
      es.onopen = () => cancelDownTimer();
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          // The browser gives up after a non-200 response, so retry by hand with backoff.
          es.close();
          if (source === es) source = null;
          const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** failures);
          failures += 1;
          retryTimer = window.setTimeout(connect, delay);
        }
        markDown();
      };
      es.addEventListener("hello", (ev) => {
        const d = parse<HelloPayload>(ev);
        if (!d) return;
        cancelDownTimer();
        failures = 0;
        setConnection("live");
        dispatch({ type: "hello", serverT: d.server_t, runs: d.runs });
      });
      es.addEventListener("snapshot", (ev) => {
        const d = parse<SnapshotPayload>(ev);
        if (d) dispatch({ type: "snapshot", runId: d.run_id, summary: d.summary, events: d.events, now: Date.now() });
      });
      es.addEventListener("feed", (ev) => {
        const d = parse<FeedPayload>(ev);
        if (!d) return;
        const now = Date.now();
        if (d.event.type === "segment") recordArrival(d.run_id, d.event, now);
        dispatch({ type: "feed", runId: d.run_id, event: d.event, now });
      });
      es.addEventListener("runs", (ev) => {
        const d = parse<RunsPayload>(ev);
        if (d) dispatch({ type: "runs", runs: d.runs });
      });
    };

    dispatch({ type: "reset" });
    connect();
    return () => {
      closed = true;
      window.clearTimeout(downTimer);
      window.clearTimeout(retryTimer);
      source?.close();
    };
  }, [runParam]);

  return { state, connection };
}
