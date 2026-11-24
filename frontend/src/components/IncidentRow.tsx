import { memo } from "react";
import { api, ago, catColor, count, SNAPSHOT, usd, type Brief } from "../api";

interface Props {
  r: Brief;
  on?: boolean;
  cursor?: boolean;
  isNew?: boolean;
  /** Fewer lines: no summary, no reasons (the brief's lists). */
  compact?: boolean;
  onSelect: (id: string) => void;
  refresh: () => void;
}

const MONEY: Record<string, string> = {
  theft: "stolen", ransom_paid: "ransom paid", ransom_demand: "ransom asked", loss: "lost", fine: "fine", settlement: "settlement",
};

/** One incident in a list. Its lines, top to bottom: what kind it is and how
 *  fresh, the headline, a sentence, who and how much, and why it ranks there. */
function IncidentRow({ r, on, cursor, isNew, compact, onSelect, refresh }: Props) {
  const claimed = r.kinds.every((k) => k === "social" || k === "ransomware");
  const level = r.relevance >= 50 ? "hi" : r.relevance >= 20 ? "mid" : "lo";
  const set = (change: Parameters<typeof api.setState>[1]) => (e: React.MouseEvent) => {
    e.stopPropagation();
    api.setState(r.id, change).then(refresh);
  };
  const why = r.reasons.filter((x) => x.points > 0).slice(0, 4);
  return (
    <article className={`row ${level} ${on ? "sel" : ""} ${cursor ? "cur" : ""} ${r.state.dismissed ? "gone" : ""}`}
      data-id={r.id} onClick={() => onSelect(r.id)}>
      <div className="row-score" title={`Relevance ${r.relevance} of 100`}>
        <b>{r.relevance}</b>
        <span className="meter"><i style={{ width: `${r.relevance}%` }} /></span>
      </div>
      <div className="row-body">
        <div className="row-top">
          <span className="cat"><i style={{ background: catColor(r.category) }} />{r.category}</span>
          {isNew && <span className="flag fresh">new</span>}
          {!isNew && r.state.updated && <span className="flag fresh">updated</span>}
          {r.kev && <span className="flag hot">exploited</span>}
          {r.category !== "ai" && r.topics.includes("ai") && <span className="flag">AI</span>}
          {claimed && <span className="flag">claim</span>}
          {r.roundup && <span className="flag">roundup</span>}
          <span className="row-when">{r.sources.length} source{r.sources.length === 1 ? "" : "s"} · {ago(r.last_seen)}</span>
          {!SNAPSHOT && (
            <span className="acts">
              <button className={`act ${r.state.starred ? "on" : ""}`} onClick={set({ starred: !r.state.starred })}
                aria-label={r.state.starred ? "Remove the star" : "Star"} title={r.state.starred ? "Starred (s)" : "Star (s)"}>
                {r.state.starred ? "★" : "☆"}
              </button>
              <button className="act" onClick={set({ dismissed: !r.state.dismissed })}
                aria-label={r.state.dismissed ? "Bring back" : "Dismiss"} title={r.state.dismissed ? "Bring back (x)" : "Dismiss: not for us (x)"}>
                {r.state.dismissed ? "↺" : "×"}
              </button>
            </span>
          )}
        </div>
        <h4 className="row-title">{r.title}</h4>
        {!compact && r.summary && r.summary !== r.title && <p className="row-sum">{r.summary}</p>}
        {(r.victims.length > 0 || r.attackers.length > 0 || r.vendors.length > 0 || r.headline_usd != null || r.records || r.cves.length > 0) && (
          <div className="row-who">
            {r.victims.length > 0 && <span>Hit <b>{r.victims.slice(0, 3).join(", ")}</b>{r.victims.length > 3 ? ` +${r.victims.length - 3}` : ""}</span>}
            {r.attackers.length > 0 && <span>By <b>{r.attackers.slice(0, 3).join(", ")}</b></span>}
            {r.vendors.length > 0 && <span>Vendor <b>{r.vendors.slice(0, 2).join(", ")}</b></span>}
            {r.headline_usd != null && <span><b>{usd(r.headline_usd)}</b> {MONEY[r.headline_kind ?? ""] ?? "reported"}</span>}
            {r.records ? <span><b>{count(r.records)}</b> records</span> : null}
            {r.cves.length > 0 && <span className="mono">{r.cves.slice(0, 2).join(" ")}{r.cves.length > 2 ? ` +${r.cves.length - 2}` : ""}</span>}
          </div>
        )}
        {!compact && why.length > 0 && <div className="row-why">{why.map((x) => `${x.why} +${x.points}`).join(" · ")}</div>}
        {r.state.note && <div className="row-note">{r.state.note}</div>}
      </div>
    </article>
  );
}

export default memo(IncidentRow);
