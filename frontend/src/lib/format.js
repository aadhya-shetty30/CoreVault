export function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function formatDate(iso) {
  const d = new Date(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

/** URL of a folder in the file browser; null/"root" is the user's top level ("My files"). */
export function folderUrl(id) {
  return id && id !== "root" ? `/app/${id}` : "/app";
}

// Mirrors the extension -> category table in backend/app/routers/analytics.py.
const CATEGORY_EXTENSIONS = {
  Images: "jpg jpeg png gif bmp webp svg heic heif tif tiff ico raw",
  Videos: "mp4 mkv mov avi webm wmv flv m4v 3gp",
  Audio: "mp3 wav flac aac ogg m4a wma opus",
  Documents: "pdf doc docx txt md rtf odt xls xlsx csv ods ppt pptx odp epub tex",
  Archives: "zip rar 7z tar gz bz2 xz tgz iso dmg",
  Code: "py js jsx ts tsx java c cpp h hpp cs go rs rb php html css json xml yml yaml sql sh ipynb kt swift",
};
const EXTENSION_TO_CATEGORY = Object.fromEntries(
  Object.entries(CATEGORY_EXTENSIONS).flatMap(([cat, exts]) => exts.split(" ").map((e) => [e, cat]))
);

export function fileExtension(filename) {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(dot + 1).toLowerCase() : "";
}

export function fileCategory(filename) {
  return EXTENSION_TO_CATEGORY[fileExtension(filename)] ?? "Other";
}

export function formatDuration(days) {
  if (days < 1) return "now";
  if (days < 60) return `${days} day${days === 1 ? "" : "s"}`;
  if (days < 730) return `${Math.round(days / 30)} months`;
  return `${(days / 365).toFixed(1)} years`;
}

export function formatLongDate(isoDate) {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}
