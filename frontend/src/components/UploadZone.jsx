import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { UploadIcon } from "./Icons.jsx";

/**
 * Drag-and-drop strip (also clickable). The parent can open the file picker
 * itself -- e.g. from an "Upload" button -- through the ref's `browse()`.
 */
const UploadZone = forwardRef(function UploadZone({ onUpload, uploading }, ref) {
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);

  useImperativeHandle(ref, () => ({ browse: () => inputRef.current?.click() }));

  function handleFiles(fileList) {
    Array.from(fileList).forEach((file) => onUpload(file));
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFiles(e.dataTransfer.files);
      }}
      className={`group flex items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-5 cursor-pointer transition-colors ${
        dragOver
          ? "border-indigo-400 bg-indigo-50/80"
          : "border-slate-200 bg-white/60 hover:border-indigo-300 hover:bg-indigo-50/40"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files) handleFiles(e.target.files);
          e.target.value = ""; // allow picking the same file again
        }}
      />
      <span
        className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
          dragOver ? "bg-indigo-100 text-indigo-600" : "bg-slate-100 text-slate-500 group-hover:bg-indigo-100 group-hover:text-indigo-600"
        }`}
      >
        <UploadIcon className="w-5 h-5" />
      </span>
      <p className="text-sm text-slate-500">
        {uploading ? (
          "Uploading..."
        ) : (
          <>
            <span className="font-medium text-slate-700">Drop files here</span> or{" "}
            <span className="font-medium text-indigo-600">browse</span>
          </>
        )}
      </p>
    </div>
  );
});

export default UploadZone;
