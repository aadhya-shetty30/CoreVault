import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import DonutChart from "../components/DonutChart.jsx";
import StaleFilesModal from "../components/StaleFilesModal.jsx";
import ForecastChart from "../components/ForecastChart.jsx";
import ActivityList from "../components/ActivityList.jsx";
import FileActivityModal from "../components/FileActivityModal.jsx";
import AppShell from "../components/AppShell.jsx";
import { folderUrl } from "../lib/format";

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

// Fixed category -> color mapping (and draw order), so a category keeps its
// color no matter which others are present or how they rank. The six hues
// are a colorblind-validated categorical set; "Other" is deliberately gray.
const CATEGORIES = [
  { key: "Images", color: "#2a78d6" },
  { key: "Videos", color: "#eb6834" },
  { key: "Audio", color: "#1baf7a" },
  { key: "Documents", color: "#eda100" },
  { key: "Archives", color: "#e87ba4" },
  { key: "Code", color: "#008300" },
  { key: "Other", color: "#898781" },
];
const CATEGORY_COLOR = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.color]));

function formatDuration(days) {
  if (days < 1) return "now";
  if (days < 60) return `${days} day${days === 1 ? "" : "s"}`;
  if (days < 730) return `${Math.round(days / 30)} months`;
  return `${(days / 365).toFixed(1)} years`;
}

function forecastHeadline(f) {
  if (f.status === "insufficient_data") {
    return "Not enough history yet -- check back after a few days of uploads.";
  }
  if (f.status === "flat") {
    return `Your storage hasn't grown in the last ${f.window_days} days, so you're not on track to run out.`;
  }
  const rate = `+${formatBytes(f.growth_bytes_per_day)}/day`;
  if (f.days_until_full === null) return `Growing ${rate} -- at that rate you won't fill your quota for over 100 years.`;
  if (f.days_until_full === 0) return "You've reached your storage quota.";
  return `At your current rate (${rate}), you'll run out of space in about ${formatDuration(f.days_until_full)} -- around ${new Date(
    `${f.projected_full_date}T00:00:00Z`
  ).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" })}.`;
}

function StatTile({ label, value, hint, children }) {
  return (
    <div className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm p-4">
      <p className="text-xs font-semibold uppercase text-slate-400">{label}</p>
      <p className="text-2xl font-semibold text-slate-900 mt-1">{value}</p>
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
      {children}
    </div>
  );
}

export default function DashboardPage() {
  const { token } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [hoveredCategory, setHoveredCategory] = useState(null);
  const [staleFiles, setStaleFiles] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [activity, setActivity] = useState(null);
  const [activityFile, setActivityFile] = useState(null);

  const load = useCallback(async () => {
    try {
      const [storage, forecastData, recent] = await Promise.all([
        apiRequest("/analytics/storage", { token }),
        apiRequest("/analytics/forecast", { token }),
        apiRequest("/analytics/activity?limit=15", { token }),
      ]);
      setStats(storage);
      setForecast(forecastData);
      setActivity(recent);
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not load storage analytics");
    }
  }, [token, notify]);

  useEffect(() => {
    load();
  }, [load]);

  async function openStaleReview() {
    try {
      const files = await apiRequest("/analytics/stale-files", { token });
      if (files.length === 0) notify("Nothing to review -- every file has been used recently", "success");
      else setStaleFiles(files);
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Could not load unused files");
    }
  }

  const usedPct = stats ? Math.min(100, (stats.storage_used_bytes / stats.storage_quota_bytes) * 100) : 0;
  const categoryValues = Object.fromEntries((stats?.by_category ?? []).map((c) => [c.category, c]));
  const segments = CATEGORIES.map((c) => ({
    key: c.key,
    label: c.key,
    color: c.color,
    value: categoryValues[c.key]?.total_bytes ?? 0,
  }));
  const maxFileSize = stats?.largest_files[0]?.size_bytes || 1;

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-500 mt-1">What's using your space, how fast it's growing, and what happened recently.</p>
        </div>
        {stats === null ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-28 rounded-xl bg-white ring-1 ring-slate-200/60 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <StatTile
                label="Storage used"
                value={formatBytes(stats.storage_used_bytes)}
                hint={`of ${formatBytes(stats.storage_quota_bytes)} (${usedPct.toFixed(1)}%)`}
              >
                <div className="h-1.5 bg-slate-200 rounded mt-3 overflow-hidden" role="meter" aria-valuenow={usedPct} aria-valuemin={0} aria-valuemax={100}>
                  <div
                    className={`h-full rounded ${usedPct >= 90 ? "bg-red-600" : "bg-indigo-600"}`}
                    style={{ width: `${usedPct}%` }}
                  />
                </div>
              </StatTile>
              <StatTile label="Files" value={stats.file_count} hint={`${formatBytes(stats.active_bytes)} in current versions`} />
              <StatTile
                label="Old versions & recycle bin"
                value={formatBytes(stats.old_versions_bytes + stats.recycle_bin_bytes)}
                hint={`${formatBytes(stats.old_versions_bytes)} versions · ${formatBytes(stats.recycle_bin_bytes)} in ${stats.recycle_bin_count} recycled`}
              />
              <StatTile
                label="Saved by deduplication"
                value={formatBytes(stats.dedup_saved_bytes)}
                hint="Identical content is only stored and charged once"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <section className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm p-5">
                <h2 className="font-semibold text-slate-800">Space by file type</h2>
                <p className="text-xs text-slate-500 mb-4">Current versions of your files, by extension</p>
                {stats.file_count === 0 ? (
                  <p className="text-sm text-slate-400">Upload some files to see a breakdown.</p>
                ) : (
                  <div className="flex flex-col sm:flex-row items-center gap-6">
                    <DonutChart
                      segments={segments}
                      centerLabel="Total"
                      centerValue={formatBytes(stats.active_bytes)}
                      formatValue={formatBytes}
                      hovered={hoveredCategory}
                      onHover={setHoveredCategory}
                    />
                    <table className="text-sm flex-1 w-full">
                      <thead>
                        <tr className="text-xs text-slate-400 text-left">
                          <th className="font-normal pb-1">Type</th>
                          <th className="font-normal pb-1 text-right">Files</th>
                          <th className="font-normal pb-1 text-right">Size</th>
                          <th className="font-normal pb-1 text-right">Share</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stats.by_category.map((c) => (
                          <tr
                            key={c.category}
                            className={hoveredCategory === c.category ? "bg-slate-100" : ""}
                            onMouseEnter={() => setHoveredCategory(c.category)}
                            onMouseLeave={() => setHoveredCategory(null)}
                          >
                            <td className="py-1 pr-2">
                              <span
                                className="inline-block w-2.5 h-2.5 rounded-sm mr-2 align-middle"
                                style={{ backgroundColor: CATEGORY_COLOR[c.category] }}
                              />
                              <span className="text-slate-700">{c.category}</span>
                            </td>
                            <td className="py-1 text-right text-slate-500 tabular-nums">{c.file_count}</td>
                            <td className="py-1 text-right text-slate-700 tabular-nums">{formatBytes(c.total_bytes)}</td>
                            <td className="py-1 text-right text-slate-500 tabular-nums">
                              {stats.active_bytes ? ((c.total_bytes / stats.active_bytes) * 100).toFixed(1) : "0.0"}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm p-5">
                <h2 className="font-semibold text-slate-800">Largest files</h2>
                <p className="text-xs text-slate-500 mb-4">The files taking up the most space</p>
                {stats.largest_files.length === 0 ? (
                  <p className="text-sm text-slate-400">No files yet.</p>
                ) : (
                  <ol className="space-y-2.5">
                    {stats.largest_files.map((f) => (
                      <li key={f.id} title={`${f.folder_path} / ${f.filename} — ${formatBytes(f.size_bytes)}`}>
                        <div className="flex justify-between gap-3 text-sm">
                          <button
                            onClick={() => navigate(folderUrl(f.folder_id))}
                            className="truncate text-left text-slate-700 hover:underline"
                          >
                            {f.filename}
                          </button>
                          <span className="text-slate-700 tabular-nums whitespace-nowrap">{formatBytes(f.size_bytes)}</span>
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <div className="flex-1 h-2 bg-slate-100 rounded-sm overflow-hidden">
                            <div
                              className="h-full rounded-r"
                              style={{
                                width: `${Math.max(1, (f.size_bytes / maxFileSize) * 100)}%`,
                                backgroundColor: CATEGORY_COLOR[f.category],
                              }}
                            />
                          </div>
                          <span className="text-xs text-slate-400 w-40 truncate">{f.folder_path}</span>
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <section className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm p-5 lg:col-span-2">
                <h2 className="font-semibold text-slate-800">Storage forecast</h2>
                <p className="text-sm text-slate-600 mt-1 mb-4">{forecastHeadline(forecast)}</p>
                {forecast.history.length < 3 ? (
                  // A day or two of history is a dot, not a line -- explain instead of drawing an empty chart.
                  <div className="h-48 rounded-md border border-dashed flex flex-col items-center justify-center text-center px-6">
                    <p className="text-sm text-slate-600">
                      Your account is {forecast.history.length === 1 ? "less than a day" : "2 days"} old, currently using{" "}
                      <span className="font-semibold">{formatBytes(forecast.storage_used_bytes)}</span> of{" "}
                      {formatBytes(forecast.storage_quota_bytes)}.
                    </p>
                    <p className="text-xs text-slate-400 mt-1">The usage chart and prediction appear after 3 days of history.</p>
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
                <p className="text-xs text-slate-400 mt-2">
                  Trend fitted to the last {forecast.window_days} days of uploads. Old versions count; duplicates don't.
                </p>
              </section>

              <section className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm p-5">
                <h2 className="font-semibold text-slate-800">Recent activity</h2>
                <p className="text-xs text-slate-500 mb-2">On files you own, by anyone</p>
                {activity.length === 0 ? (
                  <p className="text-sm text-slate-400">Nothing yet.</p>
                ) : (
                  <div className="max-h-80 overflow-y-auto">
                    <ActivityList
                      items={activity}
                      showFilename
                      onFileClick={(item) => setActivityFile({ id: item.file_id, filename: item.filename })}
                    />
                  </div>
                )}
              </section>
            </div>

            <section className="bg-white rounded-xl ring-1 ring-slate-200/80 shadow-sm p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="font-semibold text-slate-800">Unused files</h2>
                <p className="text-sm text-slate-500">
                  {stats.stale_file_count === 0
                    ? `Every file has been opened or changed in the last ${stats.stale_after_days} days.`
                    : `${stats.stale_file_count} file${stats.stale_file_count === 1 ? " hasn't" : "s haven't"} been opened or changed in over ${stats.stale_after_days} days.`}
                </p>
              </div>
              <button
                onClick={openStaleReview}
                disabled={stats.stale_file_count === 0}
                className="rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
              >
                Review unused files
              </button>
            </section>
          </div>
        )}
      </div>

      {staleFiles && <StaleFilesModal files={staleFiles} onClose={() => setStaleFiles(null)} onChanged={load} />}
      {activityFile && <FileActivityModal file={activityFile} onClose={() => setActivityFile(null)} />}
    </AppShell>
  );
}
