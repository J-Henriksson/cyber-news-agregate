import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { api, ago, count, cssVar, safeUrl, usd, type CompanyRow } from "../api";
import { hideTip, showTip } from "../lib/tip";
import { BAND_LABELS, bandColor, inkOn } from "../lib/viz";
import type { ViewProps } from "../App";

const SIZES = [["incidents", "Incidents"], ["usd", "Reported $"], ["relevance", "Relevance"]] as const;
type Size = (typeof SIZES)[number][0];

export default function Companies({ days, since, q, tick, onSelect, desk }: ViewProps) {
  const [rows, setRows] = useState<CompanyRow[]>([]);
  const [size, setSize] = useState<Size>("incidents");
  const [role, setRole] = useState<"all" | "victim" | "vendor">("victim");
  const [picked, setPicked] = useState<string | null>(null);
  const [mode, setMode] = useState<"map" | "table">("map");
  const [failed, setFailed] = useState(false);
  const ref = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.companies(days, desk, since).then((r) => { setRows(r.companies); setFailed(false); }).catch(() => setFailed(true));
  }, [days, since, tick, desk]);

  const shown = useMemo(() => {
    const ql = q.toLowerCase();
    return rows.filter((r) =>
      (role === "all" || (role === "victim" ? r.as_victim > 0 : r.as_vendor > 0)) &&
      (!ql || r.name.toLowerCase().includes(ql) || (r.sector ?? "").includes(ql)) &&
      (size !== "usd" || r.usd > 0));
  }, [rows, q, role, size]);

  useEffect(() => {
    if (!ref.current || mode !== "map") return;
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    const { width, height } = ref.current.getBoundingClientRect();
    if (!shown.length || width < 10) return;
    const value = (r: CompanyRow) => size === "usd" ? r.usd : size === "relevance" ? Math.max(1, r.relevance) : r.as_victim + r.as_vendor;
    const bySector = d3.group(shown, (r) => r.sector || "other");
    const root = d3.hierarchy<{ name: string; children?: unknown[]; row?: CompanyRow }>({
      name: "all",
      children: Array.from(bySector, ([sector, list]) => ({ name: sector, children: list.map((r) => ({ name: r.name, row: r })) })),
    }).sum((d) => (d.row ? value(d.row) : 0)).sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
    d3.treemap<{ name: string; row?: CompanyRow }>().size([width, height]).paddingInner(2).paddingOuter(3).paddingTop(20).round(true)(root as never);
    const color = (relevance: number) => bandColor(relevance);

    const sectors = svg.append("g").selectAll("g").data(root.children ?? []).join("g");
    sectors.append("rect")
      .attr("x", (d: any) => d.x0).attr("y", (d: any) => d.y0).attr("width", (d: any) => d.x1 - d.x0).attr("height", (d: any) => d.y1 - d.y0)
      .attr("fill", "none").attr("stroke", cssVar("--line"));
    sectors.append("text").attr("x", (d: any) => d.x0 + 5).attr("y", (d: any) => d.y0 + 13)
      .text((d: any) => (d.x1 - d.x0 > 60 ? `${d.data.name.toUpperCase()} · ${d.children?.length ?? 0}` : ""))
      .attr("font-size", 10).style("letter-spacing", "0.06em");

    const leaf = svg.append("g").selectAll("g").data(root.leaves()).join("g").style("cursor", "pointer")
      .on("click", (_e, d: any) => setPicked(d.data.row.key))
      .on("mousemove", (e, d: any) => {
        const r: CompanyRow = d.data.row;
        showTip(tipRef.current, e, [{ text: r.name, bold: true }, `${r.as_victim} as victim, ${r.as_vendor} as vendor`,
          r.usd ? `${usd(r.usd)} reported` : "", `relevance up to ${r.relevance}`]);
      })
      .on("mouseleave", () => hideTip(tipRef.current));
    leaf.append("rect")
      .attr("x", (d: any) => d.x0).attr("y", (d: any) => d.y0).attr("width", (d: any) => d.x1 - d.x0).attr("height", (d: any) => d.y1 - d.y0)
      .attr("fill", (d: any) => color(d.data.row.relevance))
      .attr("stroke", (d: any) => (d.data.row.key === picked ? cssVar("--text") : "none")).attr("stroke-width", 2);
    leaf.append("text").attr("x", (d: any) => d.x0 + 4).attr("y", (d: any) => d.y0 + 13)
      .text((d: any) => (d.x1 - d.x0 > 46 && d.y1 - d.y0 > 16 ? d.data.name : ""))
      .attr("font-size", 11).style("fill", (d: any) => inkOn(color(d.data.row.relevance)))
      .each(function (d: any) {
        const self = this as SVGTextElement;
        const max = d.x1 - d.x0 - 8;
        let t = self.textContent ?? "";
        while (t.length > 3 && self.getComputedTextLength() > max) { t = t.slice(0, -2); self.textContent = `${t}...`; }
      });
  }, [shown, size, picked, mode]);

  const value = (r: CompanyRow) => (size === "usd" ? r.usd : size === "relevance" ? r.relevance : r.as_victim + r.as_vendor);
  const table = useMemo(() => [...shown].sort((a, b) => value(b) - value(a) || b.relevance - a.relevance).slice(0, 400), [shown, size]);

  const row = rows.find((r) => r.key === picked) ?? null;
  return (
    <div className="view full treemap-wrap">
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, padding: "12px 16px" }}>
        <div className="toolbar">
          <span className="label">size by</span>
          <span className="seg">{SIZES.map(([k, l]) => <button key={k} className={`btn ${size === k ? "on" : ""}`} onClick={() => setSize(k)}>{l}</button>)}</span>
          <span className="label">as</span>
          <span className="seg">
            {(["victim", "vendor", "all"] as const).map((k) => <button key={k} className={`btn ${role === k ? "on" : ""}`} onClick={() => setRole(k)}>{k[0].toUpperCase() + k.slice(1)}</button>)}
          </span>
          <span className="seg">
            {(["map", "table"] as const).map((k) => <button key={k} className={`btn ${mode === k ? "on" : ""}`} onClick={() => setMode(k)}>{k[0].toUpperCase() + k.slice(1)}</button>)}
          </span>
          <span className="label">{shown.length} companies{mode === "map" ? ", by sector" : ""}</span>
          {mode === "map" && (
            <span className="legend"><span className="ramp" title={BAND_LABELS.join(" · ")}>relevance to us
              <span>{[1, 2, 3, 4, 5].map((k) => <i key={k} style={{ background: `var(--seq-${k})` }} />)}</span>higher</span></span>
          )}
        </div>
        {failed && <div className="empty">The companies could not be read.</div>}
        {!failed && shown.length === 0 && <div className="empty">No company named as {role === "all" ? "victim or vendor" : role} in this window.</div>}
        {mode === "map" ? <svg ref={ref} role="img" aria-label="Companies by sector" style={{ flex: 1, width: "100%", display: "block" }} /> : (
          <div style={{ flex: 1, overflow: "auto" }}>
            <table className="grid">
              <thead><tr><th>Company</th><th>Sector</th><th>Country</th><th className="num">Hit</th><th className="num">Vendor</th>
                <th className="num">Reported</th><th className="num">Relevance</th></tr></thead>
              <tbody>
                {table.map((r) => (
                  <tr key={r.key} className={`click ${r.key === picked ? "sel" : ""}`} onClick={() => setPicked(r.key)}>
                    <td><b>{r.name}</b></td><td className="small">{r.sector}</td><td className="small">{r.country ?? ""}</td>
                    <td className="num">{r.as_victim || ""}</td><td className="num">{r.as_vendor || ""}</td>
                    <td className="num">{r.usd ? usd(r.usd) : ""}</td><td className="num">{r.relevance}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {size === "usd" && <div className="note" style={{ marginTop: 6 }}>Only companies with a reported amount. Most incidents never state one.</div>}
      </div>
      {row && <CompanyDetail row={row} onSelect={onSelect} onPick={(name) => {
        const hit = rows.find((r) => r.name === name);
        if (hit) setPicked(hit.key);
      }} />}
      <div ref={tipRef} className="chart-tip" style={{ display: "none" }} />
    </div>
  );
}

function CompanyDetail({ row, onSelect, onPick }: { row: CompanyRow; onSelect: (id: string) => void; onPick: (name: string) => void }) {
  const wd = row.wikidata;
  return (
    <aside className="company-detail">
      <h2>{row.name}</h2>
      <div className="muted small">{[row.sector, row.country].filter(Boolean).join(" · ")}</div>
      {wd && (
        <p className="small">
          {wd.description} <a href={safeUrl(wd.url)} target="_blank" rel="noreferrer">Wikidata</a>
          {wd.employees ? <span className="faint"> · {count(wd.employees)} staff</span> : null}
          {wd.exchange.length > 0 && <span className="faint"> · listed on {wd.exchange.join(", ")}</span>}
        </p>
      )}
      <div className="small">
        {row.as_victim} incident{row.as_victim === 1 ? "" : "s"} as victim, {row.as_vendor} as vendor
        {row.usd > 0 && <> · <b>{usd(row.usd)}</b> reported</>}
        {row.records > 0 && <> · {count(row.records)} records</>}
      </div>
      <h3>Incidents</h3>
      <ul className="items">
        {row.incidents.map((i) => (
          <li key={i.id + i.role}><a href="#" onClick={(e) => { e.preventDefault(); onSelect(i.id); }}>{i.title}</a>
            <div className="faint small">{i.role} · relevance {i.relevance}{i.usd ? ` · ${usd(i.usd)}` : ""} · {ago(i.last_seen)}</div></li>
        ))}
      </ul>
      <h3>Related companies</h3>
      {row.related.length === 0 && <p className="faint small">{wd ? "Wikidata lists no parent or subsidiaries." : "Not found on Wikidata (yet: a few are looked up each round)."}</p>}
      <ul className="items">
        {row.related.map((r) => (
          <li key={r.name + r.how}>
            {r.in_news ? <a href="#" onClick={(e) => { e.preventDefault(); onPick(r.name); }}>{r.name}</a> : r.name}
            <span className="faint small"> · {r.how}{r.in_news ? ", in the news too" : ""}</span>
          </li>
        ))}
      </ul>
    </aside>
  );
}
