import { useEffect, useState, type RefObject } from "react";

/** The drawn width of an element, kept as it changes. A chart drawn at its
 *  real size keeps its type at the page's sizes; one stretched from a fixed
 *  viewBox has its 11px labels grow to 15 on a wide window. */
export function useWidth(ref: RefObject<Element>, fallback = 1000): number {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => {
      const next = Math.round(el.getBoundingClientRect().width);
      if (next > 0) setWidth((had) => (Math.abs(had - next) > 1 ? next : had));
    };
    read();
    const watch = new ResizeObserver(read);
    watch.observe(el);
    return () => watch.disconnect();
  }, [ref]);
  return width;
}
