import { useEffect } from "react";

/** Calls `onEscape` when the Escape key is pressed -- used by every modal to close itself. */
export default function useEscapeKey(onEscape) {
  useEffect(() => {
    if (!onEscape) return;
    const handler = (e) => e.key === "Escape" && onEscape();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onEscape]);
}
