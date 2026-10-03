import { fileCategory, fileExtension } from "../lib/format";

// Soft tinted tile per file type; the hues match the dashboard's donut colors.
const STYLES = {
  Images: "bg-blue-50 text-blue-600 ring-blue-100",
  Videos: "bg-orange-50 text-orange-600 ring-orange-100",
  Audio: "bg-emerald-50 text-emerald-600 ring-emerald-100",
  Documents: "bg-amber-50 text-amber-700 ring-amber-100",
  Archives: "bg-pink-50 text-pink-600 ring-pink-100",
  Code: "bg-green-50 text-green-700 ring-green-100",
  Other: "bg-slate-100 text-slate-500 ring-slate-200",
};

/** A small rounded tile showing the file's extension, tinted by file type. */
export default function FileIcon({ filename, size = "md" }) {
  const ext = fileExtension(filename).slice(0, 4) || "file";
  const dims = size === "lg" ? "w-14 h-14 text-xs" : "w-9 h-9 text-[10px]";
  return (
    <span
      className={`${dims} ${STYLES[fileCategory(filename)]} shrink-0 rounded-lg ring-1 ring-inset flex items-center justify-center font-semibold uppercase tracking-wide`}
      aria-hidden="true"
    >
      {ext}
    </span>
  );
}
