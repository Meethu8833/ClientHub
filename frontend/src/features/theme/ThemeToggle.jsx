import { Icon } from "../../components/ui/Icon";
import { THEMES } from "./theme";
import { useTheme } from "./useTheme";

// One button that cycles Light → Dark → System.
//
// A cycling button (rather than a dropdown) keeps the topbar to a single 40px
// target, and the three states are cheap to walk through. The accessibility
// work is in the labelling: the icon alone can't say which mode is active, so
//
//   * `aria-label` states the CURRENT mode and what clicking will do — an
//     icon-only control must carry its own name;
//   * the visible `title` gives sighted mouse users the same information;
//   * an `aria-live` region announces the change after the click, because the
//     button's own label changing is not reliably announced on its own.
//
// While on System the icon shows a monitor, not the resolved look — the state
// being communicated is the PREFERENCE, and "System" is a distinct choice.

const CONFIG = {
  [THEMES.LIGHT]: { icon: "sun", label: "Light", next: "dark" },
  [THEMES.DARK]: { icon: "moon", label: "Dark", next: "system" },
  [THEMES.SYSTEM]: { icon: "monitor", label: "System", next: "light" },
};

export function ThemeToggle() {
  const { preference, resolved, cycleTheme } = useTheme();
  const { icon, label, next } = CONFIG[preference] ?? CONFIG[THEMES.SYSTEM];

  // "System" is the only preference whose name doesn't tell you the result.
  const description = preference === THEMES.SYSTEM ? `System (currently ${resolved})` : label;

  return (
    <>
      <button
        type="button"
        onClick={cycleTheme}
        title={`Theme: ${description} — click to switch to ${next}`}
        aria-label={`Theme: ${description}. Switch to ${next} mode.`}
        className="flex h-9 w-9 items-center justify-center rounded-md text-gray-500
          transition-colors hover:bg-gray-100 hover:text-gray-700
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600
          focus-visible:ring-offset-2 focus-visible:ring-offset-white
          dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200
          dark:focus-visible:ring-offset-gray-900"
      >
        <Icon name={icon} />
      </button>

      {/* Announces the change for screen-reader users after the click. */}
      <span aria-live="polite" className="sr-only">
        {`${description} theme`}
      </span>
    </>
  );
}
