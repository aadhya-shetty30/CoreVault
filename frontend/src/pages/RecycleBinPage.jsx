import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { formatBytes, formatDate } from "../lib/format";
import AppShell from "../components/AppShell.jsx";
import FileIcon from "../components/FileIcon.jsx";
import { RestoreIcon, TrashIcon } from "../components/Icons.jsx";

export default function RecycleBinPage() {
  const { token } = useAuth();
  const { notify } = useToast();
  const [items, setItems] = useState(null);
  const [restoringId, setRestoringId] = useState(null);

  const load = useCallback(async () => {
    try {
      setItems(await apiRequest("/recycle-bin", { token }));
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not load recycle bin");
    }
  }, [token, notify]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRestore(item) {
    setRestoringId(item.id);
    try {
      await apiRequest(`/recycle-bin/${item.id}/restore`, { method: "POST", token });
      notify(`Restored "${item.filename}"`, "success");
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not restore file");
    } finally {
      setRestoringId(null);
    }
  }

  return (
    <AppShell>
      <div className="max-w-4xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Recycle bin</h1>
          <p className="text-sm text-slate-500 mt-1">
            Deleted files stay here for 30 days before they're removed for good. Restore anything you still need.
          </p>
        </div>

        {items === null ? (
          <div className="space-y-3">
            {[0, 1].map((i) => (
              <div key={i} className="h-14 rounded-xl bg-white ring-1 ring-slate-200/60 animate-pulse" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl bg-white ring-1 ring-slate-200/80 px-6 py-16 text-center">
            <span className="mx-auto w-14 h-14 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center">
              <TrashIcon className="w-7 h-7" />
            </span>
            <h2 className="mt-4 font-semibold text-slate-800">Recycle bin is empty</h2>
            <p className="mt-1 text-sm text-slate-500">Files you delete will show up here.</p>
          </div>
        ) : (
          <ul className="rounded-xl bg-white ring-1 ring-slate-200/80 shadow-sm divide-y divide-slate-100 overflow-hidden">
            {items.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-4 py-3">
                <FileIcon filename={item.filename} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-800 truncate">{item.filename}</p>
                  <p className="text-xs text-slate-400">
                    {formatBytes(item.size_bytes)} &middot; deleted {formatDate(item.deleted_at)}
                  </p>
                </div>
                <span
                  className={`hidden sm:inline-block text-xs font-medium rounded-full px-2.5 py-1 ${
                    item.days_remaining <= 3 ? "bg-rose-50 text-rose-600" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {item.days_remaining} day{item.days_remaining === 1 ? "" : "s"} left
                </span>
                <button
                  onClick={() => handleRestore(item)}
                  disabled={restoringId === item.id}
                  className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 disabled:opacity-50"
                >
                  <RestoreIcon className="w-4 h-4" />
                  {restoringId === item.id ? "Restoring..." : "Restore"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
