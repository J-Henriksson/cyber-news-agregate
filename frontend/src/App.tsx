import { useCallback, useEffect, useRef, useState } from "react";
import { ago, api, SNAPSHOT, watchReach, type Desk, type SourcesView } from "./api";
import IncidentPanel from "./components/IncidentPanel";
import BriefView from "./views/Brief";
import Feed from "./views/Feed";
import Graph from "./views/Graph";
import Companies from "./views/Companies";
import Money from "./views/Money";
import Timeline from "./views/Timeline";
import Sources from "./views/Sources";
import ProfileView from "./views/Profile";

const VIEWS = [
  ["brief", "Brief"],
  ["feed", "Feed"],
  ["graph", "Graph"],
  ["companies", "Companies"],
  ["money", "Money"],
  ["timeline", "Timeline"],
] as const;
const ADMIN_ALL = [
  ["sources", "Sources"],
  ["profile", "Profile"],
] as const;
// A copy has no profile to edit: who "us" is stays on the machine that made it.
const ADMIN = ADMIN_ALL.filter(([k]) => !SNAPSHOT || k !== "profile");
type View = (typeof VIEWS)[number][0] | (typeof ADMIN_ALL)[number][0];
const ALL_VIEWS = [...VIEWS, ...ADMIN].map(([k]) => k) as readonly string[];
/** 0 is "today": since midnight, by this computer's clock. */
const WINDOWS = [0, 3, 7, 14, 30, 90];
/** An incident at least this relevant raises a desktop alert, when alerts are on. */
const ALERT_AT = 50;

function midnight(): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* a private window: not remembered */
  }
}

interface Place { view: View; days: number; desk: Desk; q: string; selected: string | null }

/** Where the page is, read from the address: #feed?d=14&desk=ai&q=akira&i=abc123. */
function readPlace(): Place {
  const [name, rest] = location.hash.slice(1).split("?");
  const p = new URLSearchParams(rest ?? "");
  const days = Number(p.get("d") ?? "14");
  const desk = (p.get("desk") ?? stored("radar.desk") ?? "") as Desk;
  return {
    view: (ALL_VIEWS.includes(name) ? name : "brief") as View,
    days: WINDOWS.includes(days) ? days : 14,
    desk: desk === "cyber" || desk === "ai" ? desk : "",
    q: p.get("q") ?? "",
    selected: p.get("i"),
  };
}

function writePlace(pl: Place): string {
  const p = new URLSearchParams();
  if (pl.days !== 14) p.set("d", String(pl.days));
  if (pl.desk) p.set("desk", pl.desk);
  if (pl.q) p.set("q", pl.q);
  if (pl.selected) p.set("i", pl.selected);
  const rest = p.toString();
  return `#${pl.view}${rest ? `?${rest}` : ""}`;
}

export default function App() {
  const [place, setPlace] = useState<Place>(readPlace);
  const { view, days, desk, q, selected } = place;
  const [status, setStatus] = useState<SourcesView | null>(null);
  // Bumped when the backend says something changed: the open view fetches again.
  const [tick, setTick] = useState(0);
  const [live, setLive] = useState(false);
  const [reachable, setReachable] = useState(true);
  // Incidents with something new since the page opened, until looked at.
  const [fresh, setFresh] = useState<Map<string, FreshIncident>>(new Map());
  const [alerts, setAlerts] = useState(() => stored("radar.alerts") === "on" && "Notification" in window && Notification.permission === "granted");
  const alertsRef = useRef(alerts);
  alertsRef.current = alerts;
  const searchRef = useRef<HTMLInputElement>(null);

  const go = useCallback((change: Partial<Place>) => setPlace((p) => ({ ...p, ...change })), []);

  // The address follows the page (a new entry for a new view, the same entry otherwise), and the page the address.
  useEffect(() => {
    const next = writePlace(place);
    if (location.hash === next) return;
    if (location.hash.slice(1).split("?")[0] !== place.view) location.hash = next;
    else history.replaceState(null, "", next);
  }, [place]);
  useEffect(() => {
    const follow = () => setPlace((p) => {
      const next = readPlace();
      return writePlace(p) === writePlace(next) ? p : next;
    });
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  useEffect(() => store("radar.desk", desk), [desk]);

  const loadStatus = useCallback(() => {
    api.sources().then(setStatus).catch(() => undefined);
  }, []);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    watchReach(setReachable);
    loadStatus();
    // A copy does not change while it is open: nothing to listen for.
    if (SNAPSHOT) return;
    // The backend pushes; this only keeps "read 3 min ago" in the status current.
    const t = setInterval(loadStatus, 5 * 60_000);
    const events = new EventSource("/api/events");
    events.onopen = () => setLive(true);
    events.onerror = () => setLive(false); // EventSource reconnects by itself
    events.addEventListener("hello", () => {
      setLive(true);
      // Back after a gap (the laptop slept, the backend restarted): catch up.
      setTick((n) => n + 1);
      loadStatus();
    });
    events.addEventListener("status", loadStatus);
    events.addEventListener("state", () => setTick((n) => n + 1));
    events.addEventListener("change", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { new: FreshIncident[] };
      setTick((n) => n + 1);
      loadStatus();
      if (!d.new.length) return;
      setFresh((prev) => {
        const next = new Map(prev);
        for (const inc of d.new) next.set(inc.id, inc);
        return next;
      });
      if (alertsRef.current) {
        for (const inc of d.new.filter((i) => i.relevance >= ALERT_AT).slice(0, 3)) {
          const n = new Notification(`${inc.relevance} · ${inc.category}`, { body: inc.title, tag: inc.id });
          n.onclick = () => {
            window.focus();
            setPlace((p) => ({ ...p, view: "feed", selected: inc.id }));
          };
        }
      }
    });
    return () => {
      clearInterval(t);
      events.close();
    };
  }, [loadStatus]);

  const open = useCallback((id: string) => {
    setPlace((p) => ({ ...p, selected: id }));
    setFresh((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Map(prev);
      next.delete(id);
      return next;
    });
  }, []);
  const close = useCallback(() => setPlace((p) => ({ ...p, selected: null })), []);

  // Keys: / to search, Esc to close. (The feed adds j, k, s and x.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "Escape") {
        if (typing) (e.target as HTMLElement).blur();
        else close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  useEffect(() => {
    document.title = `${fresh.size ? `(${fresh.size}) ` : ""}cyber-news-agregate`;
  }, [fresh]);

  const toggleAlerts = async () => {
    if (alerts) {
      setAlerts(false);
      store("radar.alerts", "off");
      return;
    }
    if (!("Notification" in window)) return;
    const granted = Notification.permission === "granted" || (await Notification.requestPermission()) === "granted";
    setAlerts(granted);
    store("radar.alerts", granted ? "on" : "off");
  };

  const failing = status?.sources.filter((s) => s.error).length ?? 0;
  const pending = status?.model.states.pending ?? 0;
  // Today: the views ask for what was told since midnight (worked out afresh each time).
  const since = days === 0 ? (SNAPSHOT ? SNAPSHOT.midnight : midnight()) : undefined;
  const label = days === 0 ? "today" : `the last ${days} days`;
  const props: ViewProps = { days: days === 0 ? 1 : days, since, label, q, tick, selected, onSelect: open, fresh, desk, refresh };
  const freshTop = [...fresh.values()].sort((a, b) => b.relevance - a.relevance)[0];
  const alertsBlocked = "Notification" in window && Notification.permission === "denied";

  return (
    <div className="app">
      <header className="top">
        <span className="seg" role="group" aria-label="Desk">
          {([["", "All"], ["cyber", "Cyber"], ["ai", "AI"]] as const).map(([k, name]) => (
            <button key={k} className={`btn ${desk === k ? "on" : ""}`} aria-pressed={desk === k} onClick={() => go({ desk: k })}>{name}</button>
          ))}
        </span>
        <span className="seg" role="group" aria-label="Window">
          {WINDOWS.map((d) => (
            <button key={d} className={`btn ${d === days ? "on" : ""}`} aria-pressed={d === days} onClick={() => go({ days: d })}>{d === 0 ? "Today" : `${d} d`}</button>
          ))}
        </span>
        <input ref={searchRef} className="search" placeholder="Search: company, group, CVE, source  ( / )" aria-label="Search"
          value={q} onChange={(e) => go({ q: e.target.value })} />
        <span className="spacer" />
        {fresh.size > 0 && (
          <button className="btn solid" title={freshTop ? `${freshTop.relevance} · ${freshTop.title}` : ""}
            onClick={() => { go({ view: "feed" }); if (freshTop) open(freshTop.id); }}>
            {fresh.size} new{freshTop && freshTop.relevance >= 40 ? `, top ${freshTop.relevance}` : ""}
          </button>
        )}
        {SNAPSHOT && (
          <span className="health copy" title={`A read-only copy of the page as it stood ${new Date(SNAPSHOT.at * 1000).toLocaleString()}. Its windows end there, and "Today" is that day.`}>
            <i className="lamp" />
            Copy, made {ago(SNAPSHOT.at)}
            {status && <span>{status.sources.length - failing}/{status.sources.length} sources</span>}
          </span>
        )}
        {!SNAPSHOT && status && (
          <span className={`health ${live ? "" : "down"}`}
            title={[`${status.sources.length - failing} of ${status.sources.length} sources answering`,
              status.model.key ? `model: ${status.model.today.calls} of ${status.model.daily_calls} calls today, ${pending} items waiting` : "no model key: the rules alone read the items",
              status.busy.length ? `reading ${status.busy.join(", ")}` : ""].filter(Boolean).join("\n")}>
            <i className="lamp" />
            {live ? "Live" : "Reconnecting"}
            <span>{status.sources.length - failing}/{status.sources.length} sources</span>
            {failing > 0 && <span className="bad">{failing} failing</span>}
            {status.busy.length > 0 && <span>reading {status.busy.length}</span>}
          </span>
        )}
        {!SNAPSHOT && (
          <>
            <button className={`btn ${alerts ? "on" : ""}`} onClick={toggleAlerts} disabled={alertsBlocked} aria-pressed={alerts}
              title={alertsBlocked ? "This browser blocks notifications for this page" : `A desktop alert for each new incident of relevance ${ALERT_AT} or more`}>
              Alerts {alerts ? "on" : "off"}
            </button>
            <button className="btn" onClick={() => api.refresh()} title="Read every source not read in the last two minutes">Read now</button>
          </>
        )}
      </header>
      {!reachable && (
        <div className="banner" role="alert">{SNAPSHOT ? "The page's data could not be fetched. Check the connection and reload."
          : "The backend is not answering. Start it with ./run.sh in the cyber-news-agregate folder; the page reconnects by itself."}</div>
      )}
      <nav className="nav" aria-label="Views">
        {VIEWS.map(([k, name]) => (
          <button key={k} className={view === k ? "on" : ""} aria-current={view === k} onClick={() => go({ view: k })}>
            <span>{name}</span>{k === "feed" && fresh.size > 0 && <em>{fresh.size}</em>}
          </button>
        ))}
        <div className="sep" />
        {ADMIN.map(([k, name]) => (
          <button key={k} className={view === k ? "on" : ""} aria-current={view === k} onClick={() => go({ view: k })}>
            <span>{name}</span>{k === "sources" && failing > 0 && <em>{failing}</em>}
          </button>
        ))}
        <div className="keys" aria-hidden="true">
          <span><kbd>/</kbd> search</span>
          <span><kbd>j</kbd> <kbd>k</kbd> move</span>
          {!SNAPSHOT && <span><kbd>s</kbd> star</span>}
          {!SNAPSHOT && <span><kbd>x</kbd> dismiss</span>}
          <span><kbd>Esc</kbd> close</span>
        </div>
      </nav>
      <main className="main">
        {view === "brief" && <BriefView {...props} onView={(v) => go({ view: v as View })} />}
        {view === "feed" && <Feed {...props} />}
        {view === "graph" && <Graph {...props} />}
        {view === "companies" && <Companies {...props} />}
        {view === "money" && <Money {...props} />}
        {view === "timeline" && <Timeline {...props} />}
        {view === "sources" && <Sources tick={tick} />}
        {view === "profile" && !SNAPSHOT && <ProfileView onSaved={refresh} />}
        {selected && <IncidentPanel id={selected} tick={tick} onClose={close} onSelect={open} refresh={refresh} />}
      </main>
    </div>
  );
}

export interface ViewProps {
  days: number;
  q: string;
  tick: number;
  selected: string | null;
  onSelect: (id: string) => void;
  fresh: Map<string, FreshIncident>;
  desk: Desk;
  /** Set for "today": what was told since this moment (epoch seconds), not the last ``days``. */
  since?: number;
  /** The window in words: "today", "the last 14 days". */
  label: string;
  /** Fetch again (after the reader starred or dismissed something). */
  refresh: () => void;
}

export interface FreshIncident { id: string; title: string; relevance: number; category: string }
