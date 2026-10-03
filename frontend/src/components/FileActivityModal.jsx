import { useEffect, useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import ActivityList from "./ActivityList.jsx";
import useEscapeKey from "../lib/useEscapeKey";
import { CloseIcon } from "./Icons.jsx";

/** Phase 3: full activity log for one file (owner only, per the API). */
export default function FileActivityModal({ file, onClose }) {
  useEscapeKey(onClose);
  const { token } = useAuth();
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiRequest(`/files/${file.id}/activity`, { token })
      .then(setItems)
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 404
            ? "Only the file's owner can see its activity."
            : "Could not load activity."
        )
      );
  }, [file.id, token]);

  return (
    <div className="fixed inset-0 bg-slate-900/20 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 w-full max-w-lg p-6 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-slate-800 truncate">Activity: {file.filename}</h2>
          <button onClick={onClose} className="p-1 -m-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100" aria-label="Close">
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>
        {error ? (
          <p className="text-sm text-slate-500">{error}</p>
        ) : items === null ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-slate-400">
            No activity recorded yet. (Activity is tracked from the moment this feature was installed.)
          </p>
        ) : (
          <div className="max-h-96 overflow-y-auto border border-slate-200 rounded-lg px-3">
            <ActivityList items={items} />
          </div>
        )}
      </div>
    </div>
  );
}
