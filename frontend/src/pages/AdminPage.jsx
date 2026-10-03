import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { formatBytes, formatDate, formatDuration, formatLongDate } from "../lib/format";
import useEscapeKey from "../lib/useEscapeKey";
import AppShell from "../components/AppShell.jsx";
import ForecastChart from "../components/ForecastChart.jsx";
import { CloseIcon, ShieldIcon } from "../components/Icons.jsx";

// A user "needs attention" when they're close to full now, or will be soon.
const CRITICAL_DAYS = 30;
const WARNING_DAYS = 90;

function usagePct(u) {
  return u.storage_quota_bytes ? (u.storage_used_bytes / u.storage_quota_bytes) * 100 : 0;
}

function urgency(u) {
  const pct = usagePct(u);
  const days = u.days_until_full;
  if (pct >= 90 || (days !== null && days <= CRITICAL_DAYS)) return "critical";
  if (pct >= 75 || (days !== null && days <= WARNING_DAYS)) return "warning";
  return "ok";
}

const URGENCY_RANK = { critical: 0, warning: 1, ok: 2 };
const URGENCY_BADGE = {
  critical: { label: "Critical", className: "bg-rose-50 text-rose-700 ring-rose-100" },
  warning: { label: "Running low", className: "bg-amber-50 text-amber-700 ring-amber-100" },
  ok: { label: "OK", className: "bg-emerald-50 text-emerald-700 ring-emerald-100" },
};

function forecastText(u) {
  if (u.forecast_status === "insufficient_data") return { main: "New account", sub: "Not enough history yet" };
  if (u.forecast_status === "flat") return { main: "Not growing", sub: "No new uploads lately" };
  const rate = `+${formatBytes(u.growth_bytes_per_day)}/day`;
  if (u.days_until_full === null) return { main: "100+ years", sub: rate };
  if (u.days_until_full === 0) return { main: "Full now", sub: rate };
  return { main: `Full in ~${formatDuration(u.days_until_full)}`, sub: `${formatLongDate(u.projected_full_date)} · ${rate}` };
}

function renewalMailto(u) {
  const f = forecastText(u);
  const subject = "Your CoreVault storage";
  const body = [
    `Hi ${u.username},`,
    "",
    `You're currently using ${formatBytes(u.storage_used_bytes)} of your ${formatBytes(u.storage_quota_bytes)} CoreVault storage (${usagePct(u).toFixed(0)}%), with ${formatBytes(u.storage_left_bytes)} left.`,
    u.days_until_full !== null && u.forecast_status === "growing"
      ? `At your current rate, your storage will be full around ${formatLongDate(u.projected_full_date)}.`
      : `Storage outlook: ${f.main.toLowerCase()}.`,
    "",
    "Reply to this email if you'd like to renew or upgrade your storage plan.",
    "",
    "Thanks,",
    "CoreVault",
  ].join("\n");
  return `mailto:${u.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function UserForecastModal({ user, onClose }) {
  const { token } = useAuth();
  const [forecast, setForecast] = useState(null);
  const [error, setError] = useState(null);
  useEscapeKey(onClose);

  useEffect(() => {
    apiRequest(`/admin/users/${user.id}/forecast`, { token })
      .then(setForecast)
      .catch((err) => setError(err instanceof ApiError ? String(err.detail) : "Could not load forecast"));
  }, [user.id, token]);

  const f = forecastText(user);
  return (
    <div className="fixed inset-0 bg-slate-900/20 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 w-full max-w-2xl p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-800 truncate">{user.username}</h2>
            <p className="text-sm text-slate-500 truncate">{user.email}</p>
          </div>
          <button onClick={onClose} className="p-1 -m-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100" aria-label="Close">
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {[
            ["Used", formatBytes(user.storage_used_bytes)],
            ["Left", formatBytes(user.storage_left_bytes)],
            ["Forecast", f.main],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl bg-slate-50 ring-1 ring-slate-200/70 px-3 py-2.5">
              <p className="text-xs text-slate-500">{label}</p>
              <p className="text-sm font-semibold text-slate-900 mt-0.5">{value}</p>
            </div>
          ))}
        </div>

        {error ? (
          <p className="text-sm text-rose-600">{error}</p>
        ) : forecast === null ? (
          <div className="h-56 rounded-xl bg-slate-50 animate-pulse" />
        ) : forecast.history.length < 3 ? (
          <div className="h-48 rounded-xl border border-dashed border-slate-200 flex items-center justify-center text-sm text-slate-500 px-6 text-center">
            This account is too new for a usage chart -- it appears after 3 days of history.
          </div>
        ) : (
          <ForecastChart
            forecast={forecast}
            formatValue={formatBytes}
            horizonDays={
              forecast.days_until_full !== null && forecast.days_until_full < forecast.window_days
                ? Math.max(14, forecast.days_until_full + 7)
                : forecast.window_days
            }
          />
        )}
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-400">Storage totals only -- file names and contents are never shown to admins.</p>
          <a
            href={renewalMailto(user)}
            className="shrink-0 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
          >
            Email about renewal
          </a>
        </div>
      </div>
    </div>
  );
}

function StatTile({ label, value, hint, tone = "default" }) {
  const toneClass = tone === "critical" ? "text-rose-600" : tone === "warning" ? "text-amber-600" : "text-slate-900";
  return (
    <div className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <p className={`text-2xl font-semibold mt-1 ${toneClass}`}>{value}</p>
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </div>
  );
}

export default function AdminPage() {
  const { token, user: me } = useAuth();
  const { notify } = useToast();
  const [data, setData] = useState(null);
  const [forbidden, setForbidden] = useState(false);
  const [query, setQuery] = useState("");
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await apiRequest("/admin/users", { token }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setForbidden(true);
      else notify(err instanceof ApiError ? String(err.detail) : "Could not load users");
    }
  }, [token, notify]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    return data.users
      .map((u) => ({ ...u, urgency: urgency(u), pct: usagePct(u) }))
      .filter((u) => !q || u.username.toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
      .filter((u) => !onlyAttention || u.urgency !== "ok")
      .sort(
        (a, b) =>
          URGENCY_RANK[a.urgency] - URGENCY_RANK[b.urgency] ||
          (a.days_until_full ?? Infinity) - (b.days_until_full ?? Infinity) ||
          b.pct - a.pct
      );
  }, [data, query, onlyAttention]);

  const counts = useMemo(() => {
    const c = { critical: 0, warning: 0 };
    (data?.users ?? []).forEach((u) => {
      const level = urgency(u);
      if (level in c) c[level] += 1;
    });
    return c;
  }, [data]);

  if (forbidden || (me && !me.is_admin)) {
    return (
      <AppShell>
        <div className="max-w-xl mx-auto px-4 py-16 text-center">
          <span className="mx-auto w-14 h-14 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center">
            <ShieldIcon className="w-7 h-7" />
          </span>
          <h1 className="mt-4 font-semibold text-slate-800">Admins only</h1>
          <p className="mt-1 text-sm text-slate-500">Your account doesn't have access to the admin overview.</p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Admin</h1>
          <p className="text-sm text-slate-500 mt-1">
            Storage usage and forecasts for every account -- spot who's running out before they do. File names and contents are
            never shown here.
          </p>
        </div>

        {data === null ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-24 rounded-xl bg-white ring-1 ring-slate-200/60 animate-pulse" />
            ))}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <StatTile label="Users" value={data.user_count} />
              <StatTile
                label="Storage used"
                value={formatBytes(data.total_used_bytes)}
                hint={`of ${formatBytes(data.total_quota_bytes)} allocated`}
              />
              <StatTile
                label="Critical"
                value={counts.critical}
                hint={`≥90% full or full within ${CRITICAL_DAYS} days`}
                tone={counts.critical ? "critical" : "default"}
              />
              <StatTile
                label="Running low"
                value={counts.warning}
                hint={`≥75% full or full within ${WARNING_DAYS} days`}
                tone={counts.warning ? "warning" : "default"}
              />
            </div>

            <section className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm overflow-hidden">
              <div className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between px-4 py-3 border-b border-slate-100">
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by name or email"
                  className="w-full sm:w-72 rounded-lg bg-white px-3 py-2 text-sm ring-1 ring-slate-200 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <label className="flex items-center gap-2 text-sm text-slate-600 select-none">
                  <input type="checkbox" checked={onlyAttention} onChange={(e) => setOnlyAttention(e.target.checked)} />
                  Only show users who need attention
                </label>
              </div>

              <div className="hidden lg:grid grid-cols-[minmax(0,1.4fr)_minmax(0,1.2fr)_7rem_minmax(0,1.3fr)_6.5rem_5rem] gap-4 px-4 py-2.5 border-b border-slate-100 text-xs font-medium text-slate-400">
                <span>User</span>
                <span>Storage used</span>
                <span className="text-right">Left</span>
                <span>Forecast</span>
                <span>Status</span>
                <span className="sr-only">Actions</span>
              </div>

              {rows.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-slate-400">No users match.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {rows.map((u) => {
                    const f = forecastText(u);
                    const badge = URGENCY_BADGE[u.urgency];
                    return (
                      <li
                        key={u.id}
                        onClick={() => setSelected(u)}
                        className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1.2fr)_7rem_minmax(0,1.3fr)_6.5rem_5rem] gap-x-4 gap-y-2 items-center px-4 py-3 cursor-pointer hover:bg-slate-50/70 transition-colors"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <span className="w-8 h-8 shrink-0 rounded-full bg-gradient-to-br from-indigo-300 to-sky-300 text-white text-sm font-semibold flex items-center justify-center">
                            {u.username.slice(0, 1).toUpperCase()}
                          </span>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-slate-800 truncate">
                              {u.username}
                              {u.is_admin && (
                                <span className="ml-2 align-middle text-[10px] font-semibold uppercase tracking-wide text-indigo-600 bg-indigo-50 rounded px-1.5 py-0.5">
                                  Admin
                                </span>
                              )}
                            </p>
                            <p className="text-xs text-slate-400 truncate">
                              {u.email} &middot; joined {formatDate(u.created_at)}
                            </p>
                          </div>
                        </div>
                        <div>
                          <div className="flex justify-between text-xs text-slate-500 mb-1">
                            <span className="tabular-nums">
                              {formatBytes(u.storage_used_bytes)} / {formatBytes(u.storage_quota_bytes)}
                            </span>
                            <span className="tabular-nums">{u.pct < 0.1 && u.pct > 0 ? "<0.1" : u.pct.toFixed(1)}%</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                u.urgency === "critical" ? "bg-rose-500" : u.urgency === "warning" ? "bg-amber-400" : "bg-indigo-500"
                              }`}
                              style={{ width: `${Math.min(100, Math.max(u.pct, u.pct > 0 ? 1.5 : 0))}%` }}
                            />
                          </div>
                        </div>
                        <span className="text-sm text-slate-700 lg:text-right tabular-nums">
                          <span className="lg:hidden text-xs text-slate-400">Left: </span>
                          {formatBytes(u.storage_left_bytes)}
                        </span>
                        <div className="min-w-0">
                          <p className="text-sm text-slate-700">{f.main}</p>
                          <p className="text-xs text-slate-400 truncate">{f.sub}</p>
                        </div>
                        <span>
                          <span className={`inline-block text-xs font-medium rounded-full px-2.5 py-1 ring-1 ring-inset ${badge.className}`}>
                            {badge.label}
                          </span>
                        </span>
                        <a
                          href={renewalMailto(u)}
                          onClick={(e) => e.stopPropagation()}
                          className="text-sm font-medium text-indigo-600 hover:text-indigo-700 lg:text-right"
                        >
                          Email
                        </a>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </div>

      {selected && <UserForecastModal user={selected} onClose={() => setSelected(null)} />}
    </AppShell>
  );
}
