import { useEffect, useRef, type RefObject } from "react";

/** Marks every .reveal descendant (or the node itself) with [data-in] as it enters the viewport.
 *  data-in, not a class: React re-renders rewrite className and would wipe an observer-added class.
 *  Pass `dep` when revealed content renders after a data fetch, so new nodes get observed. */
export function useReveal<T extends HTMLElement>(dep?: unknown): RefObject<T | null> {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.setAttribute("data-in", "");
            io.unobserve(e.target);
          }
        }
      },
      { threshold: 0.12 },
    );
    const targets = el.classList.contains("reveal")
      ? [el]
      : Array.from(el.querySelectorAll<HTMLElement>(".reveal"));
    targets.forEach((t) => io.observe(t));
    return () => io.disconnect();
  }, [dep]);
  return ref;
}
