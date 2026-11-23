import { KIND_LABEL, usd, type Incident } from "../api";

const day = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);

/** An incident as Markdown, to paste into a chat, a ticket or a mail. */
export function incidentMarkdown(inc: Incident): string {
  const lines: string[] = [`## ${inc.title}`, ""];
  if (inc.summary) lines.push(inc.summary, "");
  lines.push(`- Kind: ${inc.category}, first reported ${day(inc.first_seen)}, last ${day(inc.last_seen)}, ${inc.sources.length} source${inc.sources.length === 1 ? "" : "s"}`);
  lines.push(`- Relevance to us: ${inc.relevance}/100${inc.reasons.length ? ` (${inc.reasons.filter((r) => r.points > 0).map((r) => r.why).join("; ")})` : ""}`);
  const who = (role: string) => inc.entities.filter((e) => e.role === role).map((e) => e.name);
  if (who("victim").length) lines.push(`- Hit: ${who("victim").join(", ")}`);
  if (who("attacker").length) lines.push(`- By: ${who("attacker").join(", ")}`);
  if (who("vendor").length) lines.push(`- Vendor: ${who("vendor").join(", ")}`);
  if (inc.cves.length) lines.push(`- Flaws: ${inc.cves.map((c) => `${c.id}${c.kev ? " (exploited)" : ""}`).join(", ")}`);
  for (const m of inc.money.filter((x) => x.usd != null).slice(0, 4)) {
    lines.push(`- Money: ${usd(m.usd)} ${KIND_LABEL[m.kind] ?? m.kind}, as reported by ${m.source}`);
  }
  if (inc.records) lines.push(`- Affected: ${inc.records.toLocaleString()} people or records`);
  if (inc.state.note) lines.push(`- Note: ${inc.state.note}`);
  lines.push("", "Sources:");
  for (const it of inc.items.slice(0, 12)) lines.push(`- ${it.source}: ${it.url ? `[${it.title}](${it.url})` : it.title}`);
  return lines.join("\n");
}
