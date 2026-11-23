export type Category =
  | "ransomware" | "breach" | "vulnerability" | "malware" | "actor" | "tool" | "policy" | "crypto" | "ddos" | "ai" | "other";

export const CATEGORIES: Category[] = [
  "ransomware", "breach", "vulnerability", "malware", "actor", "tool", "policy", "crypto", "ddos", "ai", "other",
];

/** The desks: everything, cybersecurity, or AI news. A story about both is on both. */
export type Desk = "" | "cyber" | "ai";

export interface Reason { points: number; why: string }

export interface Brief {
  id: string;
  title: string;
  summary: string | null;
  category: Category;
  first_seen: number;
  last_seen: number;
  relevance: number;
  kinds: string[];
  sources: string[];
  victims: string[];
  attackers: string[];
  vendors: string[];
  headline_usd: number | null;
  headline_kind: string | null;
  records: number | null;
  countries: string[];
  topics: string[];
  roundup: boolean;
  reasons: Reason[];
  cves: string[];
  kev: boolean;
  items: number;
  url: string | null;
  state: State;
}

/** What the reader did with an incident. ``updated``: told again since last opened. */
export interface State { starred: boolean; dismissed: boolean; seen: number | null; note: string | null; updated: boolean }

export interface Related { id: string; title: string; category: Category; relevance: number; last_seen: number; shares: string[] }

export interface Entity {
  name: string; type: string; role: string; sector: string | null; country: string | null; items: number;
}

export interface MoneyFact {
  amount: number; currency: string; kind: string; quote: string; usd: number | null; item: string; source: string;
  stated_by_source?: boolean;
}

export interface Company {
  qid: string; label: string; description: string | null; url: string; parent: string[]; subsidiaries: string[];
  industry: string[]; country: string | null; exchange: string[]; employees: number | null;
}

export interface Incident extends Omit<Brief, "cves" | "items"> {
  entities: Entity[];
  cves: { id: string; kev: boolean; ransomware_use: string | null; epss: number | null; percentile: number | null; vendor: string | null; product: string | null }[];
  money: MoneyFact[];
  items: { id: string; source: string; kind: string; title: string; url: string | null; published: number; read_by: string;
    data: Record<string, unknown>; paywall: boolean }[];
  via: string[];
  read_by_model: number;
  companies: Record<string, Company>;
  related: Related[];
}

/** The graph's lenses: each built for one question (backend graphs.py). */
export type Lens = "us" | "links" | "companies" | "groups";

export interface GraphNode {
  id: string; kind: string; label: string; sub?: string | null; category?: Category; relevance: number; usd: number;
  reports: number; incidents: number; sector?: string | null; country?: string | null; role?: string;
  /** What the profile says this is to us ("stack", "peer", "actor"...), if anything. */
  ours?: string | null;
  /** A parent company drawn only because it ties two shown companies: not in the news itself. */
  outside?: boolean;
  kev?: boolean; epss?: number | null; facet?: string; points?: number; group?: number | string; claim?: boolean;
  last_seen?: number; victims?: number; more?: number; wikidata?: string;
  x: number; y: number; r: number;
}
export interface GraphLink { source: string; target: string; kind: string; weight: number }
export interface GraphData {
  lens: Lens; nodes: GraphNode[]; links: GraphLink[]; of: number; alone: number;
  facets?: { id: string; label: string }[]; sectors?: { id: string; label: string; count: number }[];
}
export interface NodeDetail {
  id: string; label: string; kind: string; sub: string | null; total: number; roles: Record<string, number>; usd: number;
  wikidata: Company | null;
  incidents: { id: string; title: string; category: Category; relevance: number; last_seen: number; role: string; usd: number | null; sources: number }[];
}

const deskQ = (desk: Desk) => (desk ? `&desk=${desk}` : "");
/** Query for a window: the last ``days``, or since the moment ``since`` (epoch seconds). */
const winQ = (days: number, since?: number) => (since !== undefined ? `since=${Math.floor(since)}&days=${days}` : `days=${days}`);

/** Called with true when the backend answers, false when it cannot be reached. */
let onReach: (ok: boolean) => void = () => {};
export const watchReach = (fn: (ok: boolean) => void) => { onReach = fn; };

async function get<T>(path: string): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path);
  } catch (e) {
    onReach(false);
    throw e;
  }
  onReach(true);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

function query(p: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== "") q.set(k, String(v));
  return q.toString();
}

export const api = {
  feed: (p: Record<string, string | number | undefined>) =>
    get<{ total: number; categories: Record<string, number>; incidents: Brief[] }>(`/api/feed?${query(p)}`),
  /** A link that downloads what the same filters show, as a file. */
  exportUrl: (format: "csv" | "json", p: Record<string, string | number | undefined>) => `/api/export?${query({ ...p, format })}`,
  brief: (hours: number, desk: Desk, since?: number) =>
    get<BriefView>(`/api/brief?${query({ hours, desk, since: since !== undefined ? Math.floor(since) : undefined })}`),
  incident: (id: string) => get<Incident>(`/api/incident/${id}`),
  setState: async (id: string, change: Partial<{ starred: boolean; dismissed: boolean; seen: boolean; note: string }>) => {
    const r = await fetch(`/api/incident/${id}/state`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<State>;
  },
  graph: (lens: Lens, days: number, minRel: number, limit: number, desk: Desk, since?: number) =>
    get<GraphData>(`/api/graph?lens=${lens}&${winQ(days, since)}&min_relevance=${minRel}&limit=${limit}${deskQ(desk)}`),
  node: (id: string, days: number, desk: Desk, since?: number) =>
    get<NodeDetail>(`/api/node?id=${encodeURIComponent(id)}&${winQ(days, since)}${deskQ(desk)}`),
  companies: (days: number, desk: Desk, since?: number) => get<{ companies: CompanyRow[] }>(`/api/companies?${winQ(days, since)}${deskQ(desk)}`),
  money: (days: number, desk: Desk, since?: number) => get<MoneyView>(`/api/money?${winQ(days, since)}${deskQ(desk)}`),
  timeline: (days: number, desk: Desk, since?: number) => get<TimelineView>(`/api/timeline?${winQ(days, since)}${deskQ(desk)}`),
  exposure: (days: number, since?: number) => get<ExposureView>(`/api/exposure?${winQ(days, since)}`),
  sources: () => get<SourcesView>(`/api/sources`),
  profile: () => get<Profile>(`/api/profile`),
  saveProfile: async (p: Profile) => {
    const r = await fetch(`/api/profile`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<Profile>;
  },
  refresh: () => fetch(`/api/refresh`, { method: "POST" }),
};

export interface CompanyRow {
  key: string; name: string; type: string; sector: string; country: string | null; as_victim: number; as_vendor: number;
  usd: number; records: number; relevance: number;
  incidents: { id: string; title: string; relevance: number; role: string; usd: number | null; last_seen: number }[];
  wikidata: Company | null;
  related: { name: string; how: string; in_news: boolean }[];
}

export interface MoneyView {
  facts: { incident: string; title: string; category: Category; relevance: number; victims: string[]; kind: string;
    amount: number; currency: string; usd: number | null; quote: string; source: string; when: number }[];
  by_kind: Record<string, number>;
  fx_day: string | null;
  fx_source: string;
}

export interface TimelineView {
  start: number;
  bucket: number;
  buckets: ({ t: number } & Record<string, number>)[];
  actors: { name: string; events: { t: number; id: string; title: string; relevance: number }[] }[];
  incidents: { id: string; title: string; category: Category; relevance: number; first_seen: number; sources: number; usd: number | null }[];
}

export interface ExposureView {
  since: string; stack: string[];
  rows: { cve: string; vendor: string; product: string; name: string; added: string; ransomware_use: string; ours: boolean;
    epss: number | null; percentile: number | null; incidents: { id: string; title: string; relevance: number }[] }[];
}

export interface BriefView {
  since: number;
  counts: { incidents: number; by_category: Record<string, number>; high: number; sources: number };
  top: Brief[];
  exploited: ExposureView["rows"];
  money: MoneyView["facts"];
  trending: { name: string; kind: string; today: number; daily_before: number; incident: { id: string; title: string; relevance: number } }[];
  tools: Brief[];
  ai: Brief[];
  starred: Brief[];
}

export interface SourcesView {
  sources: { name: string; kind: string; desk: string; url: string; every_min: number; reliability: string; last_try: number | null;
    last_ok: number | null; items: number | null; new_items: number | null; stored: number; error: string | null }[];
  not_read: { name: string; why: string }[];
  model: { name: string; key: boolean; daily_calls: number; cost_today_usd: number; states: Record<string, number>;
    today: { calls: number; items: number; prompt_tokens: number; output_tokens: number; failed: number;
      last: { at: number; ok: number; error: string | null } | null } };
  busy: string[];
  polling: boolean;
  build_seconds: number;
}

export interface Interest { name: string; project: string; points: number; keywords: string[] }
export interface Profile {
  organization: string; aliases: string[]; sectors: string[]; countries: Record<string, number>; stack: string[];
  suppliers: string[]; own_tools: string[]; peers: string[]; actors: string[]; interests: Interest[];
  authorities: Record<string, number>;
}

// -- formatting ------------------------------------------------------------------------------

export function usd(n: number | null | undefined): string {
  if (n == null) return "";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(n >= 1e10 ? 0 : 1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}k`;
  return `$${Math.round(n)}`;
}

export function count(n: number | null | undefined): string {
  if (n == null) return "";
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(n);
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** The colour of a kind of incident, for a style attribute (the eight chart classes: lib/viz.ts). */
const CAT_CLASS: Record<string, string> = { ddos: "malware", actor: "policy" };
export const catColor = (c: string) => `var(--k-${CAT_CLASS[c] ?? (CATEGORIES.includes(c as Category) ? c : "other")})`;

export const KIND_LABEL: Record<string, string> = {
  theft: "stolen", ransom_paid: "ransom paid", ransom_demand: "ransom asked", loss: "loss or cost", fine: "fine",
  settlement: "settlement", reward: "reward offered", business: "business (not damage)", other: "unclear",
};

/** Resolved CSS colour of a token, for d3 (which cannot read var()). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

/** A link from a feed, only if it is a web address: never "javascript:" or "data:". */
export function safeUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const u = new URL(url, location.origin);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : undefined;
  } catch {
    return undefined;
  }
}
