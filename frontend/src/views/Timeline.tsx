import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { api, cssVar, type TimelineView } from "../api";
import { CLASSES, classOf } from "../lib/viz";
import { hideTip, showTip } from "../lib/tip";
import { useWidth } from "../lib/useWidth";
import type { ViewProps } from "../App";

/** Incidents by day (by hour for a day or two), stacked by kind in the
 *  palette's fixed order, and each group's incidents on its own lane. */
export default function Timeline({ days, since, label, tick, onSelect, desk }: ViewProps) {
  const [data, setData] = useState<TimelineView | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState(false);
  const [table, setTable] = useState(false);
  const bars = useRef<SVGSVGElement>(null);
  const lanes = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const width = Math.min(1400, useWidth(wrap) - 44);

  useEffect(() => {
    setBusy(true);
    api.timeline(days, desk, since).then((d) => { setData(d); setFailed(false); }).catch(() => setFailed(true)).finally(() => setBusy(false));
  }, [days, since, tick, desk]);

  // Each bucket's count per chart class (eleven categories fold into eight hues and grey).
  const stacked = useMemo(() => (data?.buckets ?? []).map((b) => {
    const per: Record<string, number> = {};
    for (const [cat, n] of Object.entries(b)) if (cat !== "t") per[classOf(cat)] = (per[classOf(cat)] ?? 0) + Number(n);
    return { t: b.t, per, total: d3.sum(Object.values(per)) };
  }), [data]);
  const classes = useMemo(() => CLASSES.filter((c) => stacked.some((b) => b.per[c.key])), [stacked]);
  const hourly = (data?.bucket ?? 86400) < 86400;
  const when = (t: number) => (hourly ? d3.timeFormat("%a %H:00")(new Date(t * 1000)) : d3.timeFormat("%a %b %d")(new Date(t * 1000)));

  useEffect(() => {
    if (!data || !bars.current || !lanes.current || table) return;
    const m = { l: 150, r: 14, t: 14, b: 24 };
    const muted = cssVar("--muted");
    const end = new Date();
    const start = new Date(data.start * 1000);
    const x = d3.scaleTime().domain([start, end]).range([m.l, width - m.r]).clamp(true);
    const per = data.bucket * 1000;
    // A bar is never thicker than 24: the rest of its slot is air.
    const slot = x(new Date(start.getTime() + per)) - x(start);
    const bw = Math.max(2, Math.min(24, slot - 3));
    const bg = cssVar("--bg");

    const h = 230;
    const svg = d3.select(bars.current).attr("viewBox", `0 0 ${width} ${h}`).attr("width", width).attr("height", h);
    svg.selectAll("*").remove();
    const y = d3.scaleLinear().domain([0, d3.max(stacked, (b) => b.total) ?? 1]).nice(4).range([h - m.b, m.t]);
    svg.append("g").attr("class", "axis grid").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(4).tickSize(-(width - m.l - m.r)).tickPadding(8));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${h - m.b})`).call(d3.axisBottom(x).ticks(8).tickSize(3));
    svg.append("text").attr("x", m.l - 44).attr("y", m.t + 4).attr("text-anchor", "end").text(hourly ? "incidents an hour" : "incidents a day")
      .style("font-size", "11px").style("fill", muted);
    const g = svg.append("g");
    for (const b of stacked) {
      const cx = Math.max(m.l + bw / 2, x(new Date(b.t * 1000 + per / 2)));
      let top = y(0);
      const parts = classes.filter((c) => b.per[c.key]);
      parts.forEach((c, i) => {
        const hgt = y(0) - y(b.per[c.key]);
        const y1 = top, y0 = top - hgt;
        top = y0;
        // A gap in the surface's colour parts the segments; the data end is rounded, the baseline square.
        const drawTop = y0 + (i === parts.length - 1 ? 0 : 2);
        const tall = Math.max(1, y1 - drawTop);
        const r = i === parts.length - 1 ? Math.min(4, bw / 2, tall) : 0;
        g.append("path")
          .attr("d", `M${cx - bw / 2},${y1}V${drawTop + r}q0,${-r} ${r},${-r}H${cx + bw / 2 - r}q${r},0 ${r},${r}V${y1}Z`)
          .attr("fill", cssVar(`--k-${c.key}`)).attr("stroke", "none")
          .on("pointermove", (e: PointerEvent) => showTip(tipRef.current, e,
            [{ text: `${b.per[c.key]} ${c.label}`, bold: true }, `${when(b.t)} · ${b.total} in all`]))
          .on("pointerleave", () => hideTip(tipRef.current));
      });
    }

    // Each group's incidents on its own lane: one hue, a ring of the surface around each dot.
    const lane = 24;
    const lh = m.t + m.b + Math.max(1, data.actors.length) * lane;
    const ls = d3.select(lanes.current).attr("viewBox", `0 0 ${width} ${lh}`).attr("width", width).attr("height", lh);
    ls.selectAll("*").remove();
    ls.append("g").attr("class", "axis").attr("transform", `translate(0,${lh - m.b})`).call(d3.axisBottom(x).ticks(8).tickSize(3));
    const rows = ls.append("g").selectAll("g").data(data.actors).join("g").attr("transform", (_a, i) => `translate(0,${m.t + i * lane})`);
    rows.append("line").attr("x1", m.l).attr("x2", width - m.r).attr("y1", lane / 2).attr("y2", lane / 2).attr("stroke", cssVar("--line"));
    rows.append("text").attr("x", m.l - 12).attr("y", lane / 2 + 4).attr("text-anchor", "end")
      .text((a) => `${a.name.length > 20 ? `${a.name.slice(0, 19)}...` : a.name}  ${a.events.length}`)
      .style("fill", cssVar("--text")).style("font-size", "12px");
    const dot = rows.selectAll("g").data((a) => a.events).join("g").style("cursor", "pointer")
      .attr("transform", (e) => `translate(${x(new Date(e.t * 1000 + per / 2))},${lane / 2})`)
      .on("click", (_e, ev) => onSelect(ev.id))
      .on("pointermove", (e: PointerEvent, ev) => showTip(tipRef.current, e, [{ text: `${ev.relevance} · ${ev.title}`, bold: true }, when(ev.t)]))
      .on("pointerleave", () => hideTip(tipRef.current));
    dot.append("circle").attr("r", 12).attr("fill", "transparent");
    dot.append("circle").attr("r", (e) => 4.5 + e.relevance / 20).attr("fill", cssVar("--g-group")).attr("stroke", bg).attr("stroke-width", 2);
  }, [data, stacked, classes, hourly, table, onSelect, width]);

  return (
    <div ref={wrap} className={`view ${busy ? "busy" : ""}`}>
      <div className="toolbar" style={{ marginBottom: 6 }}>
        <h2 style={{ margin: 0 }}>Timeline <span className="muted">· {hourly ? "hour by hour" : "day by day"}, {label}</span></h2>
        <span className="spacer" />
        <span className="seg" role="group" aria-label="Show as">
          <button className={`btn ${!table ? "on" : ""}`} onClick={() => setTable(false)}>Chart</button>
          <button className={`btn ${table ? "on" : ""}`} onClick={() => setTable(true)}>Table</button>
        </span>
      </div>
      {failed && <div className="empty">The timeline could not be read.</div>}
      <div className="legend" style={{ marginBottom: 8 }}>
        {classes.map((c) => <span key={c.key}><i style={{ background: `var(--k-${c.key})` }} />{c.label}</span>)}
      </div>
      {table ? (
        <table className="grid" style={{ maxWidth: 1000 }}>
          <thead><tr><th>{hourly ? "Hour" : "Day"}</th>{classes.map((c) => <th key={c.key} className="num">{c.label}</th>)}<th className="num">All</th></tr></thead>
          <tbody>
            {[...stacked].reverse().map((b) => (
              <tr key={b.t}><td className="mono small">{when(b.t)}</td>
                {classes.map((c) => <td key={c.key} className="num">{b.per[c.key] ?? ""}</td>)}<td className="num"><b>{b.total}</b></td></tr>
            ))}
          </tbody>
        </table>
      ) : (
        <>
          <svg ref={bars} role="img" aria-label="Incidents over time by kind" style={{ display: "block", maxWidth: "100%" }} />
          <h3>Groups, by incident · a larger dot matters more to us</h3>
          {data && data.actors.length === 0 && <p className="muted small">No group named as attacker in this window.</p>}
          <svg ref={lanes} role="img" aria-label="Each group's incidents over time" style={{ display: "block", maxWidth: "100%" }} />
        </>
      )}
      <div ref={tipRef} className="chart-tip" style={{ display: "none" }} />
    </div>
  );
}
