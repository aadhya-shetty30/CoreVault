import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import useEscapeKey from "../lib/useEscapeKey";
import { CloseIcon } from "./Icons.jsx";

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export default function FileVersionsModal({ file, onClose, onRestored }) {
  useEscapeKey(onClose);
  const { token } = useAuth();
  const { notify } = useToast();
  const [versions, setVersions] = useState(null);
  const [restoringId, setRestoringId] = useState(null);

  const load = useCallback(async () => {
    try {
      setVersions(await apiRequest(`/files/${file.id}/versions`, { token }));
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not load version history");
    }
  }, [file.id, token, notify]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRestore(version) {
    setRestoringId(version.id);
    try {
      await apiRequest(`/files/${file.id}/versions/${version.id}/restore`, { method: "POST", token });
      notify(`Restored version ${version.version_number}`, "success");
      await load();
      onRestored?.();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not restore version");
    } finally {
      setRestoringId(null);
    }
  }

  return (
    <div className="fixed inset-0 bg-slate-900/20 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-800">Version history: {file.filename}</h2>
          <button onClick={onClose} className="p-1 -m-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100" aria-label="Close">
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>
        {versions === null ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : versions.length === 0 ? (
          <p className="text-sm text-slate-400">No versions yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100 border border-slate-200 rounded-lg">
            {versions.map((v, idx) => (
              <li key={v.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <div>
                  <p className="text-slate-800">
                    Version {v.version_number} {idx === 0 && <span className="text-xs text-indigo-600">(current)</span>}
                  </p>
                  <p className="text-xs text-slate-400">
                    {formatBytes(v.size_bytes)} &middot; {new Date(v.modified_at).toLocaleString()}
                  </p>
                </div>
                {idx !== 0 && (
                  <button
                    onClick={() => handleRestore(v)}
                    disabled={restoringId === v.id}
                    className="text-xs text-indigo-600 hover:underline disabled:opacity-50"
                  >
                    {restoringId === v.id ? "Restoring..." : "Restore"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
