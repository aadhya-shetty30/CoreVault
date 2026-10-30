import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL, apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import useEscapeKey from "../lib/useEscapeKey";
import { CloseIcon } from "./Icons.jsx";

export default function CollaborativeEditorModal({ file, onClose, onChanged }) {
  useEscapeKey(onClose);
  const { token } = useAuth();
  const { notify } = useToast();
  const [document, setDocument] = useState(null);
  const [content, setContent] = useState("");
  const [status, setStatus] = useState("Loading document…");
  const [collaborators, setCollaborators] = useState([]);
  const [canEdit, setCanEdit] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const timer = useRef(null);
  const contentRef = useRef("");
  const docRef = useRef(null);
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const data = await apiRequest(`/files/${file.id}/document`, { token });
      setDocument(data);
      docRef.current = data;
      setContent(data.content);
      contentRef.current = data.content;
      setStatus("Connected");
    } catch (err) {
      setStatus(err instanceof ApiError ? String(err.detail) : "Could not open document");
    }
  }, [file.id, token]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!token) return undefined;
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const apiUrl = new URL(API_BASE_URL);
    const socket = new WebSocket(`${scheme}//${apiUrl.host}/files/${file.id}/collaboration?token=${encodeURIComponent(token)}`);
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "presence" && message.can_edit !== undefined) setCanEdit(message.can_edit);
      if (message.type === "presence" && message.online !== undefined) {
        setCollaborators((prev) => message.online
          ? [...new Set([...prev, message.username])]
          : prev.filter((name) => name !== message.username));
      }
      if (message.type === "saved" && message.username) {
        docRef.current = { ...docRef.current, content: message.content, content_hash: message.content_hash };
        if (!dirtyRef.current && !savingRef.current) {
          contentRef.current = message.content;
          setContent(message.content);
          setStatus(`Saved by ${message.username}`);
        } else if (message.content !== contentRef.current) {
          setStatus(`A newer edit from ${message.username} is available. Reload to continue.`);
          dirtyRef.current = false;
        }
      }
    };
    socket.onopen = () => setStatus("Connected");
    socket.onerror = () => setStatus("Live connection unavailable");
    return () => socket.close();
  }, [file.id, token]);

  const save = useCallback(async (nextContent) => {
    if (!docRef.current || !dirtyRef.current || savingRef.current || !canEdit) return;
    savingRef.current = true;
    setStatus("Saving…");
    try {
      const result = await apiRequest(`/files/${file.id}/document`, {
        method: "PUT", token,
        json: { content: nextContent, base_hash: docRef.current.content_hash },
      });
      docRef.current = { ...docRef.current, content: nextContent, content_hash: result.content_hash };
      dirtyRef.current = false;
      setStatus("All changes saved");
      onChanged?.();
    } catch (err) {
      setStatus(err instanceof ApiError && err.status === 409 ? "Conflict: reload the latest version before editing" : "Save failed");
      if (err instanceof ApiError && err.status === 409) notify(String(err.detail));
      else notify(err instanceof ApiError ? String(err.detail) : "Could not save document");
    } finally {
      savingRef.current = false;
    }
  }, [canEdit, file.id, notify, onChanged, token]);

  function changeContent(value) {
    contentRef.current = value;
    dirtyRef.current = true;
    setContent(value);
    setStatus("Unsaved changes…");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => save(value), 900);
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center">
      <section className="w-full max-w-6xl h-[90vh] bg-white rounded-2xl shadow-2xl ring-1 ring-slate-900/10 flex flex-col overflow-hidden">
        <header className="flex items-center justify-between gap-4 px-5 py-4 border-b border-slate-100">
          <div className="min-w-0"><h2 className="font-semibold text-slate-900 truncate">{file.filename}</h2><p className="text-xs text-slate-500 mt-1">{status}{collaborators.length ? ` · Here now: ${collaborators.join(", ")}` : ""}{status.startsWith("A newer edit") || status.startsWith("Conflict:") ? <button onClick={load} className="ml-2 text-indigo-600 underline">Reload latest</button> : null}</p></div>
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={() => setVersionOpen((value) => !value)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">{versionOpen ? "Hide history" : "Version history"}</button>
            <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-slate-100" aria-label="Close"><CloseIcon className="w-5 h-5" /></button>
          </div>
        </header>
        <div className="flex-1 min-h-0 flex">
          <textarea value={content} onChange={(event) => changeContent(event.target.value)} readOnly={!canEdit} spellCheck={false} aria-label="Shared document editor" placeholder="This document is empty" className="flex-1 resize-none p-5 sm:p-7 font-mono text-sm leading-6 text-slate-800 outline-none disabled:bg-slate-50" />
          {versionOpen && <aside className="w-72 border-l border-slate-100 overflow-auto p-4"><h3 className="font-medium text-sm mb-3">Previous versions</h3><VersionList fileId={file.id} token={token} onRestore={load} /></aside>}
        </div>
        <footer className="border-t border-slate-100 px-5 py-2 text-xs text-slate-400">{canEdit ? "Edits save automatically and appear for collaborators." : "You have view access."}</footer>
      </section>
    </div>
  );
}

function VersionList({ fileId, token, onRestore }) {
  const [versions, setVersions] = useState(null);
  useEffect(() => { apiRequest(`/files/${fileId}/versions`, { token }).then(setVersions).catch(() => setVersions([])); }, [fileId, token]);
  async function restore(version) {
    try { await apiRequest(`/files/${fileId}/versions/${version.id}/restore`, { method: "POST", token }); await onRestore(); }
    catch { /* the file version history remains available if a restore fails */ }
  }
  if (!versions) return <p className="text-xs text-slate-400">Loading…</p>;
  if (!versions.length) return <p className="text-xs text-slate-400">No saved versions yet.</p>;
  return <ul className="divide-y divide-slate-100">{versions.map((version, index) => <li key={version.id} className="py-3"><p className="text-sm text-slate-700">Version {version.version_number}{index === 0 ? " · current" : ""}</p><p className="text-xs text-slate-400 mt-1">{new Date(version.modified_at).toLocaleString()}</p>{index > 0 && <button onClick={() => restore(version)} className="text-xs text-indigo-600 mt-2 hover:underline">Restore</button>}</li>)}</ul>;
}
