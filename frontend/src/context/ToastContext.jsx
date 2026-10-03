import { createContext, useCallback, useContext, useState } from "react";
import { AlertIcon, CheckIcon, CloseIcon } from "../components/Icons.jsx";

const ToastContext = createContext(null);
let nextId = 1;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback(
    (message, type = "error") => {
      const id = nextId++;
      setToasts((prev) => [...prev, { id, message, type }]);
      setTimeout(() => dismiss(id), 5000);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div className="fixed bottom-4 right-4 left-4 sm:left-auto z-[60] flex flex-col items-end gap-2" aria-live="polite">
        {toasts.map((t) => {
          const isError = t.type === "error";
          return (
            <div
              key={t.id}
              role={isError ? "alert" : "status"}
              className="flex items-start gap-3 w-full sm:w-96 rounded-xl bg-white px-4 py-3 shadow-lg ring-1 ring-slate-200 text-sm"
            >
              <span
                className={`mt-0.5 w-5 h-5 shrink-0 rounded-full flex items-center justify-center ${
                  isError ? "bg-rose-50 text-rose-600" : "bg-emerald-50 text-emerald-600"
                }`}
              >
                {isError ? <AlertIcon className="w-4 h-4" /> : <CheckIcon className="w-3.5 h-3.5" />}
              </span>
              <p className="flex-1 text-slate-700 break-words">{t.message}</p>
              <button onClick={() => dismiss(t.id)} className="text-slate-300 hover:text-slate-500" aria-label="Dismiss">
                <CloseIcon className="w-4 h-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
