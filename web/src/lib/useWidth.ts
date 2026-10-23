import { useCallback, useLayoutEffect, useState } from "react";

/**
 * Width of an element, kept current with a ResizeObserver; charts draw to it.
 * Returns a callback ref so elements that mount later (after data loads) are measured too.
 */
export function useWidth<T extends HTMLElement>(fallback = 640) {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);
  const ref = useCallback((element: T | null) => setNode(element), []);
  useLayoutEffect(() => {
    if (!node) return;
    setWidth(node.clientWidth || fallback);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width) || fallback));
    observer.observe(node);
    return () => observer.disconnect();
  }, [node, fallback]);
  return [ref, width] as const;
}
