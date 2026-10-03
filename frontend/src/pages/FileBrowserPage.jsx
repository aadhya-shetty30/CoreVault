import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiRequest, ApiError } from "../api/client";
import { uploadFileSmart } from "../api/upload";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { folderUrl, formatBytes, formatDate } from "../lib/format";
import AppShell from "../components/AppShell.jsx";
import Breadcrumb from "../components/Breadcrumb.jsx";
import UploadZone from "../components/UploadZone.jsx";
import FileIcon from "../components/FileIcon.jsx";
import FileVersionsModal from "../components/FileVersionsModal.jsx";
import ShareModal from "../components/ShareModal.jsx";
import StaleFilesModal from "../components/StaleFilesModal.jsx";
import FileActivityModal from "../components/FileActivityModal.jsx";
import {
  ActivityIcon,
  DownloadIcon,
  DotsIcon,
  FolderIcon,
  FolderPlusIcon,
  HistoryIcon,
  ShareIcon,
  TrashIcon,
  UploadIcon,
} from "../components/Icons.jsx";

// Phase 3: the stale-file prompt opens automatically at most once per login
// (the JWT lives in memory, so a new token == a new login). Module-level
// rather than component state so navigating to the recycle bin/dashboard
// and back doesn't re-prompt.
let staleCheckedForToken = null;

function IconButton({ label, onClick, danger = false, children }) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`p-2 rounded-lg transition-colors ${
        danger ? "text-slate-400 hover:text-rose-600 hover:bg-rose-50" : "text-slate-400 hover:text-indigo-600 hover:bg-indigo-50"
      }`}
    >
      {children}
    </button>
  );
}

/** Phone-sized overflow menu for a file row (desktop shows the icon buttons instead). */
function RowMenu({ actions }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div className="relative" ref={ref}>
      <IconButton label="More actions" onClick={() => setOpen((o) => !o)}>
        <DotsIcon className="w-4 h-4" />
      </IconButton>
      {open && (
        <div role="menu" className="absolute right-0 mt-1 w-48 rounded-xl bg-white shadow-lg ring-1 ring-slate-200 py-1.5 z-30">
          {actions.map(({ label, icon: ActionIcon, onClick, danger }) => (
            <button
              key={label}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onClick();
              }}
              className={`w-full flex items-center gap-3 px-3.5 py-2 text-sm hover:bg-slate-50 ${danger ? "text-rose-600" : "text-slate-700"}`}
            >
              <ActionIcon className={`w-4 h-4 ${danger ? "" : "text-slate-400"}`} />
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function FileBrowserPage() {
  const { folderId } = useParams(); // undefined at the top level ("My files"), else a folder UUID
  const navigate = useNavigate();
  const { token, refreshUser } = useAuth();
  const { notify } = useToast();
  const uploadZoneRef = useRef(null);

  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [uploads, setUploads] = useState([]); // [{ name, progress }] -- in-flight uploads, for the progress list
  const [treeRefreshKey, setTreeRefreshKey] = useState(0);
  const [versionsFile, setVersionsFile] = useState(null);
  const [shareFile, setShareFile] = useState(null);
  const [staleFiles, setStaleFiles] = useState(null);
  const [activityFile, setActivityFile] = useState(null);

  const currentFolderId = folderId && folderId !== "root" ? folderId : null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const path = currentFolderId ? `/folders/${currentFolderId}` : "/folders/root";
      const data = await apiRequest(path, { token });
      setDetail(data);
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Failed to load folder");
      if (err instanceof ApiError && err.status === 404) navigate(folderUrl(null));
    } finally {
      setLoading(false);
    }
  }, [currentFolderId, token, notify, navigate]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!token || staleCheckedForToken === token) return;
    staleCheckedForToken = token;
    apiRequest("/analytics/stale-files", { token })
      .then((files) => {
        if (files.length) setStaleFiles(files);
      })
      .catch(() => {
        // Best-effort nudge -- never block or toast the file browser over it.
      });
  }, [token]);

  function goToFolder(id) {
    navigate(folderUrl(id));
  }

  async function handleNewFolder() {
    const name = window.prompt("New folder name:");
    if (!name) return;
    try {
      await apiRequest("/folders", { method: "POST", token, json: { name, parent_folder_id: currentFolderId } });
      notify("Folder created", "success");
      setTreeRefreshKey((k) => k + 1);
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not create folder");
    }
  }

  async function handleUpload(file) {
    setUploads((prev) => [...prev, { name: file.name, progress: 0 }]);
    try {
      await uploadFileSmart(file, currentFolderId, token, (fraction) => {
        setUploads((prev) => prev.map((u) => (u.name === file.name ? { ...u, progress: fraction } : u)));
      });
      notify(`Uploaded ${file.name}`, "success");
      load();
      refreshUser();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : `Failed to upload ${file.name}`);
    } finally {
      setUploads((prev) => prev.filter((u) => u.name !== file.name));
    }
  }

  async function handleDownload(file) {
    try {
      const blob = await apiRequest(`/files/${file.id}/download`, { token });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Download failed");
    }
  }

  async function handleDeleteFile(file) {
    if (!window.confirm(`Move "${file.filename}" to the recycle bin?`)) return;
    try {
      await apiRequest(`/files/${file.id}`, { method: "DELETE", token });
      notify("Moved to recycle bin", "success");
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not delete file");
    }
  }

  async function handleDeleteFolder(folder) {
    if (!window.confirm(`Delete "${folder.name}" and everything inside it? This cannot be undone.`)) return;
    try {
      await apiRequest(`/folders/${folder.id}`, { method: "DELETE", token });
      notify("Folder deleted", "success");
      setTreeRefreshKey((k) => k + 1);
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not delete folder");
    }
  }

  const folders = detail?.folders ?? [];
  const files = detail?.files ?? [];
  const isEmpty = !loading && folders.length === 0 && files.length === 0;

  return (
    <AppShell selectedFolderId={currentFolderId} treeRefreshKey={treeRefreshKey}>
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
          <div className="min-w-0">
            {detail && detail.breadcrumb.length > 1 && (
              <div className="mb-1 -ml-1">
                <Breadcrumb items={detail.breadcrumb} onNavigate={goToFolder} />
              </div>
            )}
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900 truncate">{detail?.name ?? "My files"}</h1>
            {detail && (
              <p className="text-sm text-slate-500 mt-1">
                {folders.length} folder{folders.length === 1 ? "" : "s"} &middot; {files.length} file
                {files.length === 1 ? "" : "s"}
              </p>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={handleNewFolder}
              className="inline-flex items-center gap-2 rounded-lg bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50"
            >
              <FolderPlusIcon className="w-4 h-4 text-slate-500" />
              New folder
            </button>
            <button
              onClick={() => uploadZoneRef.current?.browse()}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
            >
              <UploadIcon className="w-4 h-4" />
              Upload
            </button>
          </div>
        </div>

        <UploadZone ref={uploadZoneRef} onUpload={handleUpload} uploading={uploads.length > 0} />

        {uploads.length > 0 && (
          <ul className="rounded-xl bg-white ring-1 ring-slate-200/80 shadow-sm divide-y divide-slate-100">
            {uploads.map((u) => (
              <li key={u.name} className="px-4 py-3">
                <div className="flex justify-between text-sm mb-1.5">
                  <span className="truncate text-slate-700">{u.name}</span>
                  <span className="text-slate-500 tabular-nums">{Math.round(u.progress * 100)}%</span>
                </div>
                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-indigo-500 rounded-full transition-all" style={{ width: `${Math.round(u.progress * 100)}%` }} />
                </div>
              </li>
            ))}
          </ul>
        )}

        {loading ? (
          <div className="space-y-3" aria-label="Loading">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-14 rounded-xl bg-white ring-1 ring-slate-200/60 animate-pulse" />
            ))}
          </div>
        ) : isEmpty ? (
          <div className="rounded-2xl bg-white ring-1 ring-slate-200/80 px-6 py-16 text-center">
            <span className="mx-auto w-14 h-14 rounded-2xl bg-indigo-50 text-indigo-500 flex items-center justify-center">
              <FolderIcon className="w-7 h-7" />
            </span>
            <h2 className="mt-4 font-semibold text-slate-800">This folder is empty</h2>
            <p className="mt-1 text-sm text-slate-500">Upload files or create a folder to get started.</p>
          </div>
        ) : (
          <div className="space-y-8">
            {folders.length > 0 && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">Folders</h2>
                <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                  {folders.map((folder) => (
                    <li key={folder.id}>
                      <div
                        onClick={() => goToFolder(folder.id)}
                        className="group flex items-center gap-3 rounded-xl bg-white px-4 py-3 ring-1 ring-slate-200/80 shadow-sm cursor-pointer hover:ring-indigo-200 hover:shadow transition"
                      >
                        <span className="w-9 h-9 rounded-lg bg-indigo-50 text-indigo-500 flex items-center justify-center shrink-0">
                          <FolderIcon className="w-5 h-5" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-slate-800 truncate">{folder.name}</p>
                          <p className="text-xs text-slate-400">Created {formatDate(folder.created_at)}</p>
                        </div>
                        <span onClick={(e) => e.stopPropagation()} className="sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                          <IconButton label={`Delete ${folder.name}`} onClick={() => handleDeleteFolder(folder)} danger>
                            <TrashIcon className="w-4 h-4" />
                          </IconButton>
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {files.length > 0 && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">Files</h2>
                <div className="rounded-xl bg-white ring-1 ring-slate-200/80 shadow-sm overflow-hidden">
                  <div className="hidden md:grid grid-cols-[minmax(0,1fr)_6rem_7rem_13rem] gap-4 px-4 py-2.5 border-b border-slate-100 text-xs font-medium text-slate-400">
                    <span>Name</span>
                    <span className="text-right">Size</span>
                    <span>Modified</span>
                    <span className="sr-only">Actions</span>
                  </div>
                  <ul className="divide-y divide-slate-100">
                    {files.map((file) => (
                      <li
                        key={file.id}
                        className="group grid grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[minmax(0,1fr)_6rem_7rem_13rem] items-center gap-x-4 gap-y-1 px-4 py-2.5 hover:bg-slate-50/70 transition-colors"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <FileIcon filename={file.filename} />
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-slate-800 truncate" title={file.filename}>
                              {file.filename}
                            </p>
                            <p className="md:hidden text-xs text-slate-400">
                              {formatBytes(file.size_bytes)} &middot; {formatDate(file.updated_at)}
                            </p>
                          </div>
                        </div>
                        <span className="hidden md:block text-sm text-slate-500 text-right tabular-nums">{formatBytes(file.size_bytes)}</span>
                        <span className="hidden md:block text-sm text-slate-500">{formatDate(file.updated_at)}</span>
                        <div className="flex md:hidden items-center justify-end">
                          <IconButton label="Download" onClick={() => handleDownload(file)}>
                            <DownloadIcon className="w-4 h-4" />
                          </IconButton>
                          <RowMenu
                            actions={[
                              { label: "Version history", icon: HistoryIcon, onClick: () => setVersionsFile(file) },
                              { label: "Activity", icon: ActivityIcon, onClick: () => setActivityFile(file) },
                              { label: "Share", icon: ShareIcon, onClick: () => setShareFile(file) },
                              { label: "Move to recycle bin", icon: TrashIcon, onClick: () => handleDeleteFile(file), danger: true },
                            ]}
                          />
                        </div>
                        <div className="hidden md:flex items-center justify-end opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                          <IconButton label="Version history" onClick={() => setVersionsFile(file)}>
                            <HistoryIcon className="w-4 h-4" />
                          </IconButton>
                          <IconButton label="Activity" onClick={() => setActivityFile(file)}>
                            <ActivityIcon className="w-4 h-4" />
                          </IconButton>
                          <IconButton label="Share" onClick={() => setShareFile(file)}>
                            <ShareIcon className="w-4 h-4" />
                          </IconButton>
                          <IconButton label="Download" onClick={() => handleDownload(file)}>
                            <DownloadIcon className="w-4 h-4" />
                          </IconButton>
                          <IconButton label="Move to recycle bin" onClick={() => handleDeleteFile(file)} danger>
                            <TrashIcon className="w-4 h-4" />
                          </IconButton>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </section>
            )}
          </div>
        )}
      </div>

      {versionsFile && (
        <FileVersionsModal file={versionsFile} onClose={() => setVersionsFile(null)} onRestored={load} />
      )}
      {shareFile && <ShareModal file={shareFile} onClose={() => setShareFile(null)} />}
      {staleFiles && <StaleFilesModal files={staleFiles} onClose={() => setStaleFiles(null)} onChanged={load} />}
      {activityFile && <FileActivityModal file={activityFile} onClose={() => setActivityFile(null)} />}
    </AppShell>
  );
}
