import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, Camera, CircleStop, Download, Eraser, FileAudio, FlaskConical,
  Link, Link2Off, Pause, Play, RefreshCw, Search, Send, Speaker, Terminal,
  Upload, Volume2, Wifi, WifiOff,
} from "lucide-react";
import StackChanCanvas from "./StackChanCanvas";
import { enableAudio, playPcm } from "./audio";
import type { ApiCard, DeviceState, DriftItem, LogEntry } from "./types";

const EMPTY_STATE: DeviceState = {
  connected: false, deviceId: "stackchan-sim-001", sessionId: "", status: "offline", emotion: "neutral", subtitle: "",
  mouth: 0, yaw: 0, pitch: 45, speed: 250, volume: 65, mode: "idle", kidMode: true, smartMode: false,
  leds: Array(12).fill("#20252a"),
};
type Tab = "device" | "apis" | "events" | "logs";

export default function App() {
  const [tab, setTab] = useState<Tab>("device");
  const [state, setState] = useState<DeviceState>(EMPTY_STATE);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [cards, setCards] = useState<ApiCard[]>([]);
  const [drift, setDrift] = useState<DriftItem[]>([]);
  const [samples, setSamples] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [transport, setTransport] = useState({ uplinkFrames: 0, uplinkBytes: 0, downlinkFrames: 0, downlinkBytes: 0 });
  const [transcript, setTranscript] = useState({ user: "", assistant: "" });
  const [asrLanguage, setAsrLanguage] = useState("en");

  const loadCatalog = () => fetch("/api/catalog").then((r) => r.json()).then((data) => { setCards(data.cards || []); setDrift(data.drift || []); });
  useEffect(() => { loadCatalog(); fetch("/api/device/state").then((r) => r.json()).then((data) => { setState(data.state); setSamples(data.samples); setAsrLanguage(data.asrLanguage || "en"); }); }, []);
  useEffect(() => {
    let timer = 0;
    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${location.host}/ws/ui`);
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "snapshot") { setState(message.state); setLogs(message.logs || []); }
        if (message.type === "state") setState(message.state);
        if (message.type === "log") setLogs((old) => [...old.slice(-4998), message.entry]);
        if (message.type === "audio") playPcm(message.pcm);
        if (message.type === "transport") setTransport(message.transport);
        if (message.type === "transcript_reset") setTranscript({ user: "", assistant: "" });
        if (message.type === "transcript") setTranscript((old) => {
          const previous = message.reset ? "" : old[message.role as "user" | "assistant"];
          const text = message.append && previous ? `${previous} ${message.text}` : message.text;
          return { ...old, [message.role]: text };
        });
        if (message.type === "transcript" && message.role === "user") setNotice("STT received; waiting for reply");
        if (message.type === "transcript" && message.role === "assistant" && message.text) setNotice("Response received");
        if (message.type === "system") setNotice(`System: ${JSON.stringify(message.message)}`);
      };
      ws.onclose = () => { timer = window.setTimeout(connect, 1500); };
    };
    connect(); return () => window.clearTimeout(timer);
  }, []);

  async function command(path: string, body?: unknown, label = path) {
    setBusy(label); setNotice("");
    try {
      const response = await fetch(path, { method: "POST", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      setNotice(label.startsWith("Voice uploaded") ? "Voice uploaded; waiting for STT/TTS" : `${label}: ok`); return data;
    } catch (error) { setNotice(String((error as Error).message || error)); throw error; }
    finally { setBusy(""); }
  }

  async function runSmoke() {
    if (!confirm("Run health checks and read-only, no-cost protocol tests?")) return;
    const result = await command("/api/smoke", undefined, "Safe smoke");
    setNotice(`${result.results.filter((item: any) => item.ok).length}/${result.results.length} passed`);
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark">SC</span><div><strong>StackChan Simulator</strong><small>{state.deviceId}</small></div></div>
      <nav className="tabs" aria-label="Views">
        <button className={tab === "device" ? "active" : ""} onClick={() => setTab("device")}><Activity size={16}/>Device</button>
        <button className={tab === "apis" ? "active" : ""} onClick={() => setTab("apis")}><Terminal size={16}/>APIs <span>{cards.length}</span></button>
        <button className={tab === "events" ? "active" : ""} onClick={() => setTab("events")}><Send size={16}/>Events</button>
        <button className={tab === "logs" ? "active" : ""} onClick={() => setTab("logs")}><FileAudio size={16}/>Logs <span>{logs.length}</span></button>
      </nav>
      <div className="top-actions">
        <button className="icon-button" title="Enable audio playback" onClick={() => enableAudio().then(() => setNotice("Audio enabled"))}><Volume2 size={18}/></button>
        <button className="secondary" onClick={runSmoke} disabled={!!busy}><FlaskConical size={16}/>Safe smoke</button>
        <button className={state.connected ? "danger" : "primary"} disabled={!!busy} onClick={() => command(state.connected ? "/api/device/disconnect" : "/api/device/connect", undefined, state.connected ? "Disconnect" : "Connect")}>
          {state.connected ? <Link2Off size={16}/> : <Link size={16}/>} {state.connected ? "Disconnect" : "Connect"}
        </button>
      </div>
    </header>
    <div className="statusline">
      <span className={`dot ${state.connected ? "online" : ""}`}/><strong>{state.status}</strong>
      <span>Session {state.sessionId ? state.sessionId.slice(0, 10) : "none"}</span>
      <span>{state.emotion}</span><span>{state.mode}</span>
      {drift.length > 0 && <button onClick={() => setTab("apis")} className="drift-badge">API drift {drift.length}</button>}
      {notice && <span className="notice">{notice}</span>}
    </div>
    <main>
      {tab === "device" && <DeviceView state={state} samples={samples} command={command} busy={busy} transport={transport} transcript={transcript} asrLanguage={asrLanguage}/>} 
      {tab === "apis" && <ApiExplorer cards={cards} drift={drift} refresh={loadCatalog}/>} 
      {tab === "events" && <EventsView command={command}/>} 
      {tab === "logs" && <LogsView logs={logs} setLogs={setLogs}/>} 
    </main>
  </div>;
}

function DeviceView({ state, samples, command, busy, transport, transcript, asrLanguage }: { state: DeviceState; samples: string[]; command: (path: string, body?: unknown, label?: string) => Promise<any>; busy: string; transport: { uplinkFrames: number; uplinkBytes: number; downlinkFrames: number; downlinkBytes: number }; transcript: { user: string; assistant: string }; asrLanguage: string }) {
  const [sample, setSample] = useState(samples[0] || "en-greeting");
  const compatible = !sample.startsWith("zh-") || ["zh", "cmn", "auto", "multilingual"].includes(asrLanguage.toLowerCase());
  useEffect(() => { if (!samples.includes(sample) && samples[0]) setSample(samples[0]); }, [samples, sample]);
  async function uploadPhoto(file?: File) {
    if (!file) return; const form = new FormData(); form.set("file", file);
    const response = await fetch("/api/device/photo", { method: "POST", body: form });
    if (!response.ok) alert((await response.json()).error || "Upload failed");
  }
  return <div className="device-layout">
    <section className="sim-stage">
      <StackChanCanvas state={state}/>
      <div className="subtitle"><span>{state.status}</span>{state.subtitle || "StackChan simulator ready"}</div>
    </section>
    <aside className="control-rail">
      <section className="control-section">
        <div className="section-title"><Speaker size={17}/><h2>Voice channel</h2></div>
        <label>Sample<select value={sample} onChange={(e) => setSample(e.target.value)}>{samples.map((name) => <option key={name} value={name}>{name}{name.startsWith("zh-") ? " (multilingual ASR)" : ""}</option>)}</select></label>
        {!compatible && <small>ASR mismatch: server language is {asrLanguage}</small>}
        <div className="button-row">
          <button className="primary grow" disabled={!state.connected || !!busy || !compatible} onClick={async () => { await enableAudio(); await command("/api/device/audio/send", { name: sample }, `Voice uploaded (${sample})`); }}><Play size={16}/>Send voice</button>
          <button className="secondary" disabled={!!busy} onClick={() => { if (confirm("Audio explanation may call a paid model. Continue?")) command("/api/device/audio/explain", { name: sample }, "Explain audio"); }}><FileAudio size={16}/></button>
        </div>
      </section>
      <section className="control-section telemetry">
        <div className="section-title"><Activity size={17}/><h2>Telemetry</h2></div>
        <dl><div><dt>Yaw</dt><dd>{state.yaw}°</dd></div><div><dt>Pitch</dt><dd>{state.pitch}°</dd></div><div><dt>Speed</dt><dd>{state.speed}</dd></div><div><dt>Volume</dt><dd>{state.volume}%</dd></div><div><dt>Audio TX</dt><dd>{transport.uplinkFrames}f</dd></div><div><dt>Audio RX</dt><dd>{transport.downlinkFrames}f</dd></div></dl>
        <div className="toggle-row"><span>Kid</span><b className={state.kidMode ? "on" : ""}>{state.kidMode ? "ON" : "OFF"}</b><span>Smart</span><b className={state.smartMode ? "on" : ""}>{state.smartMode ? "ON" : "OFF"}</b></div>
      </section>
      <section className="control-section telemetry">
        <div className="section-title"><Terminal size={17}/><h2>Transcript</h2></div>
        <dl><div><dt>Heard</dt><dd>{transcript.user || "—"}</dd></div><div><dt>Reply</dt><dd>{transcript.assistant || "—"}</dd></div></dl>
      </section>
      <section className="control-section">
        <div className="section-title"><Camera size={17}/><h2>Camera scene</h2></div>
        <label className="upload-button"><Upload size={16}/>Replace next photo<input type="file" accept="image/jpeg,image/png" onChange={(event) => uploadPhoto(event.target.files?.[0])}/></label>
      </section>
      <section className="control-section led-section">
        <div className="section-title"><Wifi size={17}/><h2>LED ring</h2></div>
        <div className="led-row">{state.leds.map((color, i) => <i key={i} style={{ background: color, boxShadow: `0 0 10px ${color}` }}/>)}</div>
      </section>
    </aside>
  </div>;
}

function ApiExplorer({ cards, drift, refresh }: { cards: ApiCard[]; drift: DriftItem[]; refresh: () => void }) {
  const [search, setSearch] = useState(""); const [service, setService] = useState("all"); const [selectedId, setSelectedId] = useState("");
  const selected = cards.find((card) => card.id === selectedId) || cards[0];
  const filtered = cards.filter((card) => (service === "all" || card.service === service) && `${card.method} ${card.path} ${card.summary}`.toLowerCase().includes(search.toLowerCase()));
  useEffect(() => { if (!selectedId && cards[0]) setSelectedId(cards[0].id); }, [cards, selectedId]);
  return <div className="api-layout">
    <aside className="api-list">
      <div className="search"><Search size={16}/><input placeholder="Search APIs" value={search} onChange={(e) => setSearch(e.target.value)}/><button className="icon-button" title="Refresh OpenAPI" onClick={refresh}><RefreshCw size={15}/></button></div>
      <div className="service-filter">{["all", "behaviour", "bridge", "xiaozhi", "dotty-pi"].map((name) => <button className={service === name ? "active" : ""} onClick={() => setService(name)} key={name}>{name}</button>)}</div>
      <div className="api-scroll">{filtered.map((card) => <button className={`api-row ${selected?.id === card.id ? "selected" : ""}`} key={card.id} onClick={() => setSelectedId(card.id)}><span className={`method ${card.method.toLowerCase()}`}>{card.method}</span><span><strong>{card.path}</strong><small>{card.summary}</small></span><i className={`risk ${card.risk}`}>{card.risk}</i></button>)}</div>
    </aside>
    <section className="api-detail">{selected && <ApiRunner key={selected.id} card={selected}/>}</section>
    <aside className="drift-panel"><div className="section-title"><Activity size={17}/><h2>Contract drift</h2></div>{drift.length === 0 ? <p className="empty">Runtime OpenAPI matches the catalog.</p> : drift.map((item, index) => <div className="drift-row" key={`${item.service}-${item.path}-${index}`}><b>{item.kind}</b><span>{item.service}</span><code>{item.method} {item.path}</code></div>)}</aside>
  </div>;
}

function ApiRunner({ card }: { card: ApiCard }) {
  const [params, setParams] = useState<Record<string, string>>(() => Object.fromEntries((card.parameters || []).map((p) => [p.name, p.name === "device_id" || p.name === "Device-Id" ? "stackchan-sim-001" : p.name === "limit" ? "5" : ""])));
  const [body, setBody] = useState(JSON.stringify(card.defaultBody ?? {}, null, 2)); const [file, setFile] = useState<File>(); const [result, setResult] = useState<any>(); const [running, setRunning] = useState(false);
  async function run() {
    if (card.risk !== "safe" && !confirm(`${card.risk.toUpperCase()} request: ${card.method} ${card.path}. Continue?`)) return;
    setRunning(true); setResult(undefined);
    try {
      const payload: any = { path: {}, query: {}, headers: {}, body: body.trim() ? JSON.parse(body) : {} };
      for (const parameter of card.parameters || []) {
        const bucket = parameter.in === "header" ? "headers" : parameter.in;
        payload[bucket][parameter.name] = params[parameter.name];
      }
      if (file) payload.file = { name: file.name, mime: file.type, data: await fileBase64(file) };
      const response = await fetch(`/api/execute/${card.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      setResult(await response.json());
    } catch (error) { setResult({ error: String((error as Error).message || error) }); }
    finally { setRunning(false); }
  }
  return <>
    <div className="api-heading"><div><span className={`method ${card.method.toLowerCase()}`}>{card.method}</span><code>{card.path}</code></div><i className={`risk ${card.risk}`}>{card.risk}</i></div>
    <h1>{card.summary}</h1><p className="service-name">{card.service} · {card.id}</p>
    {(card.parameters || []).length > 0 && <div className="parameter-grid">{card.parameters!.map((parameter) => <label key={`${parameter.in}-${parameter.name}`}><span>{parameter.name}<small>{parameter.in}{parameter.required ? " · required" : ""}</small></span><input value={params[parameter.name] || ""} onChange={(e) => setParams({ ...params, [parameter.name]: e.target.value })}/></label>)}</div>}
    {card.method !== "GET" && <label className="editor-label">JSON body<textarea spellCheck={false} value={body} onChange={(e) => setBody(e.target.value)}/></label>}
    {card.contentType === "multipart" && <label className="upload-button compact"><Upload size={16}/>{file?.name || "Select file"}<input type="file" onChange={(event) => setFile(event.target.files?.[0])}/></label>}
    <button className="primary execute" disabled={running} onClick={run}>{running ? <RefreshCw className="spin" size={17}/> : <Send size={17}/>}Execute</button>
    {result && <div className="response"><div className="response-meta"><b className={result.ok ? "ok" : "bad"}>{result.status || "ERROR"}</b>{result.durationMs != null && <span>{result.durationMs} ms</span>}<span>{result.contentType}</span></div>
      {result.encoding === "base64" && result.contentType?.startsWith("image/") && <img className="response-image" src={`data:${result.contentType};base64,${result.body}`} alt="API response"/>}
      {result.encoding === "base64" && result.contentType?.startsWith("audio/") && <audio className="response-audio" controls src={`data:${result.contentType};base64,${result.body}`}/>} 
      {!(result.encoding === "base64" && /^(image|audio)\//.test(result.contentType || "")) && <pre>{JSON.stringify(result.body ?? result, null, 2)}</pre>}
      {result.headers && <details className="response-headers"><summary>Response headers</summary><pre>{JSON.stringify(result.headers, null, 2)}</pre></details>}
    </div>}
  </>;
}

function EventsView({ command }: { command: (path: string, body?: unknown, label?: string) => Promise<any> }) {
  const presets = [
    ["Face detected", "face_detected", { confidence: .96 }], ["Face lost", "face_lost", {}], ["Sound left", "sound_event", { direction: "left", confidence: .88 }],
    ["Wake word", "wake_word", { word: "Hi StackChan" }], ["Head pet", "head_pet_started", {}], ["State dance", "state_changed", { state: "dance" }],
    ["Dance started", "dance_started", {}], ["Chat active", "chat_status", { status: "active" }],
  ] as const;
  const [raw, setRaw] = useState(JSON.stringify({ name: "face_detected", data: { confidence: 0.96 } }, null, 2));
  const [mcp, setMcp] = useState(JSON.stringify({ jsonrpc: "2.0", method: "tools/list", params: { cursor: "", withUserTools: false }, id: 99 }, null, 2));
  return <div className="events-layout">
    <section><div className="section-title"><Send size={17}/><h2>Event presets</h2></div><div className="preset-grid">{presets.map(([label, name, data]) => <button className="preset" key={label} onClick={() => command("/api/device/event", { name, data }, label)}><span>{label}</span><code>{name}</code></button>)}</div></section>
    <section><div className="section-title"><Terminal size={17}/><h2>Raw event</h2></div><textarea className="raw-editor" value={raw} onChange={(e) => setRaw(e.target.value)}/><button className="primary" onClick={() => command("/api/device/event", JSON.parse(raw), "Raw event")}><Send size={16}/>Send event</button></section>
    <section><div className="section-title"><Terminal size={17}/><h2>Raw MCP</h2></div><textarea className="raw-editor" value={mcp} onChange={(e) => setMcp(e.target.value)}/><button className="secondary" onClick={() => command("/api/device/mcp", JSON.parse(mcp), "Raw MCP")}><Send size={16}/>Send MCP</button></section>
  </div>;
}

function LogsView({ logs, setLogs }: { logs: LogEntry[]; setLogs: (logs: LogEntry[]) => void }) {
  const [filter, setFilter] = useState(""); const [paused, setPaused] = useState(false); const frozen = useRef<LogEntry[]>([]); const end = useRef<HTMLDivElement>(null);
  if (!paused) frozen.current = logs;
  const shown = useMemo(() => frozen.current.filter((entry) => JSON.stringify(entry).toLowerCase().includes(filter.toLowerCase())), [logs, filter, paused]);
  useEffect(() => { if (!paused) end.current?.scrollIntoView({ block: "end" }); }, [logs, paused]);
  async function clear() { await fetch("/api/logs", { method: "DELETE" }); setLogs([]); frozen.current = []; }
  return <div className="logs-view"><div className="log-toolbar"><div className="search"><Search size={16}/><input placeholder="Filter logs" value={filter} onChange={(e) => setFilter(e.target.value)}/></div><button className="secondary" onClick={() => setPaused(!paused)}>{paused ? <Play size={16}/> : <Pause size={16}/>} {paused ? "Resume" : "Pause"}</button><a className="secondary button-link" href="/api/logs/export"><Download size={16}/>JSONL</a><button className="danger" onClick={clear}><Eraser size={16}/>Clear</button></div><div className="log-table"><div className="log-head"><span>Time</span><span>Dir</span><span>Service</span><span>Kind</span><span>Summary</span><span>Size / time</span></div>{shown.map((entry) => <details className="log-row" key={entry.id}><summary><time>{entry.ts.slice(11, 23)}</time><b className={`dir ${entry.direction}`}>{entry.direction}</b><span>{entry.service}</span><code>{entry.kind}</code><span>{entry.summary}</span><small>{entry.binaryLength ? `${entry.binaryLength} B` : ""}{entry.durationMs != null ? ` ${entry.durationMs} ms` : ""}</small></summary>{entry.payload !== undefined && <pre>{JSON.stringify(entry.payload, null, 2)}</pre>}</details>)}<div ref={end}/></div></div>;
}

function fileBase64(file: File): Promise<string> { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onerror = () => reject(reader.error); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.readAsDataURL(file); }); }
