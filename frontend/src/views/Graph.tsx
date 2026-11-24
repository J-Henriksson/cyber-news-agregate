import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { api, ago, count, cssVar, safeUrl, SNAPSHOT, usd, type GraphData, type GraphNode, type Lens, type NodeDetail } from "../api";
import { layoutPacked, layoutUs, named, setRadii, short, type Mark } from "../lib/graphLayout";
import { BAND_LABELS, bandColor, inkOn, shapePath, SHAPES, textWidth } from "../lib/viz";
import { hideTip, showTip, type TipLine } from "../lib/tip";
import type { ViewProps } from "../App";

const LENSES: { key: Lens; name: string; asks: string; says: string; line: string }[] = [
  { key: "us", name: "Us", asks: "Why does it matter to us?",
    says: "Each incident hangs on the parts of the profile that gave it points.", line: "a line: points given" },
  { key: "links", name: "Links", asks: "What is connected?",
    says: "Incidents, and only what at least two of them share: a company, a group, a flaw.", line: "a line: named in the incident" },
  { key: "companies", name: "Companies", asks: "Which companies are tied together?",
    says: "Hit in the same incident, hit through another's product, or owned by one another.",
    line: "a line: hit together, hit through, or owns" },
  { key: "groups", name: "Groups", asks: "Who hits whom?",
    says: "Each group and the organisations it hit; one hit by two groups sits between them.", line: "a line: hit" },
];
const SIZES = [["relevance", "Relevance"], ["money", "Money"], ["reports", "Reports"]] as const;
type SizeBy = (typeof SIZES)[number][0];
/** Kinds the legend can switch off, by the shape that draws them. */
const TOGGLES: { name: string; kinds: string[] }[] = [
  { name: "organisation", kinds: ["company", "government"] },
  { name: "group", kinds: ["actor", "person"] },
  { name: "flaw (CVE)", kinds: ["cve"] },
  { name: "product", kinds: ["product"] },
];
const OURS: Record<string, string> = { us: "us", tool: "a tool we build on", supplier: "a supplier", stack: "software we run", peer: "a peer", actor: "a group we watch" };

function stored(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

interface Scene {
  lens: Lens;
  transform: d3.ZoomTransform;
  zoom: d3.ZoomBehavior<SVGSVGElement, unknown>;
  hover: string | null;
  relabel: () => void;
  highlight: () => void;
  fit: (animate: boolean) => void;
}

export default function Graph({ days, since, q, tick, selected, onSelect, fresh, desk }: ViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const scene = useRef<Scene | null>(null);
  // Where each lens's nodes last stood (a change glides from there), and where the reader dropped one.
  const last = useRef(new Map<string, Map<string, { x: number; y: number }>>());
  const pins = useRef(new Map<string, Map<string, { x: number; y: number }>>());
  const drawn = useRef<Lens | null>(null);
  // Read by the drawing without drawing again when they change.
  const live = useRef({ focus: null as string | null, q });

  const [lens, setLens] = useState<Lens>(() => (LENSES.find((l) => l.key === stored("radar.lens"))?.key ?? "us"));
  const [sizeBy, setSizeBy] = useState<SizeBy>("relevance");
  const [minRel, setMinRel] = useState(10);
  const [limit, setLimit] = useState(120);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [table, setTable] = useState(false);
  const [data, setData] = useState<GraphData | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [theme, setTheme] = useState(0);
  live.current = { focus, q };

  useEffect(() => {
    try { localStorage.setItem("radar.lens", lens); } catch { /* not remembered */ }
    setFocus(null);
  }, [lens]);

  // The colours are resolved when drawn: draw again when the system changes its theme.
  useEffect(() => {
    const m = window.matchMedia("(prefers-color-scheme: light)");
    const on = () => setTheme((n) => n + 1);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);

  useEffect(() => {
    setBusy(true);
    let gone = false;
    api.graph(lens, days, lens === "us" || lens === "links" ? minRel : 0, limit, desk, since)
      .then((g) => { if (!gone) { setData(g); setFailed(false); } })
      .catch(() => { if (!gone) setFailed(true); })
      .finally(() => { if (!gone) setBusy(false); });
    return () => { gone = true; };
  }, [lens, days, since, minRel, limit, desk, tick]);

  // What is drawn: the lens's nodes less the kinds switched off, each with its radius.
  const shown = useMemo(() => {
    if (!data) return null;
    const off = new Set(data.nodes.filter((n) => hidden.has(n.kind)).map((n) => n.id));
    const kept = data.links.filter((l) => !off.has(l.source) && !off.has(l.target));
    const linked = new Set(kept.flatMap((l) => [l.source, l.target]));
    // An incident left with nothing to hang on leaves with what it hung on (a company alone stays in its sector).
    const nodes = data.nodes.filter((n) => !off.has(n.id) && (n.kind !== "incident" || linked.has(n.id)))
      .map((n) => ({ ...n, x: 0, y: 0, r: 5 }));
    const ids = new Set(nodes.map((n) => n.id));
    setRadii(nodes, sizeBy);
    return { ...data, nodes, links: kept.filter((l) => ids.has(l.source) && ids.has(l.target)) };
  }, [data, hidden, sizeBy]);

  useEffect(() => {
    const el = svgRef.current;
    if (!shown || !el || table) return;
    const svg = d3.select(el);
    svg.selectAll("*").remove();
    const { width, height } = el.getBoundingClientRect();
    if (width < 40 || height < 40) return;
    const laid = shown.lens === "us" ? layoutUs(shown, Math.max(1, Math.min(1.5, width / height)))
      : layoutPacked(shown, Math.max(1, Math.min(2.2, width / height)));
    const nodes = laid.nodes;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const lensPins = pins.current.get(shown.lens);
    for (const n of nodes) {
      const pin = lensPins?.get(n.id);
      if (pin) { n.x = pin.x; n.y = pin.y; }
    }
    const neighbours = new Map<string, Set<string>>();
    for (const l of laid.links) {
      if (!neighbours.has(l.source)) neighbours.set(l.source, new Set());
      if (!neighbours.has(l.target)) neighbours.set(l.target, new Set());
      neighbours.get(l.source)!.add(l.target);
      neighbours.get(l.target)!.add(l.source);
    }

    const bg = cssVar("--bg"), neutral = cssVar("--g-node"), ours = cssVar("--g-ours"), group = cssVar("--g-group");
    const edge = cssVar("--g-edge"), ink = cssVar("--text"), accent = cssVar("--accent"), mutedInk = cssVar("--muted");
    const hollow = (n: GraphNode) => !!n.outside || (n.kind === "cve" && !n.kev);
    const fill = (n: GraphNode) => hollow(n) ? bg
      : n.kind === "us" || n.kind === "facet" ? ours
        : n.kind === "actor" || n.kind === "person" ? group
          : n.kind === "incident" || n.kind === "company" || n.kind === "government" ? bandColor(n.relevance) : neutral;
    // A ring says whose a node is: open in the panel, in our profile, or new since the page opened.
    const ringOf = (n: GraphNode) => n.id === `i:${selected}` ? ink
      : n.ours && shown.lens !== "us" && n.kind !== "us" ? ours
        : n.kind === "incident" && fresh.has(n.id.slice(2)) ? accent : null;

    const root = svg.append("g");
    const gLink = root.append("g").attr("fill", "none");
    const gRing = root.append("g").attr("fill", "none");
    const gNode = root.append("g");
    const gMark = root.append("g");
    const gLabel = root.append("g");
    const gHit = root.append("g");

    const link = gLink.selectAll("line").data(laid.links).join("line")
      .attr("stroke", edge)
      // Hairlines: the marks are the data, the lines only say which belong together.
      .attr("stroke-width", (l) => (l.kind === "hit" || l.kind === "together" || l.kind === "through" ? Math.min(2.2, 0.8 + 0.4 * l.weight) : 1));
    const ring = gRing.selectAll("path").data(nodes.filter((n) => ringOf(n))).join("path")
      .attr("d", (n) => shapePath(n.kind, n.r + 3.6)).attr("stroke", (n) => ringOf(n)!).attr("stroke-width", 1.6);
    const node = gNode.selectAll("path").data(nodes).join("path")
      .attr("d", (n) => shapePath(n.kind, n.r))
      .attr("fill", fill)
      // The surface's own colour around each mark keeps touching marks apart; a hollow one is drawn by its outline.
      .attr("stroke", (n) => (hollow(n) ? neutral : bg)).attr("stroke-width", (n) => (hollow(n) ? 1.4 : 1.5));
    const mark = gMark.selectAll("text").data(laid.marks).join("text")
      .text((m: Mark) => m.text).attr("text-anchor", (m: Mark) => m.anchor)
      .style("fill", cssVar("--faint")).style("font-weight", 600).style("letter-spacing", "0.08em").style("pointer-events", "none");
    const label = gLabel.selectAll("text").data(nodes.filter((n) => n.kind !== "us")).join("text")
      .text((n) => short(n))
      .attr("paint-order", "stroke").attr("stroke", bg).attr("stroke-linejoin", "round")
      .style("fill", (n) => (n.kind === "incident" ? mutedInk : ink)).style("pointer-events", "none");
    const us = byId.get("us");
    const usLabel = us ? gLabel.append("text").text(us.label.length > 9 ? `${us.label.slice(0, 8)}.` : us.label).attr("text-anchor", "middle")
      .style("fill", inkOn(ours)).style("font-weight", 600).style("pointer-events", "none") : null;
    const hit = gHit.selectAll<SVGCircleElement, GraphNode>("circle").data(nodes).join("circle")
      .attr("r", (n) => Math.max(n.r + 4, 12)).attr("fill", "transparent").style("cursor", "pointer");

    // Where a label is tried first: beside a mark, on the side away from the middle in the "us" lens;
    // above or below for a part of the profile at the top or bottom of its ring.
    type Spot = "right" | "left" | "below" | "above" | "br" | "bl" | "ar" | "al";
    const spots = (n: GraphNode): Spot[] => {
      if (shown.lens !== "us") return ["right", "left", "below", "above", "br", "bl", "ar", "al"];
      const side: Spot = n.x < -1 ? "left" : "right", other: Spot = side === "left" ? "right" : "left";
      const down = n.y > 0;
      const out: Spot[] = side === "left" ? (down ? ["bl", "al"] : ["al", "bl"]) : (down ? ["br", "ar"] : ["ar", "br"]);
      if (n.kind === "facet" && Math.abs(n.y) > Math.abs(n.x) * 1.4) return down ? ["below", ...out, side, other] : ["above", ...out, side, other];
      return [side, ...out, down ? "below" : "above", other];
    };
    const spot = new Map<string, Spot>();
    const place = () => {
      link.attr("x1", (l) => byId.get(l.source)!.x).attr("y1", (l) => byId.get(l.source)!.y)
        .attr("x2", (l) => byId.get(l.target)!.x).attr("y2", (l) => byId.get(l.target)!.y);
      node.attr("transform", (n) => `translate(${n.x},${n.y})`);
      ring.attr("transform", (n) => `translate(${n.x},${n.y})`);
      hit.attr("cx", (n) => n.x).attr("cy", (n) => n.y);
      mark.attr("x", (m: Mark) => m.x).attr("y", (m: Mark) => m.y);
    };

    const sc: Scene = {
      lens: shown.lens,
      transform: scene.current?.lens === shown.lens ? scene.current.transform : d3.zoomIdentity,
      zoom: d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.12, 5]),
      hover: null,
      relabel: () => undefined, highlight: () => undefined, fit: () => undefined,
    };

    const active = (): Set<string> | null => {
      const at = sc.hover ?? live.current.focus;
      if (at && byId.has(at)) {
        const near = new Set([at, ...(neighbours.get(at) ?? [])]);
        // In the "us" lens an incident's parts lead back to us.
        if (shown.lens === "us" && near.size > 1) near.add("us");
        return near;
      }
      const ql = live.current.q.trim().toLowerCase();
      if (ql) {
        const found = nodes.filter((n) => n.label.toLowerCase().includes(ql)).map((n) => n.id);
        if (found.length) return new Set(found.flatMap((id) => [id, ...(neighbours.get(id) ?? [])]));
      }
      return null;
    };

    // Labels keep their size on screen at any zoom, and only those that do not run into a weightier one are shown.
    sc.relabel = () => {
      const t = sc.transform, k = t.k;
      const near = active();
      const weight = (n: GraphNode) => {
        if (near?.has(n.id)) return 2000 + n.relevance;
        if (near) return -1;
        if (n.kind === "facet") return 900 + (n.points ?? 0) / 50;
        if (n.kind === "incident") return shown.lens === "companies" ? 120 + n.relevance : n.relevance >= 40 ? n.relevance - 25 : -1;
        // The groups, then what ties most together, then what is ours.
        if (n.kind === "cve") return 60 + n.relevance / 2 + (n.kev ? 30 : 0);
        return 200 + n.relevance + n.incidents * 6 + (n.ours ? 80 : 0) + (n.kind === "actor" || n.kind === "person" ? 300 : 0);
      };
      // Every mark is taken first, so a label does not lie on one; then the headings; then the labels by weight.
      // The name of what ties others together is the one a reader looks for: with no free place left,
      // it may lie over an incident's dot (its halo keeps it legible), never over another name or its like.
      type Box = [number, number, number, number];
      const markBox = (n: GraphNode): Box => {
        const sx = n.x * k + t.x, sy = n.y * k + t.y, r = n.r * k;
        return [sx - r, sy - r, sx + r, sy + r];
      };
      const boxes: Box[] = nodes.filter(named).map(markBox);
      const dots: Box[] = nodes.filter((n) => !named(n)).map(markBox);
      const over = (list: Box[], box: Box) => list.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]);
      const taken = (box: Box, strict = true) => over(boxes, box) || (strict && over(dots, box));
      const headings = new Set<Mark>();
      if (!near) {
        for (const m of laid.marks) {
          const w = textWidth(m.text, 10.5) * 1.12 + 6;
          const sx = m.x * k + t.x, sy = m.y * k + t.y;
          const x0 = m.anchor === "start" ? sx : m.anchor === "end" ? sx - w : sx - w / 2;
          const box: Box = [x0, sy - 10, x0 + w, sy + 4];
          if (taken(box)) continue;
          boxes.push(box);
          headings.add(m);
        }
      }
      const on = new Set<string>();
      for (const n of nodes.filter((x) => x.kind !== "us" && weight(x) >= 0).sort((a, b) => weight(b) - weight(a))) {
        const w = textWidth(short(n)) + 6;
        const sx = n.x * k + t.x, sy = n.y * k + t.y, r = n.r * k;
        const tries: [Spot, boolean][] = [...spots(n).map((sp): [Spot, boolean] => [sp, true]),
          ...(named(n) || near?.has(n.id) || shown.lens === "companies" ? spots(n).map((sp): [Spot, boolean] => [sp, false]) : [])];
        for (const [where, strict] of tries) {
          // Beside the mark, centred under or over it, or under or over it running to one side.
          const low = where === "below" || where === "br" || where === "bl";
          const x0 = where === "right" ? sx + r + 5 : where === "left" ? sx - r - 5 - w
            : where === "below" || where === "above" ? sx - w / 2 : where === "br" || where === "ar" ? sx - r : sx + r - w;
          const y0 = where === "right" || where === "left" ? sy - 8 : low ? sy + r + 3 : sy - r - 18;
          const box: Box = [x0, y0, x0 + w, y0 + 15];
          if (box[2] < 0 || box[0] > width || box[3] < 0 || box[1] > height || taken(box, strict)) continue;
          boxes.push(box);
          on.add(n.id);
          spot.set(n.id, where);
          break;
        }
      }
      const at = (n: GraphNode) => spot.get(n.id) ?? "right";
      const starts = (sp: Spot) => sp === "right" || sp === "br" || sp === "ar", ends = (sp: Spot) => sp === "left" || sp === "bl" || sp === "al";
      label.attr("display", (n) => (on.has(n.id) ? null : "none"))
        .attr("x", (n) => n.x + (at(n) === "right" ? n.r + 5 / k : at(n) === "left" ? -n.r - 5 / k
          : at(n) === "br" || at(n) === "ar" ? -n.r + 3 / k : at(n) === "bl" || at(n) === "al" ? n.r - 3 / k : 0))
        .attr("y", (n) => n.y + (at(n) === "right" || at(n) === "left" ? 4 / k
          : at(n) === "below" || at(n) === "br" || at(n) === "bl" ? n.r + 14 / k : -n.r - 6 / k))
        .attr("text-anchor", (n) => (starts(at(n)) ? "start" : ends(at(n)) ? "end" : "middle"))
        .style("font-size", `${11 / k}px`).attr("stroke-width", 3 / k);
      mark.style("font-size", `${10.5 / k}px`).attr("display", (m: Mark) => (headings.has(m) ? null : "none"));
      // What the pointer can catch stays a fingertip wide however far out the view is.
      hit.attr("r", (n) => Math.max(n.r + 4, 12 / k));
      usLabel?.attr("x", us!.x).attr("y", us!.y + 4 / k).style("font-size", `${12 / k}px`);
    };

    sc.highlight = () => {
      const near = active();
      node.attr("opacity", (n) => (!near || near.has(n.id) ? 1 : 0.16));
      ring.attr("opacity", (n) => (!near || near.has(n.id) ? 1 : 0.16));
      link.attr("stroke-opacity", (l) => (!near ? (shown.lens === "us" ? 0.5 : 0.8) : near.has(l.source) && near.has(l.target) ? 1 : 0.06))
        .attr("stroke", (l) => (near && near.has(l.source) && near.has(l.target) ? mutedInk : edge));
      sc.relabel();
    };

    sc.fit = (animate: boolean) => {
      if (!nodes.length) return;
      const padX = shown.lens === "us" ? 230 : 120, padY = 48;
      const x0 = d3.min(nodes, (n) => n.x - n.r)!, x1 = d3.max(nodes, (n) => n.x + n.r)!;
      const y0 = d3.min(nodes, (n) => n.y - n.r)!, y1 = d3.max(nodes, (n) => n.y + n.r)!;
      const k = Math.max(0.12, Math.min(1.9, (width - 2 * padX) / Math.max(1, x1 - x0), (height - 2 * padY) / Math.max(1, y1 - y0)));
      const t = d3.zoomIdentity.translate(width / 2 - ((x0 + x1) / 2) * k, height / 2 - ((y0 + y1) / 2) * k).scale(k);
      if (animate) svg.transition().duration(350).call(sc.zoom.transform, t);
      else svg.call(sc.zoom.transform, t);
    };

    let frame = 0;
    sc.zoom.on("zoom", (e) => {
      sc.transform = e.transform;
      root.attr("transform", e.transform.toString());
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(sc.relabel);
    });
    svg.call(sc.zoom).on("dblclick.zoom", null).on("click", () => setFocus(null));

    hit
      .on("pointermove", (e: PointerEvent, n) => {
        if (sc.hover !== n.id) { sc.hover = n.id; sc.highlight(); }
        showTip(tipRef.current, e, tipLines(n));
      })
      .on("pointerleave", () => { sc.hover = null; sc.highlight(); hideTip(tipRef.current); })
      .on("click", (e: MouseEvent, n) => {
        e.stopPropagation();
        if (n.kind === "incident") { onSelect(n.id.slice(2)); setFocus(n.id); } else setFocus((f) => (f === n.id ? null : n.id));
      })
      .call(d3.drag<SVGCircleElement, GraphNode>()
        .on("drag", (e, n) => {
          n.x = e.x; n.y = e.y;
          if (!pins.current.has(sc.lens)) pins.current.set(sc.lens, new Map());
          pins.current.get(sc.lens)!.set(n.id, { x: n.x, y: n.y });
          last.current.get(sc.lens)?.set(n.id, { x: n.x, y: n.y });
          place(); sc.relabel(); hideTip(tipRef.current);
        }));

    // A change glides from where things stood; what is new appears in its place.
    const before = last.current.get(shown.lens);
    const to = nodes.map((n) => ({ x: n.x, y: n.y }));
    const from = nodes.map((n, i) => before?.get(n.id) ?? to[i]);
    const firstOfLens = drawn.current !== shown.lens;
    const moving = !firstOfLens && !!before && from.some((p, i) => Math.hypot(p.x - to[i].x, p.y - to[i].y) > 1);
    last.current.set(shown.lens, new Map(nodes.map((n, i) => [n.id, to[i]])));
    scene.current = sc;
    drawn.current = shown.lens;
    if (firstOfLens) sc.fit(false); else svg.call(sc.zoom.transform, sc.transform);
    let timer: d3.Timer | null = null;
    if (moving) {
      timer = d3.timer((elapsed) => {
        const e = d3.easeCubicOut(Math.min(1, elapsed / 420));
        nodes.forEach((n, i) => { n.x = from[i].x + (to[i].x - from[i].x) * e; n.y = from[i].y + (to[i].y - from[i].y) * e; });
        place(); sc.relabel();
        if (elapsed >= 420) timer?.stop();
      });
    } else place();
    sc.highlight();

    const resized = new ResizeObserver(() => { if (scene.current === sc) sc.relabel(); });
    resized.observe(el);
    return () => { timer?.stop(); cancelAnimationFrame(frame); resized.disconnect(); };
  }, [shown, table, theme, selected, fresh, onSelect]);

  // Focus and search only relight what is drawn.
  useEffect(() => { scene.current?.highlight(); }, [focus, q]);

  useEffect(() => {
    if (!focus || focus.startsWith("i:")) { setDetail(null); return; }
    let gone = false;
    api.node(focus, days, desk, since).then((d) => { if (!gone) setDetail(d); }).catch(() => { if (!gone) setDetail(null); });
    return () => { gone = true; };
  }, [focus, days, desk, since, tick]);

  const toggle = useCallback((kinds: string[]) => setHidden((h) => {
    const next = new Set(h);
    const off = kinds.every((k) => next.has(k));
    for (const k of kinds) { if (off) next.delete(k); else next.add(k); }
    return next;
  }), []);

  const meta = LENSES.find((l) => l.key === lens)!;
  const kinds = new Set(data?.nodes.map((n) => n.kind));
  const nIncidents = shown?.nodes.filter((n) => n.kind === "incident").length ?? 0;
  const nOthers = (shown?.nodes.length ?? 0) - nIncidents;
  const counts = !data || !shown ? "" : lens === "us" ? `${nIncidents} incidents on ${shown.nodes.filter((n) => n.kind === "facet").length} parts of the profile.`
    : lens === "links" ? `${nIncidents} incidents share something; ${data.alone} of the top ${data.of} share nothing (the feed has them).`
      : lens === "companies" ? `${nOthers} companies; ${data.alone} more are tied to no other and matter less to us.`
        : `${shown.nodes.filter((n) => n.kind === "actor" || n.kind === "person").length} groups, ${shown.nodes.filter((n) => n.kind === "company" || n.kind === "government").length} organisations hit.`;
  const rows = useMemo(() => {
    const value = (n: GraphNode) => (sizeBy === "money" ? n.usd : sizeBy === "reports" ? n.incidents : n.kind === "facet" ? (n.points ?? 0) : n.relevance);
    return (shown?.nodes ?? []).filter((n) => n.kind !== "incident" && n.kind !== "us").sort((a, b) => value(b) - value(a) || b.incidents - a.incidents);
  }, [shown, sizeBy]);
  const empty = !!shown && shown.nodes.filter((n) => n.kind !== "us").length === 0;

  return (
    <div className={`view full ${busy ? "busy" : ""}`}>
      <div className="graph-bar">
        <div className="toolbar">
          <span className="seg" role="group" aria-label="Lens">
            {LENSES.map((l) => <button key={l.key} className={`btn ${lens === l.key ? "on" : ""}`} aria-pressed={lens === l.key} onClick={() => setLens(l.key)}>{l.name}</button>)}
          </span>
          <span className="label">size by</span>
          <span className="seg" role="group" aria-label="Size by">
            {SIZES.map(([k, name]) => <button key={k} className={`btn ${sizeBy === k ? "on" : ""}`} aria-pressed={sizeBy === k} onClick={() => setSizeBy(k)}>{name}</button>)}
          </span>
          {!SNAPSHOT && (lens === "us" || lens === "links") && (
            <>
              <span className="label">relevance at least</span>
              <input type="range" min={0} max={80} step={5} value={minRel} aria-label="Least relevance" onChange={(e) => setMinRel(Number(e.target.value))} />
              <span className="mono small">{minRel}</span>
            </>
          )}
          {!SNAPSHOT && (
            <select value={limit} aria-label="How many" onChange={(e) => setLimit(Number(e.target.value))}>
              {[60, 120, 200, 300].map((n) => <option key={n} value={n}>up to {n}</option>)}
            </select>
          )}
          <span className="spacer" />
          <span className="seg" role="group" aria-label="Show as">
            <button className={`btn ${!table ? "on" : ""}`} aria-pressed={!table} onClick={() => setTable(false)}>Graph</button>
            <button className={`btn ${table ? "on" : ""}`} aria-pressed={table} onClick={() => setTable(true)}>Table</button>
          </span>
          {!table && <button className="btn" onClick={() => scene.current?.fit(true)} title="Bring everything into view">Fit</button>}
        </div>
        <div className="graph-q"><b>{meta.asks}</b> {meta.says} <span className="faint">{counts}</span></div>
      </div>
      <div className="graph-stage">
        {failed && <div className="empty over">The graph could not be read.</div>}
        {!failed && empty && <div className="empty over">{lens === "us" ? "Nothing in this window touches the profile at this relevance."
          : lens === "links" ? "Nothing at this relevance shares a company, a group or a flaw with anything else. Lower the bar."
            : lens === "companies" ? "No company is tied to another in this window." : "No group is named with the organisations it hit in this window."}</div>}
        {table ? (
          <div className="graph-table">
            <table className="grid">
              <thead><tr><th>Name</th><th>What</th><th className="num">Incidents</th><th className="num">Relevance</th><th className="num">Reported</th></tr></thead>
              <tbody>
                {rows.map((n) => (
                  <tr key={n.id} className={`click ${focus === n.id ? "sel" : ""}`} onClick={() => setFocus(n.id)}>
                    <td><b>{n.label}</b>{n.ours && n.kind !== "facet" ? <span className="faint small"> · {OURS[n.ours] ?? n.ours}</span> : null}</td>
                    <td className="small muted">{n.kind === "facet" ? n.sub : [SHAPES[n.kind]?.name ?? n.kind, n.sector, n.country].filter(Boolean).join(" · ")}</td>
                    <td className="num">{n.incidents || ""}</td>
                    <td className="num">{n.kind === "facet" ? `${n.points} pts` : n.relevance}</td>
                    <td className="num">{n.usd ? usd(n.usd) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <svg ref={svgRef} role="img" aria-label={`${meta.asks} ${counts}`} />}
        {detail && <Inspector d={detail} onClose={() => setFocus(null)} onSelect={onSelect} />}
      </div>
      <div className="graph-foot legend">
        {kinds.has("incident") && <span><Glyph kind="incident" color="var(--seq-3)" />incident</span>}
        {kinds.has("facet") && <span><Glyph kind="facet" color="var(--g-ours)" />part of our profile</span>}
        {TOGGLES.filter((t) => t.kinds.some((k) => kinds.has(k))).map((t) => {
          const off = t.kinds.every((k) => hidden.has(k));
          return (
            <button key={t.name} className={`legend-btn ${off ? "off" : ""}`} aria-pressed={!off} onClick={() => toggle(t.kinds)} title={off ? "Show these" : "Hide these"}>
              <Glyph kind={t.kinds[0]} color={t.name === "group" ? "var(--g-group)" : t.name === "organisation" ? "var(--seq-3)" : "var(--g-node)"} />{t.name}
            </button>
          );
        })}
        <span className="ramp" title={BAND_LABELS.join(" · ")}>relevance
          <span>{[1, 2, 3, 4, 5].map((k) => <i key={k} style={{ background: `var(--seq-${k})` }} />)}</span>higher</span>
        {lens !== "us" && <span><Glyph kind="company" color="var(--bg)" stroke="var(--g-ours)" />ring: in our profile</span>}
        {data?.nodes.some((n) => n.outside) && <span><Glyph kind="company" color="var(--bg)" stroke="var(--g-node)" />parent company, not in the news</span>}
        <span className="faint">{meta.line} · hover or click a mark · drag to move it · scroll to zoom</span>
      </div>
      <div ref={tipRef} className="chart-tip" style={{ display: "none" }} />
    </div>
  );
}

/** A node's shape as a small key. */
function Glyph({ kind, color, stroke }: { kind: string; color: string; stroke?: string }) {
  return (
    <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
      <path d={shapePath(kind, 5)} fill={color} stroke={stroke} strokeWidth={stroke ? 1.4 : 0} />
    </svg>
  );
}

function tipLines(n: GraphNode): TipLine[] {
  const many = (k: number, word: string) => `${k} ${word}${k === 1 ? "" : "s"}`;
  if (n.kind === "incident") {
    return [{ text: `${n.relevance} · ${n.label}`, bold: true },
      `${n.category}${n.claim ? ", a claim only" : ""} · ${many(n.reports, "source")} · ${ago(n.last_seen)}`,
      n.usd ? `${usd(n.usd)} reported` : ""];
  }
  if (n.kind === "us") return [{ text: n.label, bold: true }, "us: the profile every incident is scored against"];
  if (n.kind === "facet") return [{ text: n.label, bold: true }, n.sub ?? "", `${many(n.incidents, "incident")}, ${n.points} points in all`];
  if (n.kind === "cve") {
    return [{ text: n.label, bold: true }, n.sub ?? "", n.kev ? "being exploited (CISA KEV)" : "not on CISA's exploited list",
      n.epss != null ? `EPSS ${(n.epss * 100).toFixed(1)}%` : "", many(n.incidents, "incident")];
  }
  const what = n.kind === "actor" || n.kind === "person" ? "group" : SHAPES[n.kind]?.name ?? n.kind;
  return [{ text: n.label, bold: true }, [what, n.sector, n.country].filter(Boolean).join(" · "),
    n.outside ? "parent company (Wikidata): not in the news itself" : `${many(n.incidents, "incident")}, relevance up to ${n.relevance}`,
    n.victims ? `${many(n.victims, "organisation")} hit${n.more ? `, ${n.more} not drawn` : ""}` : "",
    n.usd ? `${usd(n.usd)} reported` : "",
    n.ours ? { text: `in our profile: ${OURS[n.ours] ?? n.ours}`, dim: true } : ""];
}

const ROLE: Record<string, string> = { victim: "hit", attacker: "attacker", vendor: "vendor", flaw: "flaw", mentioned: "named", about: "about" };

/** What stands behind a node: its incidents, and for a company what Wikidata knows. */
function Inspector({ d, onClose, onSelect }: { d: NodeDetail; onClose: () => void; onSelect: (id: string) => void }) {
  const roles = Object.entries(d.roles).map(([k, v]) => `${v} as ${ROLE[k] ?? k}`).join(", ");
  const wd = d.wikidata;
  return (
    <aside className="inspector" aria-label={d.label}>
      <button className="btn x" onClick={onClose} aria-label="Close">×</button>
      <h4>{d.label}</h4>
      <div className="muted small">{[d.kind === "facet" ? null : (SHAPES[d.kind]?.name ?? d.kind), d.sub].filter(Boolean).join(" · ")}</div>
      <div className="facts">
        <span><b>{d.total}</b> incident{d.total === 1 ? "" : "s"}</span>
        {roles && <span>{roles}</span>}
        {d.usd > 0 && <span><b>{usd(d.usd)}</b> reported</span>}
      </div>
      {wd && (
        <p className="small muted" style={{ marginTop: 6 }}>
          {wd.description} <a href={safeUrl(wd.url)} target="_blank" rel="noreferrer">Wikidata</a>
          {wd.parent.length > 0 && <><br />Owned by {wd.parent.join(", ")}</>}
          {wd.subsidiaries.length > 0 && <><br />Owns {wd.subsidiaries.slice(0, 6).join(", ")}{wd.subsidiaries.length > 6 ? ` and ${wd.subsidiaries.length - 6} more` : ""}</>}
          {wd.employees ? <><br />{count(wd.employees)} staff</> : null}
        </p>
      )}
      <h3 style={{ marginTop: 14 }}>Incidents</h3>
      <ul className="items">
        {d.incidents.map((i) => (
          <li key={i.id}>
            <a href="#" onClick={(e) => { e.preventDefault(); onSelect(i.id); }}>{i.title}</a>
            <div className="faint small">
              {i.relevance} · {ROLE[i.role] ?? i.role}{i.usd ? ` · ${usd(i.usd)}` : ""} · {i.sources} source{i.sources === 1 ? "" : "s"} · {ago(i.last_seen)}
            </div>
          </li>
        ))}
      </ul>
      {d.total > d.incidents.length && <p className="faint small">and {d.total - d.incidents.length} more</p>}
    </aside>
  );
}
