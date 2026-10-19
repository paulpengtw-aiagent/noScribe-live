import { useLayoutEffect, useState, type RefObject } from "react";

export interface ElementSize {
  width: number;
  height: number;
}

/** Content-box size of an element, kept current with a ResizeObserver. Zero until measured. */
export function useElementSize<T extends HTMLElement>(ref: RefObject<T | null>): ElementSize {
  const [size, setSize] = useState<ElementSize>({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (!box) return;
      setSize((prev) =>
        prev.width === box.width && prev.height === box.height ? prev : { width: box.width, height: box.height },
      );
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
