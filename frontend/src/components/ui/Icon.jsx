// Inline icon set.
//
// Hand-rolled rather than a dependency: the dashboard needs six glyphs, and
// an icon package would ship thousands. `public/icons.svg` is still the stock
// Vite placeholder sprite (bluesky/discord/github) and is unrelated to the app.
//
// All are 24×24, 1.5px stroke, currentColor — so they inherit the tone colour
// from their container. Always aria-hidden: an icon here always sits beside a
// real text label (or, for icon-only buttons, an aria-label on the button), so
// announcing the glyph itself would only duplicate that text.
//
// A value may be a single path string or an array of them (the sun needs a
// disc plus its rays).

const PATHS = {
  clients:
    "M17 20h5v-2a3 3 0 0 0-4-2.8M9 20H4v-2a3 3 0 0 1 4-2.8m9-4.7a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3-4a2 2 0 1 1-4 0 2 2 0 0 1 4 0ZM8 8.5a2 2 0 1 1-4 0 2 2 0 0 1 4 0ZM17 20H7v-1.5a3.5 3.5 0 0 1 3.5-3.5h3a3.5 3.5 0 0 1 3.5 3.5V20Z",
  projects: "M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
  tasks: "M9 5h10M9 12h10M9 19h10M4.5 5 5.5 6l2-2M4.5 12l1 1 2-2M4.5 19l1 1 2-2",
  tickets:
    "M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v3a2 2 0 0 0 0 4v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3a2 2 0 0 0 0-4V6Z",
  quotations:
    "M14 3v4a1 1 0 0 0 1 1h4M8 13h8M8 17h5M6 3h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z",
  billing:
    "M12 6v12M15 9.5c0-1-1.3-1.8-3-1.8s-3 .8-3 1.8 1.3 1.6 3 2 3 1 3 2-1.3 1.8-3 1.8-3-.8-3-1.8",
  alert:
    "M12 9v4m0 3h.01M10.3 4.3 2.6 17.5A1.8 1.8 0 0 0 4.2 20h15.6a1.8 1.8 0 0 0 1.6-2.5L13.7 4.3a1.8 1.8 0 0 0-3.4 0Z",

  // Theme toggle glyphs.
  sun: [
    "M12 4V2M12 22v-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M4 12H2M22 12h-2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4",
    "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  ],
  moon: "M20 13.5A8.5 8.5 0 0 1 10.5 4a1 1 0 0 0-1.2-1.2 9.5 9.5 0 1 0 11.9 11.9 1 1 0 0 0-1.2-1.2Z",
  // "System": a monitor — the theme follows the device.
  monitor:
    "M3 5.5a1.5 1.5 0 0 1 1.5-1.5h15A1.5 1.5 0 0 1 21 5.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 14.5v-9ZM9 20h6M12 16v4",
};

export function Icon({ name, className = "h-5 w-5" }) {
  const d = PATHS[name];
  if (!d) return null;
  const paths = Array.isArray(d) ? d : [d];

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {paths.map((p) => (
        <path key={p} d={p} />
      ))}
    </svg>
  );
}
