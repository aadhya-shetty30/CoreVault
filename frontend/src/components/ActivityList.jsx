import { useAuth } from "../context/AuthContext.jsx";

// One entry per action the backend logs (app/activity_log.py).
const ACTIONS = {
  uploaded: { icon: "⬆️", label: "Uploaded" },
  new_version: { icon: "🔁", label: "Uploaded a new version" },
  downloaded: { icon: "⬇️", label: "Downloaded" },
  link_downloaded: { icon: "🔗", label: "Downloaded through a public link" },
  version_restored: { icon: "⏪", label: "Restored an older version" },
  deleted: { icon: "🗑️", label: "Moved to the recycle bin" },
  restored: { icon: "♻️", label: "Restored from the recycle bin" },
  permission_granted: { icon: "👥", label: "Shared" },
  permission_revoked: { icon: "🚫", label: "Removed access" },
  link_created: { icon: "🔗", label: "Created a public link" },
  link_revoked: { icon: "✂️", label: "Revoked a public link" },
  kept: { icon: "📌", label: "Kept an unused file" },
};

function timeAgo(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}

/**
 * Renders file_activity rows (newest first, as the API returns them).
 * `showFilename` adds the file's name to each row -- for the dashboard's
 * cross-file feed; the per-file modal leaves it off.
 */
export default function ActivityList({ items, showFilename = false, onFileClick }) {
  const { user } = useAuth();

  function actorName(item) {
    if (item.action === "link_downloaded") return "Someone with the link";
    if (!item.actor_id) return "A deleted user";
    if (item.actor_id === user?.id) return "You";
    return item.actor_username;
  }

  return (
    <ol className="divide-y divide-slate-100">
      {items.map((item) => {
        const action = ACTIONS[item.action] ?? { icon: "•", label: item.action };
        return (
          <li key={item.id} className="flex gap-3 py-2 text-sm">
            <span className="w-5 text-center shrink-0" aria-hidden="true">
              {action.icon}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-slate-800">
                <span className="font-medium">{actorName(item)}</span> &middot; {action.label}
                {showFilename && (
                  <>
                    {" "}
                    <button onClick={() => onFileClick?.(item)} className="text-indigo-600 hover:underline break-all">
                      {item.filename}
                    </button>
                  </>
                )}
              </p>
              {item.detail && <p className="text-xs text-slate-500 break-words">{item.detail}</p>}
            </div>
            <time
              className="text-xs text-slate-400 whitespace-nowrap"
              dateTime={item.created_at}
              title={new Date(item.created_at).toLocaleString()}
            >
              {timeAgo(item.created_at)}
            </time>
          </li>
        );
      })}
    </ol>
  );
}
