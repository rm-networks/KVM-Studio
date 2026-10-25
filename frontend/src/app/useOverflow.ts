import { type RefObject, useLayoutEffect, useState } from "react";

/**
 * How many items of a bar fit before the overflow button. The widths come from
 * a hidden copy of the items (`measure`), so hidden ones keep being measured.
 */
export function useOverflow(
  bar: RefObject<HTMLElement | null>,
  measure: RefObject<HTMLElement | null>,
  count: number,
  reserve: number,
): number {
  const [fit, setFit] = useState(count);

  useLayoutEffect(() => {
    const element = bar.current;
    const copy = measure.current;
    if (!element || !copy) return;
    const update = () => {
      const widths = Array.from(copy.children, (child) => (child as HTMLElement).offsetWidth);
      const total = widths.reduce((a, b) => a + b, 0);
      const room = element.clientWidth;
      if (total <= room) {
        setFit(count);
        return;
      }
      let used = reserve;
      let n = 0;
      for (const width of widths) {
        if (used + width > room) break;
        used += width;
        n += 1;
      }
      setFit(Math.max(1, n));
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [bar, measure, count, reserve]);

  return Math.min(fit, count);
}
