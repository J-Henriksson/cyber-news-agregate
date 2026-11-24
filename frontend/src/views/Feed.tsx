import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { api, CATEGORIES, cssVar, nowS, SNAPSHOT, type Brief } from "../api";
import IncidentRow from "../components/IncidentRow";
import { hideTip, showTip } from "../lib/tip";
import { useWidth } from "../lib/useWidth";
import type { ViewProps } from "../App";

const SORTS = [["top", "Top"], ["relevance", "Relevance"], ["recent", "Newest"], ["money", "Money"]] as const;
const SHOWS = [["", "All"], ["starred", "Starred"], ["updated", "Updated"], ["dismissed", "Dismissed"]] as const;
const SORT_HELP: Record<string, string> = {
  top: "Relevance, fading as a story ages: what to read now",
  relevance: "Relevance alone, whatever its age",
  recent: "The newest first",
  money: "The largest reported amount first",
};

export default function Feed({ days, since, q, tick, selected, onSelect, fresh, desk, refresh }: ViewProps) {
  const [rows, setRows] = useState<Brief[]>([]);
  const [cats, setCats] = useState<Record<string, number>>({});
  const [total, setTotal] = useState(0);
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("top");
  const [show, setShow] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const listRef = useRef<HTMLDivElement>(null);

  const filters = useMemo(() => ({
    days, since: since !== undefined ? Math.floor(since) : undefined, q, category, sort, desk, show,
    kinds: confirmed ? "news,advisory,filing,breach,crypto,vuln" : undefined,
  }), [days, since, q, category, sort, desk, show, confirmed]);

  useEffect(() => {
    setLoading(true);
    api.feed({ ...filters, limit: 300 })
      .then((r) => { setRows(r.incidents); setCats(r.categories); setTotal(r.total); setFailed(false); })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  }, [filters, tick]);

  // Keys: j and k move through the list, Enter opens, s stars, x dismisses.
  const state = useRef({ rows, cursor, onSelect, refresh });
  state.current = { rows, cursor, onSelect, refresh };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const { rows, cursor, onSelect, refresh } = state.current;
      const at = rows[cursor];
      if (e.key === "j" || e.key === "k") {
        const next = Math.max(0, Math.min(rows.length - 1, cursor + (e.key === "j" ? 1 : -1)));
        setCursor(next);
        listRef.current?.querySelector(`[data-id="${rows[next]?.id}"]`)?.scrollIntoView({ block: "nearest" });
      } else if ((e.key === "Enter" || e.key === "o") && at) onSelect(at.id);
      else if (e.key === "s" && at && !SNAPSHOT) api.setState(at.id, { starred: !at.state.starred }).then(refresh);
      else if (e.key === "x" && at && !SNAPSHOT) api.setState(at.id, { dismissed: !at.state.dismissed }).then(refresh);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const empty = show === "starred" ? "Nothing starred in this window." : show === "updated" ? "Nothing you opened has been told again."
    : show === "dismissed" ? "Nothing dismissed in this window."
      : `Nothing ${since !== undefined ? "today" : "in this window"} yet.${SNAPSHOT ? "" : " The sources are read every 15 to 60 minutes."}`;

  return (
    <div className={`view ${loading ? "busy" : ""}`}>
      <Scatter rows={rows} days={days} since={since} selected={selected} fresh={fresh} onSelect={onSelect} />
      <div className="toolbar">
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Kind of incident">
          <option value="">All kinds ({Object.values(cats).reduce((a, b) => a + b, 0)})</option>
          {CATEGORIES.filter((c) => cats[c]).map((c) => <option key={c} value={c}>{c} ({cats[c]})</option>)}
        </select>
        <span className="seg" role="group" aria-label="Order">
          {SORTS.map(([k, name]) => <button key={k} className={`btn ${sort === k ? "on" : ""}`} title={SORT_HELP[k]} onClick={() => setSort(k)}>{name}</button>)}
        </span>
        {!SNAPSHOT && (
          <span className="seg" role="group" aria-label="Show">
            {SHOWS.map(([k, name]) => <button key={k} className={`btn ${show === k ? "on" : ""}`} onClick={() => setShow(k)}>{name}</button>)}
          </span>
        )}
        <label className="label"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> leave out what is only claimed</label>
        <span className="label">{total} incident{total === 1 ? "" : "s"}{total > rows.length ? `, top ${rows.length} shown` : ""}</span>
        <span className="spacer" />
        {!SNAPSHOT && <a className="btn" href={api.exportUrl("csv", filters)} download>CSV</a>}
        {!SNAPSHOT && <a className="btn" href={api.exportUrl("json", filters)} download>JSON</a>}
      </div>
      {failed && <div className="empty">The feed could not be read. It is tried again when the backend answers.</div>}
      {!loading && !failed && rows.length === 0 && <div className="empty">{empty}</div>}
      <div ref={listRef} className="rows">
        {rows.map((r, i) => (
          <IncidentRow key={r.id} r={r} on={r.id === selected} cursor={i === cursor} isNew={fresh.has(r.id)} onSelect={onSelect} refresh={refresh} />
        ))}
      </div>
    </div>
  );
}

/** Every incident of the window: when (x) against how much it matters (y),
 *  sized by how many sources tell it. One hue: the list below says what each
 *  is, and what is open or new stands out. The pointer only has to be nearest. */
function Scatter({ rows, days, since, selected, fresh, onSelect }: {
  rows: Brief[]; days: number; since?: number; selected: string | null; fresh: Map<string, unknown>; onSelect: (id: string) => void;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap), height = 132, m = { l: 34, r: 12, t: 10, b: 20 };
  const data = useMemo(() => rows.slice(0, 300), [rows]);

  useEffect(() => {
    const svg = d3.select(ref.current!);
    svg.selectAll("*").remove();
    const now = nowS();
    const start = since ?? now - days * 86400;
    const x = d3.scaleTime().domain([new Date(start * 1000), new Date(now * 1000)]).range([m.l, width - m.r]);
    const y = d3.scaleLinear().domain([0, 100]).range([height - m.b, m.t]);
    const r = d3.scaleSqrt().domain([1, 12]).range([3.5, 9]).clamp(true);
    svg.append("g").attr("class", "axis grid").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).tickValues([0, 50, 100]).tickSize(-(width - m.l - m.r)).tickPadding(6));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${height - m.b})`).call(d3.axisBottom(x).ticks(8).tickSize(3));
    const bg = cssVar("--bg"), series = cssVar("--series"), ink = cssVar("--text"), accent = cssVar("--accent");
    const px = (d: Brief) => x(new Date(Math.max(start, d.last_seen) * 1000)), py = (d: Brief) => y(d.relevance);
    const dots = svg.append("g").selectAll("circle").data(data).join("circle")
      .attr("cx", px).attr("cy", py).attr("r", (d) => r(d.sources.length))
      .attr("fill", (d) => (d.id === selected ? ink : fresh.has(d.id) ? accent : series))
      .attr("fill-opacity", (d) => (d.id === selected || fresh.has(d.id) ? 1 : 0.72))
      .attr("stroke", bg).attr("stroke-width", 1.5);
    // The nearest dot answers, wherever in the plot the pointer is.
    const near = d3.Delaunay.from(data, px, py);
    let at = -1;
    svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", width - m.l - m.r).attr("height", height - m.t - m.b)
      .attr("fill", "transparent").style("cursor", "pointer")
      .on("pointermove", (e: PointerEvent) => {
        if (!data.length) return;
        const [mx, my] = d3.pointer(e);
        const i = near.find(mx, my);
        if (Math.hypot(px(data[i]) - mx, py(data[i]) - my) > 40) { at = -1; dots.attr("stroke", bg); hideTip(tip.current); return; }
        at = i;
        dots.attr("stroke", (_d, k) => (k === i ? ink : bg));
        showTip(tip.current, e, [{ text: `${data[i].relevance} · ${data[i].title}`, bold: true },
          `${data[i].category} · ${data[i].sources.length} source${data[i].sources.length === 1 ? "" : "s"}`]);
      })
      .on("pointerleave", () => { at = -1; dots.attr("stroke", bg); hideTip(tip.current); })
      .on("click", () => { if (at >= 0) onSelect(data[at].id); });
  }, [data, days, since, selected, fresh, onSelect, width]);

  return (
    <div ref={wrap} style={{ marginBottom: 12, maxWidth: 1120 }}>
      <svg ref={ref} viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Incidents by time and relevance"
        style={{ display: "block", maxWidth: "100%" }} />
      <div className="legend" style={{ paddingLeft: 34 }}>
        <span className="faint">Each dot an incident: when it was last told against its relevance; larger, more sources. The list below is the same data.</span>
      </div>
      <div ref={tip} className="chart-tip" style={{ display: "none" }} />
    </div>
  );
}
