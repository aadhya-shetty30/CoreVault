import { useEffect, useState } from "react";
import { apiRequest } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { ChevronRightIcon, FolderIcon, HomeIcon } from "./Icons.jsx";

export default function FolderTreeNode({ id, name, depth, selectedId, onSelect, defaultExpanded = false }) {
  const { token } = useAuth();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [children, setChildren] = useState(null); // null = not loaded yet
  const [loading, setLoading] = useState(false);

  async function loadChildren() {
    setLoading(true);
    try {
      const path = id ? `/folders/${id}` : "/folders/root";
      const detail = await apiRequest(path, { token });
      setChildren(detail.folders);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (defaultExpanded && token) loadChildren().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggleExpand(e) {
    e.stopPropagation();
    const next = !expanded;
    setExpanded(next);
    if (next && children === null) await loadChildren().catch(() => {});
  }

  // selectedId is null for the top level ("My files").
  const isSelected = (selectedId ?? null) === (id ?? null);
  const NodeIcon = id ? FolderIcon : HomeIcon;
  const hasNoChildren = children !== null && children.length === 0;

  return (
    <div>
      <div
        onClick={() => onSelect(id)}
        className={`group flex items-center gap-1.5 pr-2 py-1.5 rounded-lg cursor-pointer text-sm transition-colors ${
          isSelected ? "bg-indigo-50 text-indigo-700 font-medium" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`}
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        <button
          onClick={toggleExpand}
          className={`w-5 h-5 shrink-0 rounded flex items-center justify-center text-slate-400 hover:bg-slate-200/70 ${
            hasNoChildren ? "invisible" : ""
          }`}
          aria-label={expanded ? `Collapse ${name}` : `Expand ${name}`}
        >
          <ChevronRightIcon className={`w-3.5 h-3.5 transition-transform ${expanded ? "rotate-90" : ""}`} />
        </button>
        <NodeIcon className={`w-4 h-4 shrink-0 ${isSelected ? "text-indigo-500" : "text-slate-400"}`} />
        <span className="truncate">{name}</span>
      </div>
      {expanded && (
        <div>
          {loading && (
            <div className="text-xs text-slate-400 py-1" style={{ paddingLeft: `${(depth + 1) * 14 + 32}px` }}>
              Loading...
            </div>
          )}
          {children?.map((child) => (
            <FolderTreeNode
              key={child.id}
              id={child.id}
              name={child.name}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}
