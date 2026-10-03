import { useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import useEscapeKey from "../lib/useEscapeKey";
import { CloseIcon } from "./Icons.jsx";
import FileIcon from "./FileIcon.jsx";

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

function formatIdle(days) {
  if (days >= 365) {
    const years = Math.floor(days / 365);
    return `${years} year${years === 1 ? "" : "s"}`;
  }
  return `${days} day${days === 1 ? "" : "s"}`;
}

/**
 * Phase 3: "you haven't opened these in a year -- delete them?" prompt.
 * `files` comes from GET /analytics/stale-files. Deleting goes through the
 * normal DELETE /files/{id}, so everything lands in the recycle bin and
 * stays restorable; "Keep" snoozes the prompt for that file server-side;
 * "Ask me later" just closes it for this session.
 */
export default function StaleFilesModal({ files, onClose, onChanged }) {
  useEscapeKey(onClose);
  const { token, refreshUser } = useAuth();
  const { notify } = useToast();
  const [remaining, setRemaining] = useState(files);
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);

  const allSelected = remaining.length > 0 && selected.size === remaining.length;
  const selectedBytes = remaining.filter((f) => selected.has(f.id)).reduce((sum, f) => sum + f.size_bytes, 0);

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(remaining.map((f) => f.id)));
  }

  async function act(kind) {
    const ids = [...selected];
    if (ids.length === 0) return;
    if (kind === "delete" && !window.confirm(`Move ${ids.length} file${ids.length === 1 ? "" : "s"} to the recycle bin?`)) return;

    setBusy(true);
    const done = [];
    for (const id of ids) {
      try {
        if (kind === "delete") {
          await apiRequest(`/files/${id}`, { method: "DELETE", token });
        } else {
          await apiRequest(`/analytics/stale-files/${id}/keep`, { method: "POST", token });
        }
        done.push(id);
      } catch (err) {
        const name = remaining.find((f) => f.id === id)?.filename ?? "file";
        notify(err instanceof ApiError ? `${name}: ${err.detail}` : `Could not update ${name}`);
      }
    }
    setBusy(false);

    if (done.length) {
      notify(
        kind === "delete"
          ? `Moved ${done.length} file${done.length === 1 ? "" : "s"} to the recycle bin`
          : `Keeping ${done.length} file${done.length === 1 ? "" : "s"} -- we won't ask again for a year`,
        "success"
      );
      const left = remaining.filter((f) => !done.includes(f.id));
      setRemaining(left);
      setSelected(new Set());
      onChanged?.();
      if (kind === "delete") refreshUser();
      if (left.length === 0) onClose();
    }
  }

  return (
    <div className="fixed inset-0 bg-slate-900/20 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 w-full max-w-xl p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-800">Files you haven't opened in a while</h2>
            <p className="text-sm text-slate-500 mt-1">
              {remaining.length} file{remaining.length === 1 ? "" : "s"} not opened or changed in over a year. Do you
              still need {remaining.length === 1 ? "it" : "them"}? Deleted files go to the recycle bin and can be restored.
            </p>
          </div>
          <button onClick={onClose} className="p-1 -m-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100" aria-label="Close">
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>

        <div className="border border-slate-200 rounded-lg">
          <label className="flex items-center gap-3 px-3 py-2 border-b bg-slate-50 text-xs text-slate-500">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} disabled={busy} />
            Select all
          </label>
          <ul className="divide-y divide-slate-100 max-h-72 overflow-y-auto">
            {remaining.map((f) => (
              <li key={f.id}>
                <label className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer hover:bg-slate-50">
                  <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} disabled={busy} />
                  <FileIcon filename={f.filename} />
                  <div className="min-w-0 flex-1">
                    <p className="text-slate-800 truncate">{f.filename}</p>
                    <p className="text-xs text-slate-400 truncate">
                      {f.folder_path} &middot; last used {new Date(f.last_activity_at).toLocaleDateString()} (
                      {formatIdle(f.days_idle)} ago)
                    </p>
                  </div>
                  <span className="text-xs text-slate-500 whitespace-nowrap">{formatBytes(f.size_bytes)}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <button onClick={onClose} disabled={busy} className="text-sm text-slate-500 hover:underline disabled:opacity-50">
            Ask me later
          </button>
          <div className="flex gap-2">
            <button
              onClick={() => act("keep")}
              disabled={busy || selected.size === 0}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Keep selected
            </button>
            <button
              onClick={() => act("delete")}
              disabled={busy || selected.size === 0}
              className="rounded-lg bg-rose-600 px-3 py-1.5 text-sm text-white hover:bg-rose-700 disabled:opacity-50"
            >
              {busy ? "Working..." : `Delete selected${selected.size ? ` (${formatBytes(selectedBytes)})` : ""}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
