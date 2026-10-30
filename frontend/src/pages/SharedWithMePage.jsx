import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import AppShell from "../components/AppShell.jsx";
import CollaborativeEditorModal from "../components/CollaborativeEditorModal.jsx";
import FileIcon from "../components/FileIcon.jsx";
import { formatBytes, formatDate } from "../lib/format";

export default function SharedWithMePage() {
  const { token } = useAuth();
  const { notify } = useToast();
  const [files, setFiles] = useState(null);
  const [selected, setSelected] = useState(null);
  const load = useCallback(async () => {
    try { setFiles(await apiRequest("/files/shared-with-me", { token })); }
    catch (err) { notify(err instanceof ApiError ? String(err.detail) : "Could not load shared files"); setFiles([]); }
  }, [token, notify]);
  useEffect(() => { load(); }, [load]);

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-6">
        <div><h1 className="text-2xl font-semibold tracking-tight text-slate-900">Shared with me</h1><p className="mt-1 text-sm text-slate-500">Files other people have shared with your account.</p></div>
        {files === null ? <p className="text-sm text-slate-400">Loading…</p> : files.length === 0 ? (
          <div className="rounded-2xl bg-white ring-1 ring-slate-200/80 px-6 py-16 text-center"><h2 className="font-semibold text-slate-800">No files shared yet</h2><p className="mt-1 text-sm text-slate-500">Ask the owner to share a file with your email or username.</p></div>
        ) : (
          <ul className="rounded-xl bg-white ring-1 ring-slate-200/80 shadow-sm divide-y divide-slate-100">
            {files.map((file) => <li key={file.id} className="flex items-center gap-3 px-4 py-3">
              <FileIcon filename={file.filename} />
              <div className="min-w-0 flex-1"><p className="text-sm font-medium text-slate-800 truncate">{file.filename}</p><p className="text-xs text-slate-400">{file.role} · {formatBytes(file.size_bytes)} · {formatDate(file.updated_at)}</p></div>
              {file.role !== "viewer" && <button onClick={() => setSelected(file)} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700">Edit together</button>}
              {file.role === "viewer" && <button onClick={() => setSelected(file)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">Open</button>}
            </li>)}
          </ul>
        )}
      </div>
      {selected && <CollaborativeEditorModal file={selected} onClose={() => setSelected(null)} onChanged={load} />}
    </AppShell>
  );
}
