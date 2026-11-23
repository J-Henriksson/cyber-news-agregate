import * as d3 from "d3";
import { cssVar } from "../api";

/** The kinds of incident as the charts colour them: eight hues in a fixed
 *  order (the order is what keeps neighbours apart for colour-blind readers)
 *  and grey for the rest. Eleven categories fold into these: a ninth hue
 *  would not be told from the others. */
export const CLASSES: { key: string; label: string; cats: string[] }[] = [
  { key: "vulnerability", label: "vulnerability", cats: ["vulnerability"] },
  { key: "breach", label: "breach", cats: ["breach"] },
  { key: "tool", label: "tools, research", cats: ["tool"] },
  { key: "crypto", label: "crypto theft", cats: ["crypto"] },
  { key: "malware", label: "malware, DDoS", cats: ["malware", "ddos"] },
  { key: "ai", label: "AI", cats: ["ai"] },
  { key: "policy", label: "actors, law", cats: ["policy", "actor"] },
  { key: "ransomware", label: "ransomware", cats: ["ransomware"] },
  { key: "other", label: "other", cats: ["other"] },
];
const CLASS_OF: Record<string, string> = Object.fromEntries(CLASSES.flatMap((c) => c.cats.map((cat) => [cat, c.key])));

export const classOf = (category: string): string => CLASS_OF[category] ?? "other";
/** For a style attribute. */
export const classVar = (category: string): string => `var(--k-${classOf(category)})`;
/** Resolved, for d3. */
export const classColor = (category: string): string => cssVar(`--k-${classOf(category)}`);

/** Relevance in five bands, the steps of one hue: 0-19, 20-39, 40-59, 60-79, 80 and over. */
export const band = (relevance: number): number => (relevance >= 80 ? 5 : relevance >= 60 ? 4 : relevance >= 40 ? 3 : relevance >= 20 ? 2 : 1);
export const bandColor = (relevance: number): string => cssVar(`--seq-${band(relevance)}`);
export const BAND_LABELS = ["under 20", "20 to 39", "40 to 59", "60 to 79", "80 and over"];

/** Near-black or white, whichever reads on a fill. */
export const inkOn = (fill: string): string => (d3.lab(fill).l > 62 ? "#0b0e13" : "#ffffff");

const hexagon: d3.SymbolType = {
  draw(context, size) {
    const r = Math.sqrt((2 * size) / (3 * Math.sqrt(3)));
    for (let k = 0; k < 6; k++) {
      const a = (Math.PI / 3) * k + Math.PI / 6;
      if (k === 0) context.moveTo(r * Math.cos(a), r * Math.sin(a));
      else context.lineTo(r * Math.cos(a), r * Math.sin(a));
    }
    context.closePath();
  },
};

/** What a node is, by its shape (hue is spent on relevance and on whose it is). */
export const SHAPES: Record<string, { type: d3.SymbolType; name: string }> = {
  incident: { type: d3.symbolCircle, name: "incident" },
  us: { type: d3.symbolCircle, name: "us" },
  facet: { type: hexagon, name: "part of our profile" },
  company: { type: d3.symbolSquare, name: "organisation" },
  government: { type: d3.symbolSquare, name: "organisation" },
  actor: { type: d3.symbolTriangle, name: "group" },
  person: { type: d3.symbolTriangle, name: "group" },
  cve: { type: d3.symbolDiamond, name: "flaw (CVE)" },
  product: { type: d3.symbolDiamond2, name: "product" },
};

/** The outline of a node of a kind, as large in area as a circle of radius r. */
export function shapePath(kind: string, r: number): string {
  const shape = SHAPES[kind] ?? SHAPES.incident;
  return d3.symbol().type(shape.type).size(Math.PI * r * r)() ?? "";
}

/** A text's width on screen, near enough to keep labels off each other. */
export const textWidth = (text: string, px = 11): number => text.length * px * 0.56;
