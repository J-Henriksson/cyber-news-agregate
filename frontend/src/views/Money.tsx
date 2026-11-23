import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { api, ago, cssVar, KIND_LABEL, usd, type MoneyView } from "../api";
import { hideTip, showTip } from "../lib/tip";
import { useWidth } from "../lib/useWidth";
import type { ViewProps } from "../App";

const DAMAGE = ["theft", "ransom_paid", "ransom_demand", "loss", "fine", "settlement"];
const KINDS = [["", "All damage"], ["theft", "Stolen"], ["ransom_demand", "Ransom asked"], ["ransom_paid", "Ransom paid"], ["loss", "Loss"],
  ["fine", "Fines"], ["settlement", "Settlements"], ["rest", "Not damage"]] as const;

/** The amounts the sources stated. From thousands to billions on one axis
 *  takes a log scale, and on a log scale a bar's length means nothing: so
 *  each amount is a dot at its place, the figure written beside it. */
export default function Money({ days, since, label, q, tick, onSelect, desk }: ViewProps) {
  const [data, setData] = useState<MoneyView | null>(null);
  const [kind, setKind] = useState("");
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState(false);
  const ref = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const width = Math.min(1200, useWidth(wrap) - 44);

  useEffect(() => {
    setBusy(true);
    api.money(days, desk, since).then((d) => { setData(d); setFailed(false); }).catch(() => setFailed(true)).finally(() => setBusy(false));
  }, [days, since, tick, desk]);

  const facts = useMemo(() => {
    const ql = q.toLowerCase();
    return (data?.facts ?? []).filter((f) => f.usd
      && (kind === "rest" ? !DAMAGE.includes(f.kind) : kind ? f.kind === kind : DAMAGE.includes(f.kind))
      && (!ql || f.title.toLowerCase().includes(ql) || f.victims.join(" ").toLowerCase().includes(ql)));
  }, [data, kind, q]);
  const top = facts.slice(0, 40);
  const has = new Set((data?.facts ?? []).filter((f) => f.usd).map((f) => (DAMAGE.includes(f.kind) ? f.kind : "rest")));

  useEffect(() => {
    if (!ref.current) return;
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    if (!top.length) return;
    const row = 22, m = { l: Math.min(300, width * 0.32), r: 150, t: 8, b: 26 };
    const height = m.t + m.b + top.length * row;
    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("height", height);
    const lo = d3.min(top, (f) => f.usd!)!, hi = d3.max(top, (f) => f.usd!)!;
    const x = d3.scaleLog().domain([Math.max(100, lo / 2), hi * 1.6]).range([m.l, width - m.r]);
    svg.append("g").attr("class", "axis grid").attr("transform", `translate(0,${height - m.b})`)
      .call(d3.axisBottom(x).ticks(6, (n: d3.NumberValue) => usd(Number(n))).tickSize(-(height - m.t - m.b)).tickPadding(8));
    const bg = cssVar("--bg"), series = cssVar("--series"), ink = cssVar("--text");
    const g = svg.append("g").selectAll("g").data(top).join("g")
      .attr("transform", (_f, i) => `translate(0,${m.t + i * row})`).style("cursor", "pointer")
      .on("click", (_e, f) => onSelect(f.incident))
      .on("pointermove", (e: PointerEvent, f) => showTip(tipRef.current, e,
        [{ text: `${usd(f.usd)} ${KIND_LABEL[f.kind] ?? f.kind}`, bold: true }, f.title, `"${f.quote}"`, { text: f.source, dim: true }]))
      .on("pointerleave", () => hideTip(tipRef.current));
    // The whole row answers to the pointer, not the dot alone.
    g.append("rect").attr("x", 0).attr("width", width).attr("height", row).attr("fill", "transparent");
    g.append("text").attr("x", m.l - 14).attr("y", row / 2 + 4).attr("text-anchor", "end")
      .text((f) => { const name = f.victims[0] ?? f.title; return name.length > 44 ? `${name.slice(0, 42)}...` : name; }).style("fill", ink);
    g.append("circle").attr("cx", (f) => x(f.usd!)).attr("cy", row / 2).attr("r", 5).attr("fill", series).attr("stroke", bg).attr("stroke-width", 2);
    g.append("text").attr("x", (f) => x(f.usd!) + 11).attr("y", row / 2 + 4)
      .text((f) => `${usd(f.usd)}  ${KIND_LABEL[f.kind] ?? f.kind}`).style("fill", cssVar("--muted"));
  }, [top, onSelect, width]);

  const kinds = Object.entries(data?.by_kind ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <div ref={wrap} className={`view ${busy ? "busy" : ""}`}>
      <h2>Money <span className="muted">· amounts the sources stated, {label}</span></h2>
      <p className="note">Every amount here is one a source stated, with its words kept (hover a row). Adding them up gives what was reported, which is
        not what was lost: most incidents state no amount, and a ransom asked is not a ransom paid.
        Exchange rates: {data?.fx_source}{data?.fx_day ? ` ${data.fx_day}` : ""}.</p>
      {kinds.length > 0 && (
        <div className="tiles">
          {kinds.map(([k, v]) => (
            <div className="tile" key={k}><span className="tile-label">{KIND_LABEL[k] ?? k}</span><b className="tile-value">{usd(v)}</b>
              <span className="tile-sub">reported in all</span></div>
          ))}
        </div>
      )}
      <div className="toolbar" style={{ marginTop: 14 }}>
        <span className="seg" role="group" aria-label="Kind of amount">
          {KINDS.filter(([k]) => !k || has.has(k)).map(([k, name]) => <button key={k} className={`btn ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>{name}</button>)}
        </span>
        <span className="label">{facts.length} amount{facts.length === 1 ? "" : "s"}{facts.length > top.length ? `, the ${top.length} largest drawn` : ""} · each dot at its amount, on a scale of tens</span>
      </div>
      {failed && <div className="empty">The amounts could not be read.</div>}
      {!failed && top.length === 0 ? <div className="empty">No amount of this kind reported in this window.</div>
        : <svg ref={ref} role="img" aria-label="Reported amounts" style={{ display: "block", maxWidth: "100%" }} />}
      <h3>All amounts ({facts.length})</h3>
      <table className="grid" style={{ maxWidth: 1300 }}>
        <thead><tr><th className="num">USD</th><th>Kind</th><th>Incident</th><th>As stated</th><th>Source</th></tr></thead>
        <tbody>
          {facts.map((f, i) => (
            <tr key={i} className="click" onClick={() => onSelect(f.incident)}>
              <td className="num">{usd(f.usd)}</td>
              <td>{KIND_LABEL[f.kind] ?? f.kind}</td>
              <td>{f.title}<div className="faint small">{ago(f.when)}</div></td>
              <td className="muted small">"{f.quote}"</td>
              <td className="small">{f.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div ref={tipRef} className="chart-tip" style={{ display: "none" }} />
    </div>
  );
}
