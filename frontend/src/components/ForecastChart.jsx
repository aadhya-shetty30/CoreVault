import { useRef, useState } from "react";

const W = 640;
const H = 240;
const PAD = { top: 16, right: 16, bottom: 28, left: 64 };
const LINE = "#2a78d6";
const QUOTA = "#d03b3b";
const GRID = "#e2e8f0";
const MUTED = "#94a3b8";

function addDays(isoDate, n) {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

// Tick step that reads cleanly in the unit formatBytes will display
// (B/KB/MB/GB): 1, 2, 2.5 or 5 x a power of ten of that unit.
function niceStep(maxValue, targetTicks = 4) {
  const unit = Math.pow(1024, Math.max(0, Math.floor(Math.log(Math.max(maxValue, 1)) / Math.log(1024))));
  const raw = maxValue / unit / targetTicks;
  const pow10 = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow10).find((c) => c >= raw);
  return step * unit;
}

function shortDate(isoDate) {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

/**
 * Phase 3 storage forecast: past daily usage as a solid line, the fitted
 * trend projected forward `horizonDays` as a dashed line in the same color
 * (capped at the quota, since usage can't exceed it), and the quota as a
 * labeled reference line whenever it falls within view. One y-axis
 * (bytes). Hovering anywhere shows a crosshair and that day's value.
 */
export default function ForecastChart({ forecast, horizonDays, formatValue }) {
  const svgRef = useRef(null);
  const [hoverIndex, setHoverIndex] = useState(null);

  const history = forecast.history.map((p) => ({ date: p.date, value: p.used_bytes, projected: false }));
  const today = history[history.length - 1];
  const rate = forecast.status === "growing" ? forecast.growth_bytes_per_day : 0;
  const quota = forecast.storage_quota_bytes;
  const projection =
    forecast.status === "insufficient_data"
      ? []
      : Array.from({ length: horizonDays }, (_, i) => ({
          date: addDays(today.date, i + 1),
          value: Math.min(quota, today.value + rate * (i + 1)),
          projected: true,
        }));
  const points = [...history, ...projection];

  const peak = Math.max(1, ...points.map((p) => p.value));
  // Pull the quota into view when it's reasonably close, so "when will I
  // hit it" is visible; otherwise it would flatten the whole chart.
  const step = niceStep((quota <= peak * 1.5 ? Math.max(peak, quota) : peak) * 1.05);
  const yMax = Math.ceil(((quota <= peak * 1.5 ? Math.max(peak, quota) : peak) * 1.05) / step) * step;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (i) => PAD.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (v) => PAD.top + plotH - (v / yMax) * plotH;

  const pathFor = (pts, offset) => pts.map((p, i) => `${i ? "L" : "M"}${x(i + offset).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const historyPath = pathFor(history, 0);
  const projectionPath = projection.length ? pathFor([today, ...projection], history.length - 1) : "";
  const ticks = Array.from({ length: Math.round(yMax / step) + 1 }, (_, i) => i * step);
  const todayX = x(history.length - 1);
  const showQuota = quota <= yMax;

  function handleMove(e) {
    const rect = svgRef.current.getBoundingClientRect();
    const svgX = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((svgX - PAD.left) / plotW) * (points.length - 1));
    setHoverIndex(Math.max(0, Math.min(points.length - 1, i)));
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;
  const tooltipLeftPct = hovered ? (x(hoverIndex) / W) * 100 : 0;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        role="img"
        aria-label="Storage used over time, with projected growth"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth="1" />
            <text x={PAD.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle" fontSize="11" fill={MUTED}>
              {formatValue(t)}
            </text>
          </g>
        ))}

        {[0, history.length - 1, points.length - 1]
          .filter((i, idx, arr) => arr.indexOf(i) === idx)
          .map((i) => (
            <text
              key={i}
              x={x(i)}
              y={H - 8}
              textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
              fontSize="11"
              fill={MUTED}
            >
              {i === history.length - 1 ? "Today" : shortDate(points[i].date)}
            </text>
          ))}

        {projection.length > 0 && (
          <line x1={todayX} x2={todayX} y1={PAD.top} y2={PAD.top + plotH} stroke={GRID} strokeWidth="1" strokeDasharray="2 3" />
        )}

        {showQuota && (
          <g>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(quota)} y2={y(quota)} stroke={QUOTA} strokeWidth="1" strokeDasharray="4 3" />
            <text x={W - PAD.right} y={y(quota) - 5} textAnchor="end" fontSize="11" fill="#475569">
              Quota {formatValue(quota)}
            </text>
          </g>
        )}

        <path d={historyPath} fill="none" stroke={LINE} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {projectionPath && (
          <>
            <path d={projectionPath} fill="none" stroke={LINE} strokeWidth="2" strokeDasharray="6 4" strokeLinecap="round" />
            {/* labeled mid-way and below the dashed line, clear of the quota label at the right edge */}
            <text
              x={x(history.length - 1 + Math.floor(projection.length / 2))}
              y={y(projection[Math.floor(projection.length / 2)].value) + 18}
              textAnchor="middle"
              fontSize="11"
              fill="#475569"
            >
              Projected
            </text>
          </>
        )}

        {hovered && (
          <g pointerEvents="none">
            <line x1={x(hoverIndex)} x2={x(hoverIndex)} y1={PAD.top} y2={PAD.top + plotH} stroke={MUTED} strokeWidth="1" />
            <circle cx={x(hoverIndex)} cy={y(hovered.value)} r="4.5" fill={LINE} stroke="#ffffff" strokeWidth="2" />
          </g>
        )}
        {/* transparent hit area over the whole plot, so hover works between points */}
        <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="transparent" />
      </svg>

      {hovered && (
        <div
          className="absolute top-0 pointer-events-none bg-white border rounded-md shadow-md px-2.5 py-1.5 text-xs whitespace-nowrap"
          style={{
            left: `${tooltipLeftPct}%`,
            transform: `translateX(${tooltipLeftPct > 60 ? "calc(-100% - 10px)" : "10px"})`,
          }}
        >
          <p className="text-slate-500">
            {shortDate(hovered.date)}
            {hovered.projected && " · projected"}
          </p>
          <p className="font-semibold text-slate-900 tabular-nums">{formatValue(hovered.value)}</p>
        </div>
      )}
    </div>
  );
}
