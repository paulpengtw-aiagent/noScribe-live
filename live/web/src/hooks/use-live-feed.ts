import { useEffect, useReducer, useState } from "react";
import { INITIAL_LIVE_STATE, liveReducer } from "@/lib/live-state";
import type { FeedPayload, HelloPayload, RunsPayload, SegmentEvent, SnapshotPayload } from "@/lib/live-types";

/**
 * One connection state for the page.
 * connecting: until the first hello ever. live: a hello has arrived and the stream is up.
 * reconnecting: any loss after that (stream error, browser gave up, heartbeat timeout),
 * until the next hello, which makes it live again. It never goes back to connecting.
 */
export type Connection = "connecting" | "live" | "reconnecting";

/** Reconnect progress: reconnect attempts since the last hello, and the unix ms of the next one (null if unknown). */
export interface RetryInfo {
  attempt: number;
  nextAt: number | null;
}

const NO_RETRY: RetryInfo = { attempt: 0, nextAt: null };
/** An error the browser retries by itself only counts as a loss if the stream stays down this long. */
const DOWN_AFTER_MS = 2000;
/** Retry delays for a stream the browser gave up on: 1 s, 2 s, 4 s, ... capped at 10 s. */
const RETRY_BASE_MS = 1000;
const RETRY_MAX_MS = 10000;
/** The server pings every 15 s on an open stream, so 35 s with no message of any type means it is dead. */
const STALE_AFTER_MS = 35000;

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
    /** Test override for STALE_AFTER_MS. */
    __NSLIVE_HEARTBEAT_TIMEOUT_MS?: number;
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
 * A stream that goes silent (no message of any type for STALE_AFTER_MS) is closed and reopened.
 * Each connect starts with hello and a snapshot, so every snapshot simply replaces
 * the run state and feed lines that were already applied are dropped by seq.
 * The run state is kept across connection loss; it is reset only when the run changes.
 * `lastUpdateT` is the epoch seconds of the last message of any type (null before the first).
 */
export function useLiveFeed(runParam: string) {
  const [state, dispatch] = useReducer(liveReducer, INITIAL_LIVE_STATE);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [retry, setRetry] = useState<RetryInfo>(NO_RETRY);
  const [lastUpdateT, setLastUpdateT] = useState<number | null>(null);

  useEffect(() => {
    let closed = false;
    let source: EventSource | null = null;
    let downTimer: number | undefined;
    let retryTimer: number | undefined;
    let staleTimer: number | undefined;
    let failures = 0;
    let attempts = 0;

    const showReconnecting = (nextAt: number | null) => {
      setConnection("reconnecting");
      setRetry({ attempt: attempts, nextAt });
    };

    const cancelDownTimer = () => {
      window.clearTimeout(downTimer);
      downTimer = undefined;
    };

    // An error the browser retries by itself. It becomes a loss only if it does not reopen within DOWN_AFTER_MS.
    const markDown = () => {
      if (downTimer !== undefined) return;
      downTimer = window.setTimeout(() => {
        downTimer = undefined;
        attempts += 1;
        showReconnecting(null);
      }, DOWN_AFTER_MS);
    };

    // Ends the current stream and reconnects after the backoff delay. One reconnect is pending at a time.
    function reconnectLater() {
      window.clearTimeout(retryTimer);
      window.clearTimeout(staleTimer);
      cancelDownTimer();
      source?.close();
      source = null;
      const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** failures);
      failures += 1;
      attempts += 1;
      showReconnecting(Date.now() + delay);
      retryTimer = window.setTimeout(connect, delay);
    }

    function onStale() {
      if (!closed) reconnectLater();
    }

    // Every message of any type (ping included) re-arms the staleness timer. Opening a stream is not a message.
    function armStale() {
      window.clearTimeout(staleTimer);
      staleTimer = window.setTimeout(onStale, window.__NSLIVE_HEARTBEAT_TIMEOUT_MS ?? STALE_AFTER_MS);
    }

    function connect() {
      if (closed) return;
      retryTimer = undefined;
      const es = new EventSource(`/api/stream?run=${encodeURIComponent(runParam)}`);
      source = es;
      armStale();
      const on = (type: string, handle: (ev: MessageEvent<string>) => void) =>
        es.addEventListener(type, (ev) => {
          armStale();
          setLastUpdateT(Date.now() / 1000);
          handle(ev as MessageEvent<string>);
        });
      es.onopen = () => cancelDownTimer();
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          // The browser gives up after a non-200 response, so retry by hand with backoff.
          reconnectLater();
          return;
        }
        markDown();
      };
      on("ping", () => {});
      on("hello", (ev) => {
        const d = parse<HelloPayload>(ev);
        if (!d) return;
        cancelDownTimer();
        failures = 0;
        attempts = 0;
        setConnection("live");
        setRetry(NO_RETRY);
        dispatch({ type: "hello", serverT: d.server_t, runs: d.runs });
      });
      on("snapshot", (ev) => {
        const d = parse<SnapshotPayload>(ev);
        if (d) dispatch({ type: "snapshot", runId: d.run_id, summary: d.summary, events: d.events, now: Date.now() });
      });
      on("feed", (ev) => {
        const d = parse<FeedPayload>(ev);
        if (!d) return;
        const now = Date.now();
        if (d.event.type === "segment") recordArrival(d.run_id, d.event, now);
        dispatch({ type: "feed", runId: d.run_id, event: d.event, now });
      });
      on("runs", (ev) => {
        const d = parse<RunsPayload>(ev);
        if (d) dispatch({ type: "runs", runs: d.runs });
      });
    }

    dispatch({ type: "reset" });
    connect();
    return () => {
      closed = true;
      window.clearTimeout(downTimer);
      window.clearTimeout(retryTimer);
      window.clearTimeout(staleTimer);
      source?.close();
    };
  }, [runParam]);

  return { state, connection, retry, lastUpdateT };
}
