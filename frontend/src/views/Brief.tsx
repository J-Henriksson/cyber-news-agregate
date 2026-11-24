import { useEffect, useState } from "react";
import { api, ago, KIND_LABEL, SNAPSHOT, usd, type Brief, type BriefView as BriefData } from "../api";
import IncidentRow from "../components/IncidentRow";
import { CLASSES, classOf } from "../lib/viz";
import type { ViewProps } from "../App";

/** The day on one page: what matters most to us, what is being exploited in
 *  our stack, what is rising, the money, tools for the team's work, AI news. */
export default function BriefView({ days, since, label, tick, selected, onSelect, fresh, desk, refresh, onView }: ViewProps & { onView: (view: string) => void }) {
  const [data, setData] = useState<BriefData | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(true);
  // The brief is of a day (or of today); a longer window is the feed's work.
  const hours = since !== undefined ? 24 : Math.min(days, 3) * 24;

  useEffect(() => {
    setBusy(true);
    api.brief(hours, desk, since).then((d) => { setData(d); setFailed(false); }).catch(() => setFailed(true)).finally(() => setBusy(false));
  }, [hours, desk, since, tick]);

  if (!data) return <div className="view"><p className="muted">{failed ? "The brief could not be read." : "Reading the day."}</p></div>;
  const span = since !== undefined ? "today" : hours === 24 ? "the last 24 hours" : `the last ${hours / 24} days`;
  const rows = (list: Brief[], empty: string) => list.length === 0 ? <p className="faint small">{empty}</p> : (
    <div className="rows tight">
      {list.map((r) => <IncidentRow key={r.id} r={r} compact on={r.id === selected} isNew={fresh.has(r.id)} onSelect={onSelect} refresh={refresh} />)}
    </div>
  );
  // The kinds of the day, ranked: nine classes read best as bars with their figures.
  const kinds = CLASSES.map((c) => ({ ...c, n: Object.entries(data.counts.by_category).filter(([cat]) => classOf(cat) === c.key).reduce((a, [, v]) => a + v, 0) }))
    .filter((c) => c.n > 0).sort((a, b) => b.n - a.n);
  const most = Math.max(1, ...kinds.map((k) => k.n));

  return (
    <div className={`view brief ${busy ? "busy" : ""}`}>
      <h2>Brief <span className="muted">· {span}</span></h2>
      {since === undefined && days > 3 && <p className="note">The brief is of the last three days at most. The feed has all of {label}.</p>}
      <div className="tiles">
        <button className="tile" onClick={() => onView("feed")}>
          <span className="tile-label">Incidents</span><b className="tile-value">{data.counts.incidents.toLocaleString()}</b>
          <span className="tile-sub">from {data.counts.sources} sources</span>
        </button>
        <button className="tile" onClick={() => onView("feed")}>
          <span className="tile-label">Relevance 50 or more</span><b className="tile-value">{data.counts.high}</b>
          <span className="tile-sub">touch the profile closely</span>
        </button>
        <div className="tile">
          <span className="tile-label">Exploited in our stack</span><b className="tile-value">{data.exploited.length}</b>
          <span className="tile-sub">added by CISA in 7 days</span>
        </div>
        <button className="tile" onClick={() => onView("graph")}>
          <span className="tile-label">Named more than usual</span><b className="tile-value">{data.trending.length}</b>
          <span className="tile-sub">groups, companies, flaws</span>
        </button>
      </div>

      <div className="brief-cols">
        <div className="brief-main">
          <section>
            <h3>What matters most to us</h3>
            {rows(data.top, `Nothing above relevance 20 ${span}.`)}
            <button className="btn more" onClick={() => onView("feed")}>The whole feed</button>
          </section>
          <section>
            <h3>Tools and methods for the team's work · 7 days</h3>
            {rows(data.tools, "No new tool or paper touched the team's topics this week.")}
          </section>
          <section>
            <h3>AI news · 2 days</h3>
            {rows(data.ai, "No AI news in the last two days.")}
          </section>
        </div>

        <aside className="brief-side">
          <section>
            <h3>Being exploited in software we run · 7 days</h3>
            {data.exploited.length === 0 ? <p className="faint small">No new entry on CISA's exploited list for our stack.</p> : (
              <table className="grid tight">
                <tbody>
                  {data.exploited.map((r) => (
                    <tr key={r.cve} className={r.incidents.length ? "click" : ""} onClick={() => r.incidents[0] && onSelect(r.incidents[0].id)}>
                      <td className="mono small faint">{r.added.slice(5)}</td>
                      <td><b>{r.vendor}</b> {r.product}
                        <div className="faint small mono">{r.cve}{r.epss != null ? ` · EPSS ${(r.epss * 100).toFixed(r.epss < 0.1 ? 1 : 0)}%` : ""}{r.ransomware_use === "Known" ? " · ransomware" : ""}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h3>Rising: named more than usual</h3>
            {data.trending.length === 0 ? <p className="faint small">Nothing is named more today than on a day of last week.</p> : (
              <table className="grid tight">
                <tbody>
                  {data.trending.map((t) => (
                    <tr key={t.kind + t.name} className="click" onClick={() => onSelect(t.incident.id)}>
                      <td><b>{t.name}</b> <span className="faint small">{t.kind === "actor" ? "group" : t.kind}</span>
                        <div className="faint small">{t.incident.title}</div></td>
                      <td className="num" title={`${t.daily_before} a day in the week before`}>{t.today} today</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h3>Money reported · 7 days</h3>
            {data.money.length === 0 ? <p className="faint small">No amount reported this week.</p> : (
              <table className="grid tight">
                <tbody>
                  {data.money.map((f, i) => (
                    <tr key={i} className="click" onClick={() => onSelect(f.incident)}>
                      <td className="num"><b>{usd(f.usd)}</b></td>
                      <td>{f.victims[0] ?? f.title}<div className="faint small">{KIND_LABEL[f.kind] ?? f.kind} · {f.source} · {ago(f.when)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <button className="btn more" onClick={() => onView("money")}>All amounts</button>
          </section>

          <section>
            <h3>By kind · {span}</h3>
            <div className="bars">
              {kinds.map((k) => (
                <div key={k.key} style={{ display: "contents" }}>
                  <span className="name"><i className="swatch" style={{ background: `var(--k-${k.key})` }} />{k.label}</span>
                  <span className="track"><i style={{ width: `${(k.n / most) * 100}%` }} /></span>
                  <span className="fig">{k.n}</span>
                </div>
              ))}
            </div>
          </section>

          {!SNAPSHOT && (
            <section>
              <h3>Starred</h3>
              {rows(data.starred, "Nothing starred. Star an incident (s) to keep it here and see when it is told again.")}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
