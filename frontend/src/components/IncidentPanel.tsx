import { useEffect, useRef, useState } from "react";
import { api, ago, catColor, count, KIND_LABEL, safeUrl, SNAPSHOT, usd, type Incident } from "../api";
import { incidentMarkdown } from "../lib/markdown";

const ROLE_ORDER = ["victim", "attacker", "vendor", "mentioned"];
const ROLE_LABEL: Record<string, string> = { victim: "Hit", attacker: "By", vendor: "Vendor", mentioned: "Named" };

interface Props {
  id: string;
  tick: number;
  onClose: () => void;
  onSelect: (id: string) => void;
  refresh: () => void;
}

export default function IncidentPanel({ id, tick, onClose, onSelect, refresh }: Props) {
  const [inc, setInc] = useState<Incident | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState(false);
  const seenFor = useRef<string | null>(null);

  useEffect(() => {
    setInc(null);
    setError(null);
    setCopied(false);
    api.incident(id).then((next) => {
      setInc(next);
      setNote(next.state.note ?? "");
      // Opening it is reading it: from now on "updated" means told again since.
      if (!SNAPSHOT && seenFor.current !== next.id) {
        seenFor.current = next.id;
        api.setState(next.id, { seen: true }).catch(() => undefined);
      }
    }).catch(() => setError(SNAPSHOT ? "This incident is not in this copy of the page (its reports aged out, or it was regrouped since)."
      : "This incident is no longer in the store (its reports aged out, or it was regrouped)."));
  }, [id]);

  // Something changed on the server: read it again (the server follows an
  // incident that was regrouped under another id).
  useEffect(() => {
    if (tick === 0) return;
    api.incident(id).then(setInc).catch(() => undefined);
  }, [tick, id]);

  if (error) return <aside className="panel"><button className="btn close" onClick={onClose}>Close</button><p className="muted">{error}</p></aside>;
  if (!inc) return <aside className="panel"><button className="btn close" onClick={onClose}>Close</button><p className="muted">Loading</p></aside>;

  const byRole = ROLE_ORDER.map((r) => [r, inc.entities.filter((e) => e.role === r)] as const).filter(([, es]) => es.length);
  const companies = Object.entries(inc.companies);
  const set = (change: Parameters<typeof api.setState>[1]) => api.setState(inc.id, change).then((state) => {
    setInc({ ...inc, state: { ...inc.state, ...state } });
    refresh();
  });
  const copy = () => navigator.clipboard.writeText(incidentMarkdown({ ...inc, state: { ...inc.state, note: note || null } }))
    .then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); }).catch(() => undefined);

  return (
    <aside className="panel" aria-label="Incident">
      <div className="panel-acts">
        {!SNAPSHOT && <button className={`btn ${inc.state.starred ? "on" : ""}`} onClick={() => set({ starred: !inc.state.starred })}>{inc.state.starred ? "★ Starred" : "☆ Star"}</button>}
        {!SNAPSHOT && <button className={`btn ${inc.state.dismissed ? "on" : ""}`} onClick={() => set({ dismissed: !inc.state.dismissed })}
          title="Not for us: leaves every view (find it again under Feed, Dismissed)">{inc.state.dismissed ? "Dismissed: bring back" : "Dismiss"}</button>}
        <button className="btn" onClick={copy} title="Copy as Markdown, for a chat, a ticket or a mail">{copied ? "Copied" : "Copy"}</button>
        <span className="spacer" />
        <button className="btn" onClick={onClose}>Close</button>
      </div>
      <span className="cat"><i style={{ background: catColor(inc.category) }} />{inc.category}</span>
      {inc.kev && <span className="flag hot" style={{ marginLeft: 10 }}>exploited</span>}
      {inc.roundup && <span className="flag" style={{ marginLeft: 10 }}>roundup</span>}
      <h1>{inc.title}</h1>
      {inc.summary && <p className="lede">{inc.summary}</p>}
      <p className="muted small">
        First seen {ago(inc.first_seen)}, last {ago(inc.last_seen)} · {inc.sources.length} source{inc.sources.length === 1 ? "" : "s"} ·
        {" "}{inc.read_by_model}/{inc.items.length} read by the model
      </p>

      <div className="score-line"><b>{inc.relevance}</b><span>relevance to us, of 100</span></div>
      {inc.reasons.length ? (
        <table className="reasons">
          <tbody>
            {inc.reasons.map((r, i) => (
              <tr key={i} className={r.points < 0 ? "minus" : ""}><td>{r.why}</td><td className="p">{r.points > 0 ? `+${r.points}` : r.points}</td></tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted small">Nothing in it touches the profile.</p>}

      {byRole.length > 0 && <h3>Who</h3>}
      <div className="ent">
        {byRole.map(([role, es]) => (
          <div key={role} style={{ display: "contents" }}>
            <span className="k">{ROLE_LABEL[role]}</span>
            <span>
              {es.slice(0, 14).map((e, i) => (
                <span key={e.name}>
                  {i > 0 && ", "}
                  {e.name}
                  {(e.sector || e.country) && <span className="faint small"> ({[e.sector, e.country].filter(Boolean).join(", ")})</span>}
                </span>
              ))}
              {es.length > 14 && <span className="faint small"> and {es.length - 14} more</span>}
            </span>
          </div>
        ))}
        {inc.records ? (<><span className="k">Affected</span><span>{count(inc.records)} people or records</span></>) : null}
        {inc.via.length > 0 && (<><span className="k">Way in</span><span>{inc.via.join(", ")}</span></>)}
      </div>

      {inc.money.length > 0 && (
        <>
          <h3>Money (as reported)</h3>
          {inc.money.map((m, i) => (
            <div key={i}>
              <b>{m.usd != null ? usd(m.usd) : `${m.amount.toLocaleString()} ${m.currency}`}</b>
              <span className="muted"> {KIND_LABEL[m.kind] ?? m.kind}</span>
              {m.currency !== "USD" && m.usd != null && <span className="faint small"> ({m.amount.toLocaleString()} {m.currency})</span>}
              <div className="quote">"{m.quote}" ({m.source})</div>
            </div>
          ))}
        </>
      )}

      {inc.cves.length > 0 && (
        <>
          <h3>Flaws</h3>
          <table className="grid">
            <thead><tr><th>CVE</th><th>Exploited</th><th className="num">EPSS</th></tr></thead>
            <tbody>
              {inc.cves.slice(0, 12).map((c) => (
                <tr key={c.id}>
                  <td className="mono"><a href={`https://nvd.nist.gov/vuln/detail/${encodeURIComponent(c.id)}`} target="_blank" rel="noreferrer">{c.id}</a>
                    {c.vendor && <div className="faint small">{c.vendor} {c.product}</div>}</td>
                  <td>{c.kev ? `yes (CISA KEV)${c.ransomware_use === "Known" ? ", by ransomware" : ""}` : <span className="faint">not listed</span>}</td>
                  <td className="num">{c.epss != null ? `${(c.epss * 100).toFixed(1)}%` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {inc.cves.length > 12 && <p className="faint small">and {inc.cves.length - 12} more</p>}
        </>
      )}

      {inc.related.length > 0 && (
        <>
          <h3>Related incidents</h3>
          <ul className="items">
            {inc.related.map((r) => (
              <li key={r.id}>
                <a href="#" onClick={(e) => { e.preventDefault(); onSelect(r.id); }}>{r.title}</a>
                <div className="faint small">shares {r.shares.join(", ")} · relevance {r.relevance} · {ago(r.last_seen)}</div>
              </li>
            ))}
          </ul>
        </>
      )}

      {companies.length > 0 && (
        <>
          <h3>Companies around them</h3>
          {companies.slice(0, 6).map(([name, c]) => (
            <div key={name} className="small" style={{ marginBottom: 8 }}>
              <b>{name}</b> <a href={safeUrl(c.url)} target="_blank" rel="noreferrer" className="faint">Wikidata</a>
              {c.description && <div className="muted">{c.description}</div>}
              {c.parent.length > 0 && <div>Owned by {c.parent.join(", ")}</div>}
              {c.subsidiaries.length > 0 && <div className="muted">Owns {c.subsidiaries.slice(0, 8).join(", ")}{c.subsidiaries.length > 8 ? ` and ${c.subsidiaries.length - 8} more` : ""}</div>}
              {c.employees ? <div className="faint">{count(c.employees)} staff</div> : null}
            </div>
          ))}
        </>
      )}

      {!SNAPSHOT && (
        <>
          <h3>Note</h3>
          <textarea className="note-box" value={note} placeholder="A note for yourself; it shows in the lists and in the copy"
            onChange={(e) => setNote(e.target.value)} onBlur={() => note !== (inc.state.note ?? "") && set({ note })} />
        </>
      )}

      <h3>Sources ({inc.items.length})</h3>
      <ul className="items">
        {inc.items.slice().reverse().map((it) => {
          const href = safeUrl(it.url);
          return (
            <li key={it.id}>
              {href ? <a href={href} target="_blank" rel="noreferrer">{it.title}</a> : it.title}
              <div className="faint small">
                {it.source} · {ago(it.published)}{it.paywall ? " · may be behind a paywall" : ""}{it.read_by === "rules" ? " · rules only" : ""}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
