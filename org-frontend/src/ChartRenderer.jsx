import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  ScatterChart,
  Scatter,
  ZAxis,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Treemap,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// Palette derived from the app's existing accent (--accent: #c9974d) so
// charts feel native to the theme instead of default recharts colors.
const PALETTE = [
  "#c9974d", // accent
  "#7ea8c9", // slate blue
  "#6fbf8b", // success green
  "#d97757", // error/terracotta
  "#b48ead", // muted plum
  "#8a713f", // accent-dim
  "#5b8f9c", // teal
  "#c97d97", // dusty rose
];

function colorAt(i) {
  return PALETTE[i % PALETTE.length];
}

// ---- generic helpers -------------------------------------------------

function firstRow(data) {
  return Array.isArray(data) && data.length > 0 ? data[0] : null;
}

function isNumeric(v) {
  return typeof v === "number" || (typeof v === "string" && v.trim() !== "" && !isNaN(Number(v)));
}

function guessLabelKey(row) {
  if (!row) return null;
  const preferred = ["label", "name", "category", "title", "date", "period"];
  for (const k of preferred) if (k in row) return k;
  const keys = Object.keys(row);
  return keys.find((k) => !isNumeric(row[k])) ?? keys[0] ?? null;
}

function guessValueKeys(row, excludeKey) {
  if (!row) return [];
  const keys = Object.keys(row).filter((k) => k !== excludeKey && isNumeric(row[k]));
  return keys.length > 0 ? keys : Object.keys(row).filter((k) => k !== excludeKey);
}

function resolveKeys(spec) {
  const row = firstRow(spec.data);
  const labelKey =
    (spec.x_axis && row && spec.x_axis in row && spec.x_axis) || guessLabelKey(row);
  const explicitValue = spec.y_axis && row && spec.y_axis in row ? [spec.y_axis] : null;
  const valueKeys = explicitValue ?? guessValueKeys(row, labelKey);
  return { labelKey, valueKeys };
}

function findKey(row, candidates) {
  return candidates.find((k) => row && k in row);
}

function parseDate(v) {
  const d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
}

// ---- shared chrome ---------------------------------------------------

function ChartFrame({ spec, children, height = 280 }) {
  return (
    <div className="chart-frame">
      {spec.title && <div className="chart-title">{spec.title}</div>}
      {spec.description && <div className="chart-description">{spec.description}</div>}
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function StaticFrame({ spec, children }) {
  return (
    <div className="chart-frame">
      {spec.title && <div className="chart-title">{spec.title}</div>}
      {spec.description && <div className="chart-description">{spec.description}</div>}
      {children}
    </div>
  );
}

function EmptyState({ spec }) {
  return (
    <div className="chart-frame">
      {spec.title && <div className="chart-title">{spec.title}</div>}
      <div className="chart-empty">No data was returned for this query.</div>
    </div>
  );
}

const axisTick = { fill: "var(--text-dim)", fontSize: 12 };
const tooltipStyle = {
  background: "var(--panel)",
  border: "1px solid var(--hairline)",
  borderRadius: 8,
  color: "var(--text)",
  fontSize: 13,
};
const legendStyle = { color: "var(--text-dim)", fontSize: 12 };

// ======================================================================
// Category / comparison charts
// ======================================================================

function PieChartView({ spec, donut }) {
  const { labelKey, valueKeys } = resolveKeys(spec);
  const valueKey = valueKeys[0];
  return (
    <ChartFrame spec={spec}>
      <PieChart>
        <Pie
          data={spec.data}
          dataKey={valueKey}
          nameKey={labelKey}
          cx="50%"
          cy="50%"
          innerRadius={donut ? 60 : 0}
          outerRadius={95}
          paddingAngle={2}
        >
          {spec.data.map((_, i) => (
            <Cell key={i} fill={colorAt(i)} />
          ))}
        </Pie>
        <Tooltip contentStyle={tooltipStyle} />
        <Legend wrapperStyle={legendStyle} />
      </PieChart>
    </ChartFrame>
  );
}

function BarChartView({ spec, horizontal, stacked }) {
  const { labelKey, valueKeys } = resolveKeys(spec);
  return (
    <ChartFrame spec={spec}>
      <BarChart data={spec.data} layout={horizontal ? "vertical" : "horizontal"}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--hairline)" />
        {horizontal ? (
          <>
            <XAxis type="number" tick={axisTick} />
            <YAxis type="category" dataKey={labelKey} tick={axisTick} width={110} />
          </>
        ) : (
          <>
            <XAxis dataKey={labelKey} tick={axisTick} />
            <YAxis tick={axisTick} />
          </>
        )}
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--panel-2)" }} />
        {valueKeys.length > 1 && <Legend wrapperStyle={legendStyle} />}
        {valueKeys.map((k, i) => (
          <Bar
            key={k}
            dataKey={k}
            fill={colorAt(i)}
            stackId={stacked ? "stack" : undefined}
            radius={stacked ? 0 : [4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </ChartFrame>
  );
}

function LineAreaView({ spec, area }) {
  const { labelKey, valueKeys } = resolveKeys(spec);
  const Chart = area ? AreaChart : LineChart;
  return (
    <ChartFrame spec={spec}>
      <Chart data={spec.data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--hairline)" />
        <XAxis dataKey={labelKey} tick={axisTick} />
        <YAxis tick={axisTick} />
        <Tooltip contentStyle={tooltipStyle} />
        {valueKeys.length > 1 && <Legend wrapperStyle={legendStyle} />}
        {valueKeys.map((k, i) =>
          area ? (
            <Area
              key={k}
              type="monotone"
              dataKey={k}
              stroke={colorAt(i)}
              fill={colorAt(i)}
              fillOpacity={0.22}
              strokeWidth={2}
            />
          ) : (
            <Line
              key={k}
              type="monotone"
              dataKey={k}
              stroke={colorAt(i)}
              strokeWidth={2}
              dot={{ r: 3 }}
            />
          )
        )}
      </Chart>
    </ChartFrame>
  );
}

function ScatterChartView({ spec }) {
  const row = firstRow(spec.data);
  const numericKeys = row ? Object.keys(row).filter((k) => isNumeric(row[k])) : [];
  const xKey = spec.x_axis || numericKeys[0];
  const yKey = spec.y_axis || numericKeys[1];
  return (
    <ChartFrame spec={spec}>
      <ScatterChart>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--hairline)" />
        <XAxis dataKey={xKey} name={xKey} tick={axisTick} />
        <YAxis dataKey={yKey} name={yKey} tick={axisTick} />
        <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
        <Scatter data={spec.data} fill={colorAt(0)} />
      </ScatterChart>
    </ChartFrame>
  );
}

// True bubble chart: third numeric field drives dot size via ZAxis,
// distinct from a plain x/y scatter.
function BubbleChartView({ spec }) {
  const row = firstRow(spec.data);
  const numericKeys = row ? Object.keys(row).filter((k) => isNumeric(row[k])) : [];
  const xKey = spec.x_axis || numericKeys[0];
  const yKey = spec.y_axis || numericKeys[1];
  const zKey = numericKeys.find((k) => k !== xKey && k !== yKey);
  return (
    <ChartFrame spec={spec}>
      <ScatterChart>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--hairline)" />
        <XAxis dataKey={xKey} name={xKey} tick={axisTick} />
        <YAxis dataKey={yKey} name={yKey} tick={axisTick} />
        {zKey && <ZAxis dataKey={zKey} name={zKey} range={[60, 400]} />}
        <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
        <Scatter data={spec.data} fill={colorAt(0)} fillOpacity={0.65} />
      </ScatterChart>
    </ChartFrame>
  );
}

function RadarChartView({ spec }) {
  const { labelKey, valueKeys } = resolveKeys(spec);
  return (
    <ChartFrame spec={spec}>
      <RadarChart data={spec.data} outerRadius={95}>
        <PolarGrid stroke="var(--hairline)" />
        <PolarAngleAxis dataKey={labelKey} tick={axisTick} />
        <PolarRadiusAxis tick={axisTick} />
        {valueKeys.map((k, i) => (
          <Radar key={k} dataKey={k} stroke={colorAt(i)} fill={colorAt(i)} fillOpacity={0.3} />
        ))}
        <Tooltip contentStyle={tooltipStyle} />
        {valueKeys.length > 1 && <Legend wrapperStyle={legendStyle} />}
      </RadarChart>
    </ChartFrame>
  );
}

// ======================================================================
// Single metric / ranking
// ======================================================================

function GaugeView({ spec }) {
  const row = firstRow(spec.data);
  if (!row) return <EmptyState spec={spec} />;
  const valueKey = guessValueKeys(row, guessLabelKey(row))[0];
  const value = Number(row[valueKey]) || 0;
  const max = Number(row.max ?? 100);
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <StaticFrame spec={spec}>
      <div className="gauge-wrap">
        <div className="gauge-track">
          <div className="gauge-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="gauge-value">
          {value}
          {row.max ? ` / ${max}` : ""}
        </div>
      </div>
    </StaticFrame>
  );
}

function CardView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const labelKey = guessLabelKey(row0);
  const valueKey = guessValueKeys(row0, labelKey)[0];
  return (
    <StaticFrame spec={spec}>
      <div className="kpi-grid">
        {rows.map((r, i) => (
          <div className="kpi-card" key={i}>
            <div className="kpi-value">{String(r[valueKey])}</div>
            <div className="kpi-label">{String(r[labelKey])}</div>
          </div>
        ))}
      </div>
    </StaticFrame>
  );
}

// Dashboard: several KPIs together, shown with a relative mini-bar so the
// set reads as one dashboard rather than a plain card grid.
function DashboardView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const labelKey = guessLabelKey(row0);
  const valueKey = guessValueKeys(row0, labelKey)[0];
  const maxVal = Math.max(...rows.map((r) => Number(r[valueKey]) || 0), 1);
  return (
    <StaticFrame spec={spec}>
      <div className="dashboard-grid">
        {rows.map((r, i) => {
          const val = Number(r[valueKey]) || 0;
          const pct = Math.min(100, (val / maxVal) * 100);
          return (
            <div className="dash-card" key={i}>
              <div className="dash-card-label">{String(r[labelKey])}</div>
              <div className="dash-card-value">{String(r[valueKey])}</div>
              <div className="dash-mini-track">
                <div className="dash-mini-fill" style={{ width: `${pct}%`, background: colorAt(i) }} />
              </div>
            </div>
          );
        })}
      </div>
    </StaticFrame>
  );
}

function LeaderboardView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const labelKey = guessLabelKey(row0);
  const valueKey = guessValueKeys(row0, labelKey)[0];
  return (
    <StaticFrame spec={spec}>
      <ol className="leaderboard">
        {rows.map((r, i) => (
          <li className="leaderboard-row" key={i}>
            <span className={`lb-rank ${i < 3 ? "lb-rank-top" : ""}`}>{i + 1}</span>
            <span className="lb-name">{String(r[labelKey])}</span>
            <span className="lb-value">{String(r[valueKey])}</span>
          </li>
        ))}
      </ol>
    </StaticFrame>
  );
}

function TableView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const columns = row0 ? Object.keys(row0) : [];
  return (
    <StaticFrame spec={spec}>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c}>{String(r[c] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </StaticFrame>
  );
}

// ======================================================================
// Distribution over a grid
// ======================================================================

function HeatmapView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const keys = Object.keys(row0);
  const catKeys = keys.filter((k) => !isNumeric(row0[k]));
  const numericKeys = keys.filter((k) => isNumeric(row0[k]));

  if (catKeys.length < 2 || numericKeys.length < 1) return <UnsupportedView spec={spec} />;

  const [rowKey, colKey] = catKeys;
  const valueKey = numericKeys[0];
  const rowVals = Array.from(new Set(rows.map((r) => String(r[rowKey]))));
  const colVals = Array.from(new Set(rows.map((r) => String(r[colKey]))));
  const matrix = {};
  rows.forEach((r) => {
    matrix[`${r[rowKey]}|${r[colKey]}`] = Number(r[valueKey]) || 0;
  });
  const maxVal = Math.max(...Object.values(matrix), 1);

  return (
    <StaticFrame spec={spec}>
      <div className="heatmap-scroll">
        <table className="heatmap-table">
          <thead>
            <tr>
              <th></th>
              {colVals.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rowVals.map((r) => (
              <tr key={r}>
                <th>{r}</th>
                {colVals.map((c) => {
                  const v = matrix[`${r}|${c}`] ?? 0;
                  const alpha = v === 0 ? 0.05 : 0.12 + 0.85 * (v / maxVal);
                  return (
                    <td
                      key={c}
                      style={{ background: `rgba(201, 151, 77, ${alpha})` }}
                      title={`${r} / ${c}: ${v}`}
                    >
                      {v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </StaticFrame>
  );
}

// GitHub-style contribution calendar. Expects a date-like field + a
// numeric value field per row.
function CalendarView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const dateKey = findKey(row0, ["date", "day"]) || guessLabelKey(row0);
  const valueKey = guessValueKeys(row0, dateKey)[0];

  const parsed = rows
    .map((r) => ({ date: parseDate(r[dateKey]), value: Number(r[valueKey]) || 0 }))
    .filter((p) => p.date)
    .sort((a, b) => a.date - b.date);

  if (parsed.length === 0) return <UnsupportedView spec={spec} />;

  const maxVal = Math.max(...parsed.map((p) => p.value), 1);
  const valueByDate = {};
  parsed.forEach((p) => {
    valueByDate[p.date.toDateString()] = p.value;
  });

  const start = new Date(parsed[0].date);
  start.setDate(start.getDate() - start.getDay());
  const end = parsed[parsed.length - 1].date;

  const days = [];
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const key = d.toDateString();
    days.push({ date: new Date(d), value: key in valueByDate ? valueByDate[key] : null });
  }
  const weeks = [];
  for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7));

  return (
    <StaticFrame spec={spec}>
      <div className="calendar-grid">
        {weeks.map((week, wi) => (
          <div className="calendar-week" key={wi}>
            {week.map((d, di) => {
              const hasVal = d.value !== null;
              const alpha = hasVal ? 0.15 + 0.85 * (d.value / maxVal) : 0;
              return (
                <div
                  key={di}
                  className="calendar-cell"
                  title={`${d.date.toLocaleDateString()}: ${hasVal ? d.value : "no data"}`}
                  style={{
                    background: hasVal ? `rgba(201, 151, 77, ${alpha})` : "var(--panel-2)",
                  }}
                />
              );
            })}
          </div>
        ))}
      </div>
    </StaticFrame>
  );
}

// ======================================================================
// Time-based / schedule
// ======================================================================

function GanttView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const labelKey = guessLabelKey(row0);
  const startKey = findKey(row0, ["start", "start_date", "from"]);
  const endKey = findKey(row0, ["end", "end_date", "to"]);

  if (!startKey || !endKey) return <UnsupportedView spec={spec} />;

  const parsed = rows
    .map((r) => ({ label: r[labelKey], start: parseDate(r[startKey]), end: parseDate(r[endKey]) }))
    .filter((p) => p.start && p.end);

  if (parsed.length === 0) return <UnsupportedView spec={spec} />;

  const minDate = new Date(Math.min(...parsed.map((p) => p.start.getTime())));
  const maxDate = new Date(Math.max(...parsed.map((p) => p.end.getTime())));
  const totalMs = maxDate - minDate || 1;

  return (
    <StaticFrame spec={spec}>
      <div className="gantt-chart">
        {parsed.map((p, i) => {
          const leftPct = ((p.start - minDate) / totalMs) * 100;
          const widthPct = Math.max(((p.end - p.start) / totalMs) * 100, 1.5);
          return (
            <div className="gantt-row" key={i}>
              <div className="gantt-label">{String(p.label)}</div>
              <div className="gantt-track">
                <div
                  className="gantt-bar"
                  style={{ left: `${leftPct}%`, width: `${widthPct}%`, background: colorAt(i) }}
                  title={`${p.start.toLocaleDateString()} \u2013 ${p.end.toLocaleDateString()}`}
                />
              </div>
            </div>
          );
        })}
        <div className="gantt-axis">
          <span>{minDate.toLocaleDateString()}</span>
          <span>{maxDate.toLocaleDateString()}</span>
        </div>
      </div>
    </StaticFrame>
  );
}

// Horizontal event timeline (distinct from a continuous trend line):
// each row is a discrete dated event plotted as a point on an axis.
function TimelineView({ spec }) {
  const row0 = firstRow(spec.data);
  const dateKey = findKey(row0, ["date", "start", "start_date", "period", "posted_at"]) || guessLabelKey(row0);
  const labelKey = Object.keys(row0).find((k) => k !== dateKey) || dateKey;

  const parsed = spec.data
    .map((r) => ({ date: parseDate(r[dateKey]), label: String(r[labelKey] ?? r[dateKey]) }))
    .filter((p) => p.date)
    .sort((a, b) => a.date - b.date);

  if (parsed.length === 0) return <LineAreaView spec={spec} area={false} />;

  const minT = parsed[0].date.getTime();
  const maxT = parsed[parsed.length - 1].date.getTime();
  const span = maxT - minT || 1;

  return (
    <StaticFrame spec={spec}>
      <div className="timeline-wrap">
        <div className="timeline-line" />
        {parsed.map((p, i) => {
          const leftPct = ((p.date.getTime() - minT) / span) * 100;
          const above = i % 2 === 0;
          return (
            <div
              key={i}
              className={`timeline-point ${above ? "above" : "below"}`}
              style={{ left: `${leftPct}%` }}
            >
              {above && (
                <div className="timeline-label">
                  <div className="timeline-label-date">{p.date.toLocaleDateString()}</div>
                  <div className="timeline-label-text">{p.label}</div>
                </div>
              )}
              <div className="timeline-dot" style={{ background: colorAt(i) }} />
              {!above && (
                <div className="timeline-label">
                  <div className="timeline-label-date">{p.date.toLocaleDateString()}</div>
                  <div className="timeline-label-text">{p.label}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </StaticFrame>
  );
}

// ======================================================================
// Hierarchy / relationships
// ======================================================================

function TreemapContent(props) {
  const { x, y, width, height, name, fill, value } = props;
  if (width < 2 || height < 2) return null;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} style={{ fill, stroke: "var(--bg)", strokeWidth: 2 }} />
      {width > 50 && height > 22 && (
        <text x={x + 6} y={y + 16} fontSize="11" fontWeight="600" fill="var(--accent-ink)">
          {name}
        </text>
      )}
      {width > 50 && height > 36 && (
        <text x={x + 6} y={y + 30} fontSize="10" fill="var(--accent-ink)" opacity="0.85">
          {value}
        </text>
      )}
    </g>
  );
}

function TreemapView({ spec }) {
  const { labelKey, valueKeys } = resolveKeys(spec);
  const valueKey = valueKeys[0];
  const treeData = spec.data.map((d, i) => ({
    name: String(d[labelKey]),
    size: Math.max(Number(d[valueKey]) || 0, 0.01),
    fill: colorAt(i),
  }));
  return (
    <ChartFrame spec={spec}>
      <Treemap data={treeData} dataKey="size" nameKey="name" stroke="var(--bg)" content={<TreemapContent />} />
    </ChartFrame>
  );
}

// Approximated as a two-ring donut: inner ring = category, outer ring =
// subcategory, colored to match its parent. Falls back to a plain donut
// if the data only has one categorical dimension.
function SunburstView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const keys = Object.keys(row0);
  const catKeys = keys.filter((k) => !isNumeric(row0[k]));
  const numericKeys = keys.filter((k) => isNumeric(row0[k]));

  if (catKeys.length < 2 || numericKeys.length < 1) {
    return <PieChartView spec={spec} donut={true} />;
  }

  const [innerKeyName, outerKey] = catKeys;
  const valueKey = numericKeys[0];

  const innerMap = {};
  rows.forEach((r) => {
    const k = String(r[innerKeyName]);
    innerMap[k] = (innerMap[k] || 0) + (Number(r[valueKey]) || 0);
  });
  const innerData = Object.entries(innerMap).map(([name, value]) => ({ name, value }));
  const parentColor = {};
  innerData.forEach((d, i) => {
    parentColor[d.name] = colorAt(i);
  });
  const outerData = rows.map((r) => ({
    name: String(r[outerKey]),
    value: Number(r[valueKey]) || 0,
    parent: String(r[innerKeyName]),
  }));

  return (
    <ChartFrame spec={spec}>
      <PieChart>
        <Pie data={innerData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={0} outerRadius={60}>
          {innerData.map((_, i) => (
            <Cell key={i} fill={colorAt(i)} />
          ))}
        </Pie>
        <Pie data={outerData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={68} outerRadius={95}>
          {outerData.map((d, i) => (
            <Cell key={i} fill={parentColor[d.parent] || colorAt(i)} fillOpacity={0.75} />
          ))}
        </Pie>
        <Tooltip contentStyle={tooltipStyle} />
        <Legend
          wrapperStyle={legendStyle}
          payload={innerData.map((d, i) => ({ value: d.name, type: "square", color: colorAt(i) }))}
        />
      </PieChart>
    </ChartFrame>
  );
}

// Node-link diagram. Expects rows shaped like {source, target} (or
// from/to). Nodes are derived from the edge list and laid out on a
// circle — no physics simulation, just enough structure to be readable.
function NetworkView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  const srcKey = findKey(row0, ["source", "from", "a"]);
  const tgtKey = findKey(row0, ["target", "to", "b"]);

  if (!srcKey || !tgtKey) return <UnsupportedView spec={spec} />;

  const edges = rows.map((r) => ({ source: String(r[srcKey]), target: String(r[tgtKey]) }));
  const nodes = Array.from(new Set(edges.flatMap((e) => [e.source, e.target])));
  const n = nodes.length;
  const R = 150;
  const cx = 200;
  const cy = 200;
  const positions = {};
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    positions[node] = { x: cx + R * Math.cos(angle), y: cy + R * Math.sin(angle) };
  });

  return (
    <StaticFrame spec={spec}>
      <svg viewBox="0 0 400 400" className="network-svg">
        {edges.map((e, i) => {
          const p1 = positions[e.source];
          const p2 = positions[e.target];
          return <line key={i} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="var(--hairline)" strokeWidth="1.5" />;
        })}
        {nodes.map((node, i) => {
          const p = positions[node];
          const short = node.length > 10 ? node.slice(0, 9) + "\u2026" : node;
          return (
            <g key={i}>
              <circle cx={p.x} cy={p.y} r="22" fill={colorAt(i)} />
              <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize="9" fill="var(--accent-ink)">
                {short}
              </text>
            </g>
          );
        })}
      </svg>
    </StaticFrame>
  );
}

function OrgNode({ node, nameKey }) {
  return (
    <div className="org-node">
      <div className="org-box">{String(node[nameKey])}</div>
      {node.children.length > 0 && (
        <div className={`org-children ${node.children.length > 1 ? "multi" : ""}`}>
          {node.children.map((c, i) => (
            <div className="org-child-wrap" key={i}>
              <OrgNode node={c} nameKey={nameKey} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Reporting-hierarchy tree. Expects a flat list of rows with an id-like
// field and a manager/parent-id-like field (matches users/tasks-style
// tables directly).
function OrgChartView({ spec }) {
  const rows = spec.data;
  const row0 = firstRow(rows);
  if (!row0) return <EmptyState spec={spec} />;

  const idKey = findKey(row0, ["id", "user_id", "employee_id"]);
  const parentKey = findKey(row0, ["manager_id", "parent_id", "parent", "manager"]);
  const nameKey = findKey(row0, ["name", "title", "label"]) || guessLabelKey(row0);

  if (!parentKey) return <UnsupportedView spec={spec} />;

  const keyOf = (r) => (idKey ? r[idKey] : r[nameKey]);
  const byId = {};
  rows.forEach((r) => {
    byId[keyOf(r)] = { ...r, children: [] };
  });
  const roots = [];
  rows.forEach((r) => {
    const p = r[parentKey];
    if (p != null && byId[p]) byId[p].children.push(byId[keyOf(r)]);
    else roots.push(byId[keyOf(r)]);
  });

  return (
    <StaticFrame spec={spec}>
      <div className="org-chart-scroll">
        <div className="org-tree">
          {roots.map((r, i) => (
            <OrgNode key={i} node={r} nameKey={nameKey} />
          ))}
        </div>
      </div>
    </StaticFrame>
  );
}

// ======================================================================
// Fallback + report + entry point
// ======================================================================

function UnsupportedView({ spec }) {
  const hasRows = Array.isArray(spec.data) && spec.data.length > 0;
  return (
    <div className="chart-frame">
      {spec.title && <div className="chart-title">{spec.title}</div>}
      <div className="chart-fallback-note">
        Couldn't detect the fields "{spec.chart_type}" needs (e.g. source/target for a network, start/end
        dates for a gantt) \u2014 showing the raw data below instead.
      </div>
      {hasRows && <TableView spec={spec} />}
    </div>
  );
}

function ReportView({ spec }) {
  return (
    <div className="chart-frame report-frame">
      <div className="chart-title">{spec.title}</div>
      {spec.summary && <p className="report-summary">{spec.summary}</p>}
      {(spec.sections || []).map((s, i) => (
        <div className="report-section" key={i}>
          <div className="report-heading">{s.heading}</div>
          <div className="report-content">
            {Array.isArray(s.content) ? (
              <ul>
                {s.content.map((line, j) => (
                  <li key={j}>{String(line)}</li>
                ))}
              </ul>
            ) : (
              <p>{String(s.content)}</p>
            )}
          </div>
        </div>
      ))}
      {spec.recommendations && spec.recommendations.length > 0 && (
        <div className="report-section">
          <div className="report-heading">Recommendations</div>
          <ul>
            {spec.recommendations.map((r, i) => (
              <li key={i}>{String(r)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function ChartRenderer({ spec }) {
  if (!spec || spec.success === false) {
    return spec?.message ? (
      <div className="chart-frame">
        <div className="chart-empty">{spec.message}</div>
      </div>
    ) : null;
  }

  if (spec.response_type === "report") {
    return <ReportView spec={spec} />;
  }

  if (!Array.isArray(spec.data) || spec.data.length === 0) {
    return <EmptyState spec={spec} />;
  }

  switch (spec.chart_type) {
    case "pie":
      return <PieChartView spec={spec} donut={false} />;
    case "donut":
      return <PieChartView spec={spec} donut={true} />;
    case "bar":
      return <BarChartView spec={spec} horizontal={false} stacked={false} />;
    case "horizontal_bar":
      return <BarChartView spec={spec} horizontal={true} stacked={false} />;
    case "stacked_bar":
      return <BarChartView spec={spec} horizontal={false} stacked={true} />;
    case "line":
      return <LineAreaView spec={spec} area={false} />;
    case "area":
      return <LineAreaView spec={spec} area={true} />;
    case "scatter":
      return <ScatterChartView spec={spec} />;
    case "bubble":
      return <BubbleChartView spec={spec} />;
    case "radar":
      return <RadarChartView spec={spec} />;
    case "gauge":
      return <GaugeView spec={spec} />;
    case "card":
      return <CardView spec={spec} />;
    case "dashboard":
      return <DashboardView spec={spec} />;
    case "leaderboard":
      return <LeaderboardView spec={spec} />;
    case "table":
      return <TableView spec={spec} />;
    case "heatmap":
      return <HeatmapView spec={spec} />;
    case "calendar":
      return <CalendarView spec={spec} />;
    case "gantt":
      return <GanttView spec={spec} />;
    case "timeline":
      return <TimelineView spec={spec} />;
    case "treemap":
      return <TreemapView spec={spec} />;
    case "sunburst":
      return <SunburstView spec={spec} />;
    case "network":
      return <NetworkView spec={spec} />;
    case "org_chart":
      return <OrgChartView spec={spec} />;
    default:
      return <UnsupportedView spec={spec} />;
  }
}
