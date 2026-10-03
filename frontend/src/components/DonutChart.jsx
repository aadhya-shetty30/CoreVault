/**
 * Dependency-free SVG donut. `segments` is [{ key, label, value, color }],
 * drawn clockwise from 12 o'clock in the order given (callers pass a fixed
 * category order, so a category's position and color never depend on its
 * rank). Each segment is separated by a 2px surface-colored gap, and
 * hovering one shows its value in the center. Hover state is controlled by
 * the caller (`hovered` / `onHover`) so a legend row can highlight its
 * segment and vice versa.
 */
export default function DonutChart({ segments, size = 200, thickness = 34, centerLabel, centerValue, formatValue, hovered, onHover }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const r = size / 2;
  const innerR = r - thickness;

  function setHover(key) {
    onHover?.(key);
  }

  function point(radius, angle) {
    return [r + radius * Math.sin(angle), r - radius * Math.cos(angle)];
  }

  function arcPath(start, end) {
    // A single full-circle segment can't be drawn as one arc -- split it.
    if (end - start >= Math.PI * 2 - 1e-6) end = start + Math.PI * 2 - 1e-4;
    const large = end - start > Math.PI ? 1 : 0;
    const [x1, y1] = point(r, start);
    const [x2, y2] = point(r, end);
    const [x3, y3] = point(innerR, end);
    const [x4, y4] = point(innerR, start);
    return `M${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} L${x3},${y3} A${innerR},${innerR} 0 ${large} 0 ${x4},${y4} Z`;
  }

  let angle = 0;
  const arcs = segments
    .filter((s) => s.value > 0)
    .map((s) => {
      const sweep = (s.value / total) * Math.PI * 2;
      const arc = { ...s, d: arcPath(angle, angle + sweep), share: s.value / total };
      angle += sweep;
      return arc;
    });

  const active = arcs.find((a) => a.key === hovered);

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Storage by file type">
        {total === 0 ? (
          <circle cx={r} cy={r} r={r - thickness / 2} fill="none" stroke="#e2e8f0" strokeWidth={thickness} />
        ) : (
          arcs.map((a) => (
            <path
              key={a.key}
              d={a.d}
              fill={a.color}
              stroke="#ffffff"
              strokeWidth={arcs.length > 1 ? 2 : 0}
              opacity={hovered && hovered !== a.key ? 0.45 : 1}
              onMouseEnter={() => setHover(a.key)}
              onMouseLeave={() => setHover(null)}
              className="cursor-default transition-opacity"
            />
          ))
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center">
        {active ? (
          <>
            <span className="text-xs text-slate-500">{active.label}</span>
            <span className="text-lg font-semibold text-slate-900">{formatValue(active.value)}</span>
            <span className="text-xs text-slate-500">{(active.share * 100).toFixed(1)}%</span>
          </>
        ) : (
          <>
            <span className="text-xs text-slate-500">{centerLabel}</span>
            <span className="text-lg font-semibold text-slate-900">{centerValue}</span>
          </>
        )}
      </div>
    </div>
  );
}
