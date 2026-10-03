import FolderTreeNode from "./FolderTreeNode.jsx";

/**
 * `refreshKey` is bumped by the parent whenever a folder is created,
 * moved, or deleted elsewhere in the UI. Changing it remounts the whole
 * tree (via the `key` prop), which is the simplest way to invalidate each
 * node's lazily-fetched, locally-cached children without hand-rolling a
 * shared cache-invalidation scheme.
 */
export default function FolderTree({ selectedId, onSelect, refreshKey }) {
  return (
    <div key={refreshKey}>
      <FolderTreeNode id={null} name="My files" depth={0} selectedId={selectedId} onSelect={onSelect} defaultExpanded />
    </div>
  );
}
