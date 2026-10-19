import { useEffect, useReducer, useState } from "react";
import { INITIAL_LIVE_STATE, liveReducer } from "@/lib/live-state";
import type { FeedPayload, HelloPayload, RunsPayload, SegmentEvent, SnapshotPayload } from "@/lib/live-types";

export type Connection = "connecting" | "live" | "reconnecting";

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
 * EventSource reconnects by itself; the server then re-sends hello and a
 * snapshot, so every snapshot simply replaces the run state.
 */
export function useLiveFeed(runParam: string) {
  const [state, dispatch] = useReducer(liveReducer, INITIAL_LIVE_STATE);
  const [connection, setConnection] = useState<Connection>("connecting");

  useEffect(() => {
    let closed = false;
    let source: EventSource | null = null;
    let retryTimer: number | undefined;

    const connect = () => {
      if (closed) return;
      setConnection("connecting");
      const es = new EventSource(`/api/stream?run=${encodeURIComponent(runParam)}`);
      source = es;
      es.onopen = () => setConnection("live");
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          // The browser gives up on a non-200 response; retry by hand.
          es.close();
          source = null;
          setConnection("reconnecting");
          retryTimer = window.setTimeout(connect, 2000);
        } else {
          setConnection("reconnecting");
        }
      };
      es.addEventListener("hello", (ev) => {
        const d = parse<HelloPayload>(ev);
        if (d) dispatch({ type: "hello", serverT: d.server_t, runs: d.runs });
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
      window.clearTimeout(retryTimer);
      source?.close();
    };
  }, [runParam]);

  return { state, connection };
}
