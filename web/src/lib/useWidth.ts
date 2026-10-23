import { useLayoutEffect, useRef, useState } from "react";

/** Width of an element, kept current with a ResizeObserver; charts draw to it. */
export function useWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    setWidth(node.clientWidth || fallback);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width) || fallback));
    observer.observe(node);
    return () => observer.disconnect();
  }, [fallback]);
  return [ref, width] as const;
}
