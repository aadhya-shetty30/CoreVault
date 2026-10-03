import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { formatBytes, folderUrl } from "../lib/format";
import FolderTree from "./FolderTree.jsx";
import TwoFactorSetupModal from "./TwoFactorSetupModal.jsx";
import {
  ChartIcon,
  CheckIcon,
  ChevronDownIcon,
  CloseIcon,
  HomeIcon,
  LogoIcon,
  LogoutIcon,
  MenuIcon,
  ShieldIcon,
  TrashIcon,
  UsersIcon,
} from "./Icons.jsx";

function NavItem({ to, icon: IconComponent, children, end }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
          isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`
      }
    >
      <IconComponent className="w-[18px] h-[18px]" />
      {children}
    </NavLink>
  );
}

function StorageMeter({ user }) {
  if (!user) return null;
  const pct = Math.min(100, (user.storage_used_bytes / user.storage_quota_bytes) * 100);
  return (
    <div className="rounded-xl bg-slate-50 ring-1 ring-slate-200/70 p-3">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-medium text-slate-700">Storage</span>
        <span className="text-slate-500">{pct < 0.1 && pct > 0 ? "<0.1" : pct.toFixed(1)}%</span>
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-slate-200 overflow-hidden">
        <div
          className={`h-full rounded-full ${pct >= 90 ? "bg-rose-500" : "bg-indigo-500"}`}
          style={{ width: `${Math.max(pct, pct > 0 ? 2 : 0)}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-slate-500">
        {formatBytes(user.storage_used_bytes)} of {formatBytes(user.storage_quota_bytes)} used
      </p>
    </div>
  );
}

function UserMenu({ user, onEnable2fa, onLogout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!user) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full py-1 pl-1 pr-2 hover:bg-slate-100 transition-colors"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-400 to-sky-400 text-white text-sm font-semibold flex items-center justify-center">
          {user.username.slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden sm:block text-sm font-medium text-slate-700 max-w-[10rem] truncate">{user.username}</span>
        <ChevronDownIcon className="w-4 h-4 text-slate-400" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-64 rounded-xl bg-white shadow-lg ring-1 ring-slate-200 py-2 z-40"
        >
          <div className="px-4 py-2 border-b border-slate-100">
            <p className="text-sm font-medium text-slate-800 truncate">{user.username}</p>
            <p className="text-xs text-slate-500 truncate">{user.email}</p>
          </div>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onEnable2fa();
            }}
            className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            <ShieldIcon className="w-4 h-4 text-slate-400" />
            <span className="flex-1 text-left">Two-factor authentication</span>
            {user.otp_enabled ? (
              <span className="text-xs font-medium text-emerald-600 bg-emerald-50 rounded-full px-2 py-0.5">On</span>
            ) : (
              <span className="text-xs font-medium text-slate-500 bg-slate-100 rounded-full px-2 py-0.5">Off</span>
            )}
          </button>
          <button
            role="menuitem"
            onClick={onLogout}
            className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            <LogoutIcon className="w-4 h-4 text-slate-400" />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Shared chrome for every signed-in page: sidebar (navigation, folder tree,
 * storage meter) + top bar (account menu). On small screens the sidebar
 * slides in from a menu button.
 */
export default function AppShell({ children, selectedFolderId = null, treeRefreshKey = 0 }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [show2fa, setShow2fa] = useState(false);

  function goToFolder(id) {
    setSidebarOpen(false);
    navigate(folderUrl(id));
  }

  const sidebar = (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2.5 px-5 h-16 shrink-0">
        <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-sky-400 text-white flex items-center justify-center shadow-sm">
          <LogoIcon className="w-5 h-5" />
        </span>
        <span className="text-lg font-semibold tracking-tight text-slate-900">CoreVault</span>
      </div>

      <nav className="px-3 space-y-1">
        <NavItem to="/app" icon={HomeIcon}>
          My files
        </NavItem>
        <NavItem to="/dashboard" icon={ChartIcon}>
          Dashboard
        </NavItem>
        <NavItem to="/recycle-bin" icon={TrashIcon}>
          Recycle bin
        </NavItem>
        {user?.is_admin && (
          <NavItem to="/admin" icon={UsersIcon}>
            Admin
          </NavItem>
        )}
      </nav>

      <div className="mt-6 px-5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Folders</div>
      <div className="flex-1 min-h-0 overflow-y-auto px-2 mt-1">
        <FolderTree refreshKey={treeRefreshKey} selectedId={selectedFolderId} onSelect={goToFolder} />
      </div>

      <div className="p-4 shrink-0">
        <StorageMeter user={user} />
      </div>
    </div>
  );

  return (
    <div className="h-screen flex bg-[#f7f8fc]">
      <aside className="hidden md:block w-64 shrink-0 bg-white border-r border-slate-200/80">{sidebar}</aside>

      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-slate-900/20 backdrop-blur-[2px]" onClick={() => setSidebarOpen(false)} />
          <aside className="relative w-72 max-w-[85%] bg-white shadow-xl">
            <button
              onClick={() => setSidebarOpen(false)}
              className="absolute top-4 right-3 p-1.5 rounded-lg text-slate-400 hover:bg-slate-100"
              aria-label="Close menu"
            >
              <CloseIcon className="w-5 h-5" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-16 shrink-0 flex items-center justify-between gap-4 px-4 sm:px-6 bg-white/70 backdrop-blur border-b border-slate-200/80">
          <button
            onClick={() => setSidebarOpen(true)}
            className="md:hidden p-2 -ml-2 rounded-lg text-slate-500 hover:bg-slate-100"
            aria-label="Open menu"
          >
            <MenuIcon className="w-5 h-5" />
          </button>
          <div className="flex-1" />
          {user?.otp_enabled && (
            <span className="hidden sm:flex items-center gap-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 ring-1 ring-emerald-100 rounded-full px-2.5 py-1">
              <CheckIcon className="w-3.5 h-3.5" /> 2FA on
            </span>
          )}
          <UserMenu
            user={user}
            onEnable2fa={() => setShow2fa(true)}
            onLogout={() => {
              logout();
              navigate("/login");
            }}
          />
        </header>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>

      {show2fa && !user?.otp_enabled && <TwoFactorSetupModal onClose={() => setShow2fa(false)} />}
      {show2fa && user?.otp_enabled && (
        <div className="fixed inset-0 bg-slate-900/20 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 w-full max-w-sm p-6 space-y-4 text-center">
            <span className="mx-auto w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center">
              <ShieldIcon className="w-6 h-6" />
            </span>
            <p className="text-slate-700">Two-factor authentication is already enabled on your account.</p>
            <button
              onClick={() => setShow2fa(false)}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
