import { useEffect, useState } from "react";
import { api, type Interest, type Profile } from "../api";

const LISTS: [keyof Profile, string, string][] = [
  ["aliases", "Our names", "Every name the organisation goes by. An incident that names one scores +60."],
  ["own_tools", "Tools we build on", "Our own tools and the ones we fork. Named in a story: +40."],
  ["suppliers", "Suppliers", "Companies we depend on. One of them hit: +40."],
  ["stack", "Software we run", "Vendors and products. Their flaws: +25, exploited +20 more."],
  ["peers", "Peers", "Companies in our field. One of them hit: +15."],
  ["actors", "Groups we watch", "Groups and people. Named: +15."],
  ["sectors", "Our sectors", "A victim in one of them: +12."],
];

const lines = (v: string) => v.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
/** "Name: points" lines as a record (the last colon divides: "NCSC UK: 6"). */
const weights = (v: string) => Object.fromEntries(v.split("\n").map((l) => [l.slice(0, l.lastIndexOf(":")).trim(), Number(l.slice(l.lastIndexOf(":") + 1)) || 5] as const)
  .filter(([name]) => name));

export default function ProfileView({ onSaved }: { onSaved: () => void }) {
  const [p, setP] = useState<Profile | null>(null);
  const [text, setText] = useState<Record<string, string>>({});
  const [countries, setCountries] = useState("");
  const [authorities, setAuthorities] = useState("");
  const [interests, setInterests] = useState<Interest[]>([]);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.profile().then((pr) => {
      setP(pr);
      setText(Object.fromEntries(LISTS.map(([k]) => [k, (pr[k] as string[]).join("\n")])));
      setCountries(Object.entries(pr.countries).map(([c, w]) => `${c}: ${w}`).join("\n"));
      setAuthorities(Object.entries(pr.authorities ?? {}).map(([c, w]) => `${c}: ${w}`).join("\n"));
      setInterests(pr.interests);
    });
  }, []);
  if (!p) return <div className="view"><p className="muted">Loading</p></div>;

  const save = () => {
    const next: Profile = {
      ...p,
      ...Object.fromEntries(LISTS.map(([k]) => [k, lines(text[k] ?? "")])),
      countries: weights(countries),
      authorities: weights(authorities),
      interests: interests.filter((i) => i.name.trim()),
    } as Profile;
    api.saveProfile(next).then((saved) => { setP(saved); setMsg("Saved. Every incident is scored again."); onSaved(); })
      .catch((e) => setMsg(`Not saved: ${e}`));
  };

  return (
    <div className="view">
      <h2>Who "us" is</h2>
      <p className="note">Relevance is scored against this. The first version is an example to start from (a made-up organisation, and the
        team's ARTEX, mara and ai-course-thingy projects): correct it and save.</p>
      <div className="form" style={{ marginTop: 12 }}>
        <label>Organisation</label>
        <input className="field" value={p.organization} onChange={(e) => setP({ ...p, organization: e.target.value })} />
        {LISTS.map(([k, label, help]) => (
          <div key={k} style={{ display: "contents" }}>
            <label>{label}</label>
            <div>
              <textarea value={text[k] ?? ""} onChange={(e) => setText({ ...text, [k]: e.target.value })} />
              <div className="faint small">{help} One per line.</div>
            </div>
          </div>
        ))}
        <label>Countries</label>
        <div>
          <textarea value={countries} onChange={(e) => setCountries(e.target.value)} />
          <div className="faint small">"Country: points" per line. An incident in that country scores the points.</div>
        </div>
        <label>Authorities</label>
        <div>
          <textarea value={authorities} onChange={(e) => setAuthorities(e.target.value)} />
          <div className="faint small">"Source: points" per line, the source named as in the Sources view. An advisory of theirs on an incident scores the points.</div>
        </div>
        <label>What we work on</label>
        <div>
          {interests.map((it, i) => (
            <div className="interest" key={i}>
              <input className="field" value={it.name} placeholder="topic" onChange={(e) => setInterests(interests.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <input className="field" value={it.project} placeholder="project" onChange={(e) => setInterests(interests.map((x, j) => (j === i ? { ...x, project: e.target.value } : x)))} />
              <input className="field" type="number" value={it.points} onChange={(e) => setInterests(interests.map((x, j) => (j === i ? { ...x, points: Number(e.target.value) } : x)))} />
              <textarea value={it.keywords.join("\n")} onChange={(e) => setInterests(interests.map((x, j) => (j === i ? { ...x, keywords: lines(e.target.value) } : x)))} />
            </div>
          ))}
          <button className="btn" onClick={() => setInterests([...interests, { name: "", project: "", points: 10, keywords: [] }])}>Add a topic</button>
          <div className="faint small">A story or tool whose text holds one of the words scores the topic's points.</div>
        </div>
        <span />
        <div><button className="btn on" onClick={save}>Save</button> <span className="muted small">{msg}</span></div>
      </div>
    </div>
  );
}
