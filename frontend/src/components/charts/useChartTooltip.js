import { useCallback, useState } from "react";

// Hover/focus readout state, shared by every chart. The rendering half lives
// in ChartTooltip.jsx (this file stays JSX-free so it can be a .js module).
//
// Keyboard focus shows exactly what hover shows — that parity is the point; a
// mouse-only tooltip hides data from keyboard and screen-reader users.
export function useChartTooltip() {
  const [tip, setTip] = useState(null); // { xPct, yPct, title, rows: [{label,value,color}] }

  const show = useCallback((next) => setTip(next), []);
  const hide = useCallback(() => setTip(null), []);

  return { tip, show, hide };
}
