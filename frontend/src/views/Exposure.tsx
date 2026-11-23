import { useEffect, useState } from "react";
import { api, type ExposureView } from "../api";
import type { ViewProps } from "../App";

export default function Exposure({ days, since, q, tick, onSelect }: ViewProps) {
  const [data, setData] = useState<ExposureView | null>(null);
  const [onlyOurs, setOnlyOurs] = useState(true);
  useEffect(() => {
    api.exposure(days, since).then(setData);
  }, [days, since, tick]);

  const ql = q.toLowerCase();
  const rows = (data?.rows ?? []).filter((r) => (!onlyOurs || r.ours) &&
    (!ql || `${r.cve} ${r.vendor} ${r.product} ${r.name}`.toLowerCase().includes(ql)));
  const ours = (data?.rows ?? []).filter((r) => r.ours).length;

  return (
    <div className="view">
      <h2>Flaws being exploited in software we run</h2>
      <p className="note">CISA's list of flaws known to be exploited, added since {data?.since}, against the stack in the profile
        ({data?.stack.join(", ")}). EPSS is FIRST's estimate that a flaw is exploited in the next 30 days.</p>
      <div className="toolbar">
        <label className="label"><input type="checkbox" checked={onlyOurs} onChange={(e) => setOnlyOurs(e.target.checked)} /> only our stack ({ours} of {data?.rows.length ?? 0})</label>
      </div>
      <table className="grid">
        <thead><tr><th>Added</th><th>CVE</th><th>Vendor and product</th><th>Flaw</th><th>Ransomware</th><th className="num">EPSS</th><th>In the news</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.cve}>
              <td className="mono small">{r.added}</td>
              <td className="mono"><a href={`https://nvd.nist.gov/vuln/detail/${r.cve}`} target="_blank" rel="noreferrer">{r.cve}</a></td>
              <td>{r.ours ? <b>{r.vendor}</b> : r.vendor} {r.product}</td>
              <td className="small">{r.name}</td>
              <td className="small">{r.ransomware_use === "Known" ? "known use" : <span className="faint">not known</span>}</td>
              <td className="num">{r.epss != null ? `${(r.epss * 100).toFixed(1)}%` : <span className="faint">-</span>}</td>
              <td className="small">{r.incidents.map((i) => (
                <div key={i.id}><a href="#" onClick={(e) => { e.preventDefault(); onSelect(i.id); }}>{i.title}</a></div>
              ))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="empty">Nothing in the window{onlyOurs ? " for our stack" : ""}.</div>}
    </div>
  );
}
