import { LogoIcon } from "./Icons.jsx";

/** Light, centered card layout for the signed-out pages (login, register, shared link). */
export default function AuthLayout({ title, subtitle, children }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-10 bg-gradient-to-br from-indigo-50 via-white to-sky-50">
      <div className="flex items-center gap-2.5 mb-8">
        <span className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-sky-400 text-white flex items-center justify-center shadow-sm">
          <LogoIcon className="w-6 h-6" />
        </span>
        <span className="text-xl font-semibold tracking-tight text-slate-900">CoreVault</span>
      </div>
      <div className="w-full max-w-sm rounded-2xl bg-white/90 backdrop-blur p-8 shadow-xl shadow-indigo-100/60 ring-1 ring-slate-200/70">
        {title && <h1 className="text-xl font-semibold text-slate-900">{title}</h1>}
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        <div className={title || subtitle ? "mt-6" : ""}>{children}</div>
      </div>
      <p className="mt-8 text-xs text-slate-400">Secure multi-user cloud storage</p>
    </div>
  );
}
