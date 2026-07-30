import { useLayoutEffect, useRef, useState } from "react";

// Measures the chart container so the SVG can be drawn in REAL pixel units.
//
// Why not just a viewBox + `width: 100%`? Because a viewBox scales everything
// uniformly — stretch a 560×210 box across a full-width card and the axis
// text scales up with it (unreadably large), while `preserveAspectRatio`
// letterboxes the plot into the middle and wastes the width. Drawing at the
// measured width instead keeps type at a fixed size and lets only the PLOT
// get wider, which is what a wider card should buy you.
export function useChartWidth(fallback = 560) {
  const ref = useRef(null);
  const [width, setWidth] = useState(fallback);

  // useLayoutEffect + a synchronous first measure: the chart paints at the
  // right width immediately, instead of flashing at the fallback width for a
  // frame and then snapping (which also made it easy to screenshot the wrong
  // one). The observer then keeps it correct on resize.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Clamp to the ancestor chain's client width. During the first layout
    // pass the element can briefly report a width wider than the viewport
    // (before padding/scrollbars settle); without this the chart would latch
    // onto that stale value and overflow the card on narrow screens.
    const measure = () => {
      let w = el.getBoundingClientRect().width;
      for (let p = el.parentElement; p; p = p.parentElement) {
        if (p.clientWidth > 0) w = Math.min(w, p.clientWidth);
      }
      if (w > 0) setWidth((prev) => (Math.abs(prev - w) > 0.5 ? w : prev));
    };

    measure();

    const ro = new ResizeObserver(measure);
    ro.observe(el);
    // The element's own box can stay put while an ancestor narrows, so watch
    // the viewport too.
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return [ref, width];
}
