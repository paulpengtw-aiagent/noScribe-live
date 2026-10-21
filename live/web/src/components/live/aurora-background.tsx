import { useEffect, useRef } from "react";

export interface AuroraBackgroundProps {
  /** A run is live: the aurora shimmers. Optional; without it the layer is calmer. */
  live?: boolean;
}

/**
 * A fixed, decorative layer behind the header and the glass cards, full width and fading out toward the
 * bottom (index.css masks it). Four soft radial blobs in Aurora green, teal and purple with a touch of
 * Frost drift on transform only, and a soft band just under the header (.aurora-band). The CSS makes it static under prefers-reduced-motion and
 * html[data-easy="true"]. Pointer events pass through it.
 */
export function AuroraBackground({ live = false }: AuroraBackgroundProps) {
  const ref = useRef<HTMLDivElement>(null);

  // Other styles can read the live state from the document root.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.liveRun = live ? "true" : "false";
    return () => {
      delete root.dataset.liveRun;
    };
  }, [live]);

  // Pause the drift while the tab is hidden; resume when it is shown again.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const sync = () => {
      el.dataset.paused = document.hidden ? "true" : "false";
    };
    sync();
    document.addEventListener("visibilitychange", sync);
    return () => document.removeEventListener("visibilitychange", sync);
  }, []);

  return (
    <div ref={ref} aria-hidden="true" data-live={live ? "true" : undefined} className="aurora">
      <span className="aurora-blob" data-n="1" />
      <span className="aurora-blob" data-n="2" />
      <span className="aurora-blob" data-n="3" />
      <span className="aurora-blob" data-n="4" />
      <span className="aurora-band" />
    </div>
  );
}
