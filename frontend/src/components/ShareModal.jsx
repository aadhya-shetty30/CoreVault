import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import useEscapeKey from "../lib/useEscapeKey";
import { CloseIcon } from "./Icons.jsx";

export default function ShareModal({ file, onClose }) {
  useEscapeKey(onClose);
  const { token } = useAuth();
  const { notify } = useToast();

  const [permissions, setPermissions] = useState([]);
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(true);

  const [identifier, setIdentifier] = useState("");
  const [grantRole, setGrantRole] = useState("viewer");
  const [granting, setGranting] = useState(false);

  const [linkRole, setLinkRole] = useState("viewer");
  const [expiresAt, setExpiresAt] = useState("");
  const [maxAccessCount, setMaxAccessCount] = useState("");
  const [creatingLink, setCreatingLink] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [perms, shareLinks] = await Promise.all([
        apiRequest(`/files/${file.id}/permissions`, { token }),
        apiRequest(`/files/${file.id}/share-links`, { token }),
      ]);
      setPermissions(perms);
      setLinks(shareLinks);
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not load sharing settings");
    } finally {
      setLoading(false);
    }
  }, [file.id, token, notify]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleGrant(e) {
    e.preventDefault();
    if (!identifier.trim()) return;
    setGranting(true);
    try {
      await apiRequest(`/files/${file.id}/permissions`, {
        method: "POST",
        token,
        json: { identifier: identifier.trim(), role: grantRole },
      });
      setIdentifier("");
      notify("Access granted", "success");
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not grant access");
    } finally {
      setGranting(false);
    }
  }

  async function handleRevoke(permissionId) {
    try {
      await apiRequest(`/permissions/${permissionId}`, { method: "DELETE", token });
      notify("Access revoked", "success");
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not revoke access");
    }
  }

  async function handleCreateLink(e) {
    e.preventDefault();
    setCreatingLink(true);
    try {
      await apiRequest(`/files/${file.id}/share-link`, {
        method: "POST",
        token,
        json: {
          role: linkRole,
          expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
          max_access_count: maxAccessCount ? Number(maxAccessCount) : null,
        },
      });
      setExpiresAt("");
      setMaxAccessCount("");
      notify("Share link created", "success");
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not create share link");
    } finally {
      setCreatingLink(false);
    }
  }

  async function handleRevokeLink(linkId) {
    try {
      await apiRequest(`/files/${file.id}/share-links/${linkId}`, { method: "DELETE", token });
      notify("Share link revoked", "success");
      load();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not revoke share link");
    }
  }

  function copyLink(url) {
    navigator.clipboard?.writeText(url).then(
      () => notify("Link copied to clipboard", "success"),
      () => notify("Could not copy -- copy it manually")
    );
  }

  return (
    <div className="fixed inset-0 bg-slate-900/20 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 w-full max-w-lg p-6 space-y-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-800">Share "{file.filename}"</h2>
          <button onClick={onClose} className="p-1 -m-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100" aria-label="Close">
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>

        {loading ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : (
          <>
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase text-slate-400">People with access</h3>
              <form onSubmit={handleGrant} className="flex gap-2">
                <input
                  type="text"
                  placeholder="Email or username"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  className="flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <select
                  value={grantRole}
                  onChange={(e) => setGrantRole(e.target.value)}
                  className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                </select>
                <button
                  type="submit"
                  disabled={granting}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  Add
                </button>
              </form>
              {permissions.length ? (
                <ul className="divide-y divide-slate-100 border border-slate-200 rounded-lg">
                  {permissions.map((p) => (
                    <li key={p.id} className="flex items-center justify-between px-3 py-2 text-sm">
                      <div>
                        <p className="text-slate-800">{p.username}</p>
                        <p className="text-xs text-slate-400">
                          {p.user_email} &middot; {p.role}
                        </p>
                      </div>
                      <button onClick={() => handleRevoke(p.id)} className="text-xs text-red-500 hover:underline">
                        Revoke
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-400">Only you have access.</p>
              )}
            </section>

            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase text-slate-400">Share links</h3>
              <form onSubmit={handleCreateLink} className="grid grid-cols-2 gap-2 text-sm">
                <select
                  value={linkRole}
                  onChange={(e) => setLinkRole(e.target.value)}
                  className="rounded-lg border border-slate-200 px-2 py-1.5"
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                </select>
                <input
                  type="number"
                  min="1"
                  placeholder="Max uses (optional)"
                  value={maxAccessCount}
                  onChange={(e) => setMaxAccessCount(e.target.value)}
                  className="rounded-lg border border-slate-200 px-2 py-1.5"
                />
                <input
                  type="datetime-local"
                  value={expiresAt}
                  onChange={(e) => setExpiresAt(e.target.value)}
                  className="col-span-2 rounded-lg border border-slate-200 px-2 py-1.5"
                />
                <button
                  type="submit"
                  disabled={creatingLink}
                  className="col-span-2 rounded-lg bg-indigo-600 py-1.5 text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {creatingLink ? "Generating..." : "Generate link"}
                </button>
              </form>
              {links.length > 0 && (
                <ul className="divide-y divide-slate-100 border border-slate-200 rounded-lg">
                  {links.map((l) => (
                    <li key={l.id} className="px-3 py-2 text-sm space-y-1">
                      <div className="flex items-center justify-between gap-2">
                        <button
                          onClick={() => copyLink(l.url)}
                          className="truncate text-indigo-600 hover:underline text-left"
                          title={l.url}
                        >
                          {l.url}
                        </button>
                        <button onClick={() => handleRevokeLink(l.id)} className="text-xs text-red-500 hover:underline shrink-0">
                          Revoke
                        </button>
                      </div>
                      <p className="text-xs text-slate-400">
                        {l.role} &middot; used {l.access_count}
                        {l.max_access_count ? `/${l.max_access_count}` : ""} times
                        {l.expires_at ? ` · expires ${new Date(l.expires_at).toLocaleString()}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
