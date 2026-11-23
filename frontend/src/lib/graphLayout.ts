import * as d3 from "d3";
import type { GraphData, GraphLink, GraphNode } from "../api";
import { textWidth } from "./viz";

/** Whether a node's name is one the reader looks for first: what ties others together, not an incident or a flaw. */
export const named = (n: GraphNode) => n.kind !== "incident" && n.kind !== "cve";
/** The name as drawn. */
export const short = (n: GraphNode) => (n.label.length > (n.kind === "incident" ? 40 : 30) ? `${n.label.slice(0, n.kind === "incident" ? 38 : 28)}...` : n.label);

/** A heading the layout sets among the nodes: a part of the profile, a sector. */
export interface Mark { x: number; y: number; text: string; anchor: "start" | "middle" | "end" }
export interface Laid { nodes: GraphNode[]; links: GraphLink[]; marks: Mark[] }

/** Radii of the "us" lens's two rings, in the layout's own units. */
const R1 = 250;
const R2 = 470;

/** Our organisation in the middle, the parts of the profile that matched on
 *  the first ring (in the server's order, each with room for its incidents),
 *  and every incident on the outer ring beside the parts it hangs on. The
 *  rings are widened by ``stretch`` to use a wide window. */
export function layoutUs(data: GraphData, stretch: number): Laid {
  const nodes = data.nodes;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const facets = nodes.filter((n) => n.kind === "facet");
  const incidents = nodes.filter((n) => n.kind === "incident");
  const us = byId.get("us");
  if (us) { us.x = 0; us.y = 0; }

  // Each part's share of the circle grows with the incidents on it; a gap parts one kind of part from the next.
  // A name is written level: at the top and bottom of the ring a part needs its name's width of arc,
  // at the sides only a line's height. The shares are settled over a few rounds, since the need depends on the place.
  const base = (f: GraphNode) => 1.4 + Math.sqrt(f.incidents);
  const GAP = 1.2;
  let kinds = 0;
  facets.forEach((f, i) => { if (i === 0 || facets[i - 1].facet !== f.facet) kinds += 1; });
  const gaps = kinds > 1 ? kinds * GAP : 0;
  const share = new Map(facets.map((f) => [f.id, base(f)]));
  const around = Math.PI * R1 * (1 + stretch);
  for (let round = 0; round < 4; round++) {
    const sum = d3.sum(facets, (f) => share.get(f.id)!) + gaps;
    let from = 0;
    const need = new Map<string, number>();
    facets.forEach((f, i) => {
      if (i > 0 && facets[i - 1].facet !== f.facet) from += kinds > 1 ? GAP : 0;
      const a = ((from + share.get(f.id)! / 2) / sum) * 2 * Math.PI - Math.PI / 2;
      from += share.get(f.id)!;
      const arc = Math.abs(Math.sin(a)) * (textWidth(short(f)) + 14) + Math.abs(Math.cos(a)) * 19;
      need.set(f.id, (arc / around) * sum);
    });
    for (const f of facets) share.set(f.id, Math.max(base(f), need.get(f.id)!));
  }
  const span = (f: GraphNode) => share.get(f.id)!;
  const total = d3.sum(facets, span) + gaps;
  const angle = new Map<string, number>();
  const marks: Mark[] = [];
  let at = 0;
  let groupStart = 0;
  const head = (facet: string | undefined, from: number, to: number) => {
    const label = data.facets?.find((x) => x.id === facet)?.label;
    // A heading needs an arc to stand on: a kind with one part or two is named by its parts.
    if (!label || (to - from) / total < 0.09) return;
    const a = ((from + to) / 2 / total) * 2 * Math.PI - Math.PI / 2;
    const c = Math.cos(a);
    marks.push({ x: (R1 - 54) * c * stretch, y: (R1 - 54) * Math.sin(a), text: label.toUpperCase(), anchor: c > 0.35 ? "end" : c < -0.35 ? "start" : "middle" });
  };
  facets.forEach((f, i) => {
    if (i > 0 && facets[i - 1].facet !== f.facet) {
      head(facets[i - 1].facet, groupStart, at);
      at += kinds > 1 ? GAP : 0;
      groupStart = at;
    }
    const a = ((at + span(f) / 2) / total) * 2 * Math.PI - Math.PI / 2;
    angle.set(f.id, a);
    f.x = R1 * Math.cos(a) * stretch;
    f.y = R1 * Math.sin(a);
    at += span(f);
  });
  if (facets.length) head(facets[facets.length - 1].facet, groupStart, at);

  // An incident sits outside the part that gave it most: what hangs on a part
  // is then one cluster beside it, and its lesser ties are the lines that cross.
  const best = new Map<string, [number, number]>();
  for (const l of data.links) {
    if (l.kind !== "why") continue;
    const a = l.source === "us" ? -Math.PI / 2 : angle.get(l.source);
    if (a === undefined) continue;
    const had = best.get(l.target);
    if (!had || l.weight > had[1]) best.set(l.target, [a, l.weight]);
  }
  const home = new Map<string, number>();
  incidents.forEach((n, i) => {
    const a = best.get(n.id)?.[0] ?? -Math.PI / 2;
    home.set(n.id, a);
    const r = R2 + ((i % 5) - 2) * 9;
    n.x = r * Math.cos(a) * stretch;
    n.y = r * Math.sin(a);
  });
  // Then they settle on the outer ring without overlapping, each near its direction.
  const ring = (alpha: number) => {
    for (const n of incidents) {
      const a0 = home.get(n.id)!;
      const a = Math.atan2(n.y, n.x / stretch);
      const vx = n as unknown as { vx: number; vy: number };
      vx.vx += (R2 * stretch * Math.cos(a) - n.x) * 0.12 * alpha + (R2 * stretch * Math.cos(a0) - n.x) * 0.1 * alpha;
      vx.vy += (R2 * Math.sin(a) - n.y) * 0.12 * alpha + (R2 * Math.sin(a0) - n.y) * 0.1 * alpha;
    }
  };
  const sim = d3.forceSimulation(incidents as d3.SimulationNodeDatum[])
    .force("ring", ring)
    .force("collide", d3.forceCollide<d3.SimulationNodeDatum>().radius((d) => (d as GraphNode).r + 2.5).iterations(2))
    .stop();
  sim.tick(260);
  return { nodes, links: data.links, marks };
}

/** The other lenses: each connected part gets a place of its own, sized to
 *  its nodes, and its nodes arrange themselves there by their links. What is
 *  tied to nothing stands in rows underneath, the weightiest first: scattered
 *  among the rest, its place would look as if it meant something. The same
 *  data always gives the same picture. */
export function layoutPacked(data: GraphData, aspect: number, shelf = "Tied to no other"): Laid {
  const all = d3.group(data.nodes, (n) => String(n.group ?? 0));
  const groups = new Map([...all].filter(([, ns]) => ns.length > 1));
  const single = [...all.values()].filter((ns) => ns.length === 1).map((ns) => ns[0])
    .sort((x, y) => y.relevance - x.relevance || y.incidents - x.incidents || x.label.localeCompare(y.label));
  const tied = [...groups.values()].flat();
  const marks: Mark[] = [];

  if (tied.length) {
    const want = new Map<string, number>();
    for (const [g, ns] of groups) want.set(g, Math.sqrt(d3.sum(ns, (n) => (n.r + 12) ** 2) * 1.7) + 14);
    const root = d3.hierarchy<{ g?: string; children?: { g: string }[] }>({ children: [...groups.keys()].map((g) => ({ g })) })
      .sum((d) => (d.g ? want.get(d.g)! ** 2 : 0))
      .sort((x, y) => (y.value ?? 0) - (x.value ?? 0));
    const H = 1000, W = H * aspect;
    d3.pack<{ g?: string }>().size([W, H]).padding(18)(root as d3.HierarchyNode<{ g?: string }>);
    const leaves = (root.leaves() as d3.HierarchyCircularNode<{ g?: string }>[]);
    // The pack fits the window, not the nodes: bring it to the scale at which a group has the room it wants.
    const scale = d3.median(leaves, (l) => l.r / want.get(l.data.g!)!) || 1;
    const centre = new Map(leaves.map((l) => [l.data.g!, { x: (l.x - W / 2) / scale, y: (l.y - H / 2) / scale }]));
    for (const [g, ns] of groups) {
      const c = centre.get(g)!;
      ns.forEach((n, i) => {
        // A sunflower's seeds: evenly spread, the same every time.
        const rr = Math.sqrt(i + 0.5) * 16, at = i * 2.399963;
        n.x = c.x + rr * Math.cos(at);
        n.y = c.y + rr * Math.sin(at);
      });
    }
    const ids = new Set(tied.map((n) => n.id));
    const links = data.links.filter((l) => ids.has(l.source) && ids.has(l.target)).map((l) => ({ ...l }));
    // Room for a name: what ties three or more together keeps the space at its
    // right hand free. Ghosts ride there through the settling and hold the others off.
    const degree = new Map<string, number>();
    for (const l of links) for (const id of [l.source, l.target]) degree.set(id, (degree.get(id) ?? 0) + 1);
    interface Ghost { id: string; ghost: true; host: GraphNode; dx: number; r: number; x: number; y: number; vx?: number; vy?: number }
    const ghosts: Ghost[] = [];
    for (const n of tied) {
      if (!named(n) || (degree.get(n.id) ?? 0) < 3) continue;
      const cells = Math.min(8, Math.ceil((textWidth(short(n)) + 8) / 16));
      for (let i = 0; i < cells; i++) {
        const dx = n.r + 13 + i * 16;
        ghosts.push({ id: `ghost:${n.id}:${i}`, ghost: true, host: n, dx, r: 9, x: n.x + dx, y: n.y });
      }
    }
    const real = (d: d3.SimulationNodeDatum) => !(d as unknown as Ghost).ghost;
    const home = (d: d3.SimulationNodeDatum) => centre.get(String((d as GraphNode).group ?? 0)) ?? { x: 0, y: 0 };
    const ride = () => { for (const g of ghosts) { g.x = g.host.x + g.dx; g.y = g.host.y; g.vx = 0; g.vy = 0; } };
    const sim = d3.forceSimulation([...tied, ...ghosts] as d3.SimulationNodeDatum[])
      .force("link", d3.forceLink<d3.SimulationNodeDatum, d3.SimulationLinkDatum<d3.SimulationNodeDatum>>(links as never)
        .id((d) => (d as GraphNode).id).distance((l) => ((l as unknown as GraphLink).kind === "owns" ? 34 : 52)).strength(0.55))
      .force("charge", d3.forceManyBody<d3.SimulationNodeDatum>().strength((d) => (real(d) ? -80 : 0)).distanceMax(260))
      .force("collide", d3.forceCollide<d3.SimulationNodeDatum>().radius((d) => (d as GraphNode).r + (real(d) ? 4 : 0)).iterations(2))
      .force("x", d3.forceX<d3.SimulationNodeDatum>((d) => home(d).x).strength((d) => (real(d) ? 0.16 : 0)))
      .force("y", d3.forceY<d3.SimulationNodeDatum>((d) => home(d).y).strength((d) => (real(d) ? 0.16 : 0)))
      .force("ride", ride)
      .stop();
    sim.tick(300);
  }

  if (single.length) {
    // Rows of cells, each wide enough for a name beside its mark.
    const CELL_W = 210, CELL_H = 46;
    const x0 = tied.length ? d3.min(tied, (n) => n.x - n.r)! : 0;
    const x1 = tied.length ? d3.max(tied, (n) => n.x + n.r)! : 0;
    const cols = Math.max(3, Math.min(single.length, Math.round(Math.max(x1 - x0, Math.sqrt(single.length * aspect) * CELL_W) / CELL_W)));
    const left = (x0 + x1) / 2 - (cols * CELL_W) / 2 + 20;
    const top = tied.length ? d3.max(tied, (n) => n.y + n.r)! + 96 : 0;
    single.forEach((n, i) => {
      n.x = left + (i % cols) * CELL_W;
      n.y = top + Math.floor(i / cols) * CELL_H;
    });
    if (tied.length) marks.push({ x: left - 14, y: top - 34, text: `${shelf.toUpperCase()} · ${single.length}`, anchor: "start" });
  }
  return { nodes: data.nodes, links: data.links, marks };
}

/** The radius of every node for the measure the reader picked. Each kind of
 *  node has its own range, so a company is not dwarfed by an incident. */
export function setRadii(nodes: GraphNode[], sizeBy: "relevance" | "money" | "reports"): void {
  const value = (n: GraphNode) => sizeBy === "money" ? n.usd
    : sizeBy === "reports" ? (n.kind === "incident" ? n.reports : n.incidents)
      : n.kind === "facet" ? (n.points ?? 0) : n.relevance;
  const cls = (n: GraphNode) => (n.kind === "incident" ? "incident" : n.kind === "facet" ? "facet" : "entity");
  const range: Record<string, [number, number]> = { incident: [4.5, 13], facet: [8, 20], entity: [5.5, 13] };
  const max = d3.rollup(nodes, (ns) => d3.max(ns, value) ?? 0, cls);
  for (const n of nodes) {
    if (n.kind === "us") n.r = 30;
    else if (n.kind === "cve") n.r = n.kev ? 6 : 5;
    else {
      const [lo, hi] = range[cls(n)];
      const m = max.get(cls(n)) ?? 0;
      n.r = m > 0 ? lo + (hi - lo) * Math.sqrt(Math.max(0, value(n)) / m) : lo;
    }
  }
}
