import { useEffect, useState } from "react";
import { api, ago, safeUrl, SNAPSHOT, type SourcesView } from "../api";

export default function Sources({ tick }: { tick: number }) {
  const [data, setData] = useState<SourcesView | null>(null);
  useEffect(() => {
    api.sources().then(setData);
  }, [tick]);
  if (!data) return <div className="view"><p className="muted">Loading</p></div>;
  const m = data.model;
  // Failing first, then by desk and kind.
  const rows = [...data.sources].sort((a, b) => Number(!!b.error) - Number(!!a.error) || a.desk.localeCompare(b.desk) * -1 || a.kind.localeCompare(b.kind));
  const failing = rows.filter((s) => s.error).length;
  return (
    <div className="view">
      <h2>Sources: {rows.length - failing} of {rows.length} answering</h2>
      {SNAPSHOT && <p className="note">As they stood when this copy of the page was made, {ago(SNAPSHOT.at)}.</p>}
      <table className="grid">
        <thead><tr><th>Source</th><th>Desk</th><th>Kind</th><th>How far to trust it</th><th className="num">Every</th><th>Last read</th>
          <th className="num">Items</th><th className="num">Kept</th><th>State</th></tr></thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.name}>
              <td><a href={safeUrl(s.url)} target="_blank" rel="noreferrer">{s.name}</a></td>
              <td className="small">{s.desk}</td>
              <td className="small">{s.kind}</td>
              <td className="small muted">{s.reliability}</td>
              <td className="num">{s.every_min >= 120 ? `${s.every_min / 60} h` : `${s.every_min} min`}</td>
              <td className="small">{data.busy.includes(s.name) ? "reading now" : ago(s.last_try)}</td>
              <td className="num">{s.items ?? ""}</td>
              <td className="num">{s.stored}</td>
              <td className="small">{s.error ? <span className="state-bad">failing: {s.error}{s.last_ok ? ` (last good ${ago(s.last_ok)})` : ""}</span>
                : s.last_ok ? <span className="state-good">answering</span> : <span className="faint">not read yet</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Not read</h3>
      <ul className="items">{data.not_read.map((n) => <li key={n.name}><b>{n.name}</b>: <span className="muted">{n.why}</span></li>)}</ul>
      {!SNAPSHOT && data.wikidata && (
        <>
          <h3>Around the companies</h3>
          <p className="small">
            Wikidata (owners and subsidiaries):{" "}
            {data.wikidata.error ? (
              <><span className="state-bad">not answering ({data.wikidata.error})</span>, asked again at{" "}
                {new Date((data.wikidata.until ?? 0) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.
                {!data.wikidata.contact && " It asks a script to say how to reach whoever runs it: set RADAR_CONTACT in .env."}</>
            ) : data.wikidata.asked === 0 ? "nothing looked up yet."
              : <><span className="state-good">answering</span>, {data.wikidata.known} of {data.wikidata.asked} companies found.</>}
          </p>
        </>
      )}
      <h3>The model</h3>
      {SNAPSHOT ? (
        <p className="small">{m.key ? `${m.name} reads the news beside the rules.` : "The rules alone read the items (known names only)."}</p>
      ) : (
        <p className="small">
          {m.key ? <>{m.name}: {m.today.calls} of {m.daily_calls} calls today ({m.today.items} items, {m.today.failed} failed),
            about ${m.cost_today_usd.toFixed(3)} at list price.</> : "No GEMINI_API_KEY in cyber-news-agregate/.env: the rules alone read the items (known names only)."}
          {" "}Items: {Object.entries(m.states).map(([k, v]) => `${v} ${k === "skipped" ? "structured (no model needed)" : k}`).join(", ")}.
          {m.today.last?.error && <span className="state-bad"> Last error: {m.today.last.error.slice(0, 160)}</span>}
        </p>
      )}
      <p className="note">The model only names what an item's own text writes: a company or an amount it cannot quote from the item is dropped.
        {!SNAPSHOT && ` Incidents are rebuilt in ${data.build_seconds} s whenever something new arrives.`}</p>
      {!SNAPSHOT && data.pages?.on && (
        <>
          <h3>The copy on GitHub Pages</h3>
          <p className="small">
            {!data.pages.last ? "Not pushed yet since this start: it goes out when the sources have been read."
              : data.pages.last.ok ? <><span className="state-good">pushed</span> {ago(data.pages.last.at)}: {data.pages.last.incidents?.toLocaleString()} incidents
                in {data.pages.last.files?.toLocaleString()} files ({((data.pages.last.bytes ?? 0) / 1e6).toFixed(1)} MB).</>
                : <span className="state-bad">not pushed {ago(data.pages.last.at)}: {data.pages.last.error}</span>}
          </p>
        </>
      )}
    </div>
  );
}
