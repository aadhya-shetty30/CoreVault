import { ChevronRightIcon } from "./Icons.jsx";

export default function Breadcrumb({ items, onNavigate }) {
  return (
    <nav className="flex items-center gap-1 text-sm text-slate-500 flex-wrap" aria-label="Breadcrumb">
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1;
        return (
          <span key={item.id ?? "top"} className="flex items-center gap-1">
            {idx > 0 && <ChevronRightIcon className="w-3.5 h-3.5 text-slate-300" />}
            <button
              onClick={() => onNavigate(item.id)}
              aria-current={isLast ? "page" : undefined}
              className={`rounded px-1 py-0.5 transition-colors ${
                isLast ? "text-slate-700 font-medium" : "hover:text-indigo-600 hover:bg-indigo-50"
              }`}
            >
              {item.name}
            </button>
          </span>
        );
      })}
    </nav>
  );
}
