import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { API_BASE_URL, apiRequest, ApiError } from "../api/client";
import AuthLayout from "../components/AuthLayout.jsx";
import FileIcon from "../components/FileIcon.jsx";
import { DownloadIcon } from "../components/Icons.jsx";

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

/**
 * Public, unauthenticated landing page for a shared_links token
 * (GET /shared/{token}/info -- no Authorization header, see
 * app/routers/shared.py). The actual download is a plain link to
 * GET /shared/{token}: that endpoint streams the file directly, so letting
 * the browser navigate there natively (rather than fetching a blob via JS)
 * is simplest and lets the browser's own download UI handle it.
 */
export default function SharedLinkPage() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiRequest(`/shared/${token}/info`)
      .then(setInfo)
      .catch((err) => setError(err instanceof ApiError ? String(err.detail) : "This link could not be loaded"));
  }, [token]);

  return (
    <AuthLayout>
      <div className="space-y-4 text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Someone shared a file with you</p>
        {error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : info === null ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : !info.valid ? (
          <p className="text-sm text-red-600">{info.reason || "This link is no longer valid."}</p>
        ) : (
          <>
            <div className="flex justify-center">
              <FileIcon filename={info.filename} size="lg" />
            </div>
            <p className="text-slate-800 font-medium break-all">{info.filename}</p>
            <p className="text-sm text-slate-400">
              {formatBytes(info.size_bytes)} &middot; shared as {info.role}
            </p>
            <a
              href={`${API_BASE_URL}/shared/${token}`}
              className="inline-flex items-center justify-center gap-2 w-full rounded-lg bg-indigo-600 py-2.5 text-sm text-white font-medium shadow-sm hover:bg-indigo-700"
            >
              <DownloadIcon className="w-4 h-4" />
              Download
            </a>
          </>
        )}
      </div>
    </AuthLayout>
  );
}
