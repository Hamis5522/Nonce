import { useState, useEffect, useRef, useCallback } from "react";

// ════════════════════════════════════════════════════════════════════════════
// DESIGN TOKENS — extending the existing NONCE brand system
// ════════════════════════════════════════════════════════════════════════════
const T = {
  black:       "#08090C",
  surface:     "#0F1117",
  surfaceHi:   "#161B27",
  surfaceHi2:  "#1C2230",
  border:      "#1E2536",
  borderHi:    "#2A3348",
  indigo:      "#6366F1",
  indigoLight: "#818CF8",
  indigoDim:   "#4338CA",
  indigoGlow:  "rgba(99,102,241,0.15)",
  indigoGlow2: "rgba(99,102,241,0.07)",
  green:       "#10B981",
  greenGlow:   "rgba(16,185,129,0.12)",
  red:         "#EF4444",
  amber:       "#F59E0B",
  textPrimary: "#F1F5F9",
  textMid:     "#94A3B8",
  textDim:     "#475569",
  display:     "'Space Grotesk', system-ui, sans-serif",
  body:        "'Inter', system-ui, sans-serif",
  mono:        "'JetBrains Mono', 'Fira Code', monospace",
};

// ════════════════════════════════════════════════════════════════════════════
// LOGO
// ════════════════════════════════════════════════════════════════════════════
function NonceMark({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <circle cx="20" cy="20" r="17" stroke={T.indigo} strokeWidth="2" fill="none" />
      <circle cx="20" cy="20" r="8" stroke={T.indigo} strokeWidth="1.5" fill="none" />
      <line x1="11" y1="29" x2="29" y2="11" stroke={T.indigo} strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
function Wordmark({ size = 20 }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
      <NonceMark size={size * 1.15} />
      <span style={{ fontFamily: T.display, fontWeight: 700, fontSize: size, letterSpacing: "-0.04em", color: T.textPrimary, lineHeight: 1 }}>
        nonce
      </span>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// LIVE BACKEND — real fetch() calls to the deployed NONCE API on Render.
// Same call signature as the old simulateApi(), so every call site below
// works unchanged: callApi(method, path, body) -> { status, body }
// ════════════════════════════════════════════════════════════════════════════

// ⚠️ SET THIS to your actual Render URL once deployed, e.g.:
// const API_BASE = "https://nonce-api-xxxx.onrender.com";
const API_BASE = "https://nonce-api-hox1.onrender.com";

async function callApi(method, path, body = null) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body && method !== "GET" ? JSON.stringify(body) : undefined,
    });
    let data;
    try { data = await res.json(); }
    catch { data = { error: "Invalid response from server" }; }
    return { status: res.status, body: data };
  } catch (err) {
    // Network failure, CORS block, or Render cold-start timeout
    return {
      status: 0,
      body: {
        error: "Could not reach the NONCE API. It may be waking up from idle — try again in a few seconds.",
        code: "NETWORK_ERROR",
        detail: err.message,
      },
    };
  }
}

// Quick reachability check, used to show a "waking up" banner on first load
// instead of letting the user's first real request silently eat the cold-start delay.
async function pingApi(timeoutMs = 4000) {
  try {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), timeoutMs);
    const res = await fetch(`${API_BASE}/health`, { signal: controller.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

// ════════════════════════════════════════════════════════════════════════════
// SHARED UI ATOMS
// ════════════════════════════════════════════════════════════════════════════
function useReveal() {
  const ref = useRef(null);
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVis(true); }, { threshold: 0.12 });
    if (ref.current) obs.observe(ref.current);
    return () => obs.disconnect();
  }, []);
  return [ref, vis];
}
function Reveal({ children, style = {}, delay = 0 }) {
  const [ref, vis] = useReveal();
  return (
    <div ref={ref} style={{
      opacity: vis ? 1 : 0,
      transform: vis ? "translateY(0)" : "translateY(20px)",
      transition: `opacity 0.6s ease ${delay}ms, transform 0.6s ease ${delay}ms`,
      ...style,
    }}>{children}</div>
  );
}

function Counter({ target, suffix = "", decimals = 0 }) {
  const [val, setVal] = useState(0);
  const ref = useRef(null);
  const started = useRef(false);
  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !started.current) {
        started.current = true;
        const start = Date.now(); const dur = 1700;
        const tick = () => {
          const p = Math.min((Date.now() - start) / dur, 1);
          const eased = 1 - Math.pow(1 - p, 3);
          setVal(eased * target);
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }
    }, { threshold: 0.4 });
    if (ref.current) obs.observe(ref.current);
    return () => obs.disconnect();
  }, [target]);
  return <span ref={ref}>{decimals ? val.toFixed(decimals) : Math.round(val).toLocaleString()}{suffix}</span>;
}

function Btn({ variant = "primary", children, onClick, small, style = {} }) {
  const base = {
    border: "none", borderRadius: 8, fontFamily: T.body, fontWeight: 600,
    fontSize: small ? 13 : 15, padding: small ? "7px 16px" : "12px 26px",
    cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6,
    transition: "all 0.15s", whiteSpace: "nowrap",
  };
  const variants = {
    primary: { background: T.indigo, color: "#fff" },
    secondary: { background: "transparent", color: T.textPrimary, border: `1px solid ${T.border}` },
    ghost: { background: "transparent", color: T.indigoLight, border: `1px solid ${T.indigo}33` },
  };
  return (
    <button onClick={onClick} style={{ ...base, ...variants[variant], ...style }}
      onMouseEnter={e => { e.currentTarget.style.opacity = "0.85"; e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={e => { e.currentTarget.style.opacity = "1"; e.currentTarget.style.transform = "translateY(0)"; }}>
      {children}
    </button>
  );
}

function CodeBlock({ children, style = {} }) {
  return (
    <pre style={{ background: T.black, border: `1px solid ${T.border}`, borderRadius: 8, padding: "16px 18px", fontFamily: T.mono, fontSize: 12.5, lineHeight: 1.75, color: T.textMid, overflowX: "auto", margin: 0, ...style }}>
      <code>{children}</code>
    </pre>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// NAVIGATION
// ════════════════════════════════════════════════════════════════════════════
function Nav({ page, setPage }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const fn = () => setScrolled(window.scrollY > 30);
    window.addEventListener("scroll", fn);
    return () => window.removeEventListener("scroll", fn);
  }, []);
  const links = [
    { id: "home", label: "Home" },
    { id: "docs", label: "Docs" },
    { id: "pricing", label: "Pricing" },
    { id: "company", label: "Company" },
  ];
  return (
    <nav style={{
      position: "fixed", top: 0, left: 0, right: 0, zIndex: 300,
      background: scrolled ? `${T.black}ee` : "transparent",
      backdropFilter: scrolled ? "blur(16px)" : "none",
      borderBottom: scrolled ? `1px solid ${T.border}` : "1px solid transparent",
      transition: "all 0.3s", padding: "0 5%", height: 60,
      display: "flex", alignItems: "center", justifyContent: "space-between",
    }}>
      <div style={{ cursor: "pointer" }} onClick={() => setPage("home")}>
        <Wordmark size={19} />
      </div>
      <div className="nonce-nav-links" style={{ display: "flex", gap: 30, alignItems: "center" }}>
        {links.map(l => (
          <span key={l.id} onClick={() => setPage(l.id)} style={{
            fontFamily: T.body, fontSize: 14, cursor: "pointer",
            color: page === l.id ? T.textPrimary : T.textMid,
            borderBottom: page === l.id ? `1px solid ${T.indigo}` : "1px solid transparent",
            paddingBottom: 4, transition: "color 0.15s",
          }}>{l.label}</span>
        ))}
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <Btn variant="secondary" small onClick={() => setPage("docs")}>Log in</Btn>
        <Btn variant="primary" small onClick={() => setPage("docs")}>Get started</Btn>
      </div>
    </nav>
  );
}

function Footer({ setPage }) {
  return (
    <footer style={{ borderTop: `1px solid ${T.border}`, padding: "48px 5% 32px" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 32, marginBottom: 32 }}>
          <div style={{ maxWidth: 280 }}>
            <Wordmark size={18} />
            <p style={{ fontFamily: T.body, fontSize: 13, color: T.textDim, marginTop: 14, lineHeight: 1.6 }}>
              Cryptographic identity infrastructure for AI agents. SPIFFE-native, developer-first.
            </p>
          </div>
          {[
            { title: "Product", items: [["Docs", "docs"], ["Pricing", "pricing"]] },
            { title: "Company", items: [["About", "company"], ["Contact", "company"]] },
          ].map(col => (
            <div key={col.title}>
              <div style={{ fontFamily: T.mono, fontSize: 11, color: T.indigo, letterSpacing: "0.1em", marginBottom: 14 }}>{col.title.toUpperCase()}</div>
              {col.items.map(([label, target]) => (
                <div key={label} onClick={() => setPage(target)} style={{ fontFamily: T.body, fontSize: 13, color: T.textMid, marginBottom: 10, cursor: "pointer" }}>{label}</div>
              ))}
            </div>
          ))}
        </div>
        <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 20, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <span style={{ fontFamily: T.mono, fontSize: 11, color: T.textDim }}>© 2026 NONCE, Inc.</span>
          <span style={{ fontFamily: T.mono, fontSize: 11, color: T.textDim }}>hello@nonce.dev</span>
        </div>
      </div>
    </footer>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// HOME PAGE
// ════════════════════════════════════════════════════════════════════════════
const TERMINAL_LINES = [
  { t: "$ curl -X POST https://api.nonce.dev/v1/agents \\", c: T.textPrimary },
  { t: '  -d \'{"name":"payments-processor","scopes":["payments:execute"]}\'', c: T.textMid },
  { t: "", c: "transparent" },
  { t: "# HTTP 201 Created · 38ms", c: T.textDim },
  { t: "", c: "transparent" },
  { t: '{ "spiffe_id": "spiffe://acme.nonce.dev/agent/payments-processor",', c: T.indigoLight },
  { t: '  "cert_serial": "9F:3A:C1:B2:4E:07:DA:81",', c: T.textMid },
  { t: '  "expires_at": "2026-06-19T10:41:02Z" }', c: T.textMid },
  { t: "", c: "transparent" },
  { t: "✓  Identity issued. Agent is live.", c: T.green },
];
function HomeTerminal() {
  const [lines, setLines] = useState([]);
  const timers = useRef([]);
  const run = useCallback(() => {
    setLines([]);
    timers.current.forEach(clearTimeout);
    timers.current = TERMINAL_LINES.map((l, i) =>
      setTimeout(() => setLines(p => [...p, l]), i * 260)
    );
  }, []);
  useEffect(() => { const t = setTimeout(run, 600); return () => { clearTimeout(t); timers.current.forEach(clearTimeout); }; }, [run]);
  return (
    <div style={{ background: T.black, border: `1px solid ${T.border}`, borderRadius: 12, maxWidth: 600, width: "100%", boxShadow: `0 0 60px ${T.indigoGlow}, 0 24px 80px rgba(0,0,0,0.6)`, overflow: "hidden" }}>
      <div style={{ background: T.surface, borderBottom: `1px solid ${T.border}`, padding: "10px 16px", display: "flex", gap: 7 }}>
        {["#EF4444", "#F59E0B", "#10B981"].map((c, i) => <div key={i} style={{ width: 11, height: 11, borderRadius: "50%", background: c, opacity: 0.8 }} />)}
      </div>
      <div style={{ padding: "20px 22px", minHeight: 280, fontFamily: T.mono, fontSize: 13, lineHeight: 1.8 }}>
        {lines.map((l, i) => <div key={i} style={{ color: l.c }}>{l.t || "\u00A0"}</div>)}
      </div>
    </div>
  );
}

function HomePage({ setPage }) {
  return (
    <div>
      <div style={{ minHeight: "92vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "120px 5% 60px", position: "relative", textAlign: "center", overflow: "hidden" }}>
        <div style={{ position: "absolute", top: "18%", left: "50%", transform: "translateX(-50%)", width: 600, height: 600, background: `radial-gradient(ellipse, ${T.indigoGlow} 0%, transparent 70%)`, pointerEvents: "none" }} />
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, background: T.indigoGlow, border: `1px solid ${T.indigo}44`, borderRadius: 20, padding: "5px 14px", marginBottom: 28 }}>
          <div style={{ background: T.indigo, borderRadius: "50%", width: 6, height: 6 }} />
          <span style={{ fontFamily: T.mono, fontSize: 12, color: T.indigoLight }}>SPIFFE-native · EC P-256 · Zero-trust by default</span>
        </div>
        <h1 style={{ fontFamily: T.display, fontWeight: 700, fontSize: "clamp(38px, 6.5vw, 72px)", letterSpacing: "-0.04em", lineHeight: 1.05, color: T.textPrimary, maxWidth: 820, marginBottom: 22 }}>
          Every AI agent needs<br />
          <span style={{ background: `linear-gradient(135deg, ${T.indigo}, ${T.indigoLight})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>an identity.</span>
        </h1>
        <p style={{ fontFamily: T.body, fontSize: "clamp(15px, 1.8vw, 19px)", color: T.textMid, lineHeight: 1.65, maxWidth: 540, marginBottom: 36 }}>
          NONCE issues cryptographic SPIFFE identities for AI agents in a single API call. Scoped permissions, short-lived credentials, instant revocation, full audit trail.
        </p>
        <div style={{ display: "flex", gap: 12, marginBottom: 56, flexWrap: "wrap", justifyContent: "center" }}>
          <Btn onClick={() => setPage("docs")}>Start for free →</Btn>
          <Btn variant="secondary" onClick={() => setPage("docs")}>Read the docs</Btn>
        </div>
        <HomeTerminal />
      </div>

      <Reveal style={{ padding: "0 5% 90px" }}>
        <div style={{ maxWidth: 900, margin: "0 auto", background: T.surface, border: `1px solid ${T.border}`, borderRadius: 16, padding: 36, display: "grid", gridTemplateColumns: "repeat(4, 1fr)" }}>
          {[["38", "ms", "Avg issuance time"], ["78", "%", "Orgs with no agent ID policy"], ["45", ":1", "Machine:human identity ratio"], ["99.99", "%", "Uptime SLA"]].map(([v, s, l], i) => (
            <div key={l} style={{ textAlign: "center", padding: "0 16px", borderRight: i < 3 ? `1px solid ${T.border}` : "none" }}>
              <div style={{ fontFamily: T.display, fontWeight: 700, fontSize: 36, color: T.indigo, letterSpacing: "-0.03em", marginBottom: 6 }}>
                <Counter target={parseFloat(v)} suffix={s} decimals={v.includes(".") ? 2 : 0} />
              </div>
              <div style={{ fontFamily: T.body, fontSize: 12.5, color: T.textDim, lineHeight: 1.4 }}>{l}</div>
            </div>
          ))}
        </div>
      </Reveal>

      <Reveal style={{ padding: "0 5% 100px" }}>
        <div style={{ maxWidth: 900, margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: 48 }}>
            <div style={{ fontFamily: T.mono, fontSize: 11, color: T.indigo, letterSpacing: "0.12em", marginBottom: 10 }}>WHY NONCE</div>
            <h2 style={{ fontFamily: T.display, fontWeight: 700, fontSize: 34, letterSpacing: "-0.03em", color: T.textPrimary }}>Built for a new kind of actor.</h2>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            {[
              ["🔐", "Real X.509 cryptography", "EC P-256 certificates signed by the NONCE CA. Not token strings — actual PKI."],
              ["⏱", "Short-lived by default", "Every credential has a TTL. Zero-trust isn't a setting, it's the architecture."],
              ["⚡", "Instant revocation", "One call. Any subsequent check returns invalid, immediately, no propagation delay."],
            ].map(([icon, t, d]) => (
              <div key={t} style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 12, padding: 22 }}>
                <div style={{ fontSize: 20, marginBottom: 10 }}>{icon}</div>
                <div style={{ fontFamily: T.display, fontWeight: 700, fontSize: 15, color: T.textPrimary, marginBottom: 6 }}>{t}</div>
                <div style={{ fontFamily: T.body, fontSize: 13, color: T.textMid, lineHeight: 1.6 }}>{d}</div>
              </div>
            ))}
          </div>
        </div>
      </Reveal>

      <Reveal style={{ padding: "0 5% 110px", textAlign: "center" }}>
        <div style={{ maxWidth: 600, margin: "0 auto" }}>
          <NonceMark size={42} />
          <h2 style={{ fontFamily: T.display, fontWeight: 700, fontSize: 32, letterSpacing: "-0.03em", color: T.textPrimary, margin: "16px 0 28px" }}>
            Give your agents an identity today.
          </h2>
          <Btn onClick={() => setPage("docs")}>Get started free →</Btn>
        </div>
      </Reveal>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// DOCS PAGE — includes the live (simulated) API console
// ════════════════════════════════════════════════════════════════════════════
const ENDPOINTS = [
  { id: "issue", method: "POST", path: "/v1/agents", label: "Issue identity", body: { name: "billing-reconciler", org: "acme-corp", scopes: ["finance:read", "ledger:write"], ttl_minutes: 60 } },
  { id: "list", method: "GET", path: "/v1/agents", label: "List agents", body: null },
  { id: "verify", method: "POST", path: "/v1/agents/{id}/verify", label: "Verify identity", body: null, needsId: true },
  { id: "rotate", method: "POST", path: "/v1/agents/{id}/rotate", label: "Rotate credentials", body: null, needsId: true },
  { id: "revoke", method: "DELETE", path: "/v1/agents/{id}/revoke", label: "Revoke identity", body: null, needsId: true },
];
const methodColor = m => ({ POST: T.green, GET: T.indigo, DELETE: T.red }[m] || T.amber);

function ApiConsole() {
  const [activeId, setActiveId] = useState("issue");
  const [bodyText, setBodyText] = useState(JSON.stringify(ENDPOINTS[0].body, null, 2));
  const [agents, setAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState("checking"); // checking | awake | waking | offline

  const endpoint = ENDPOINTS.find(e => e.id === activeId);

  // On mount, ping the API once so we can show a "waking up" banner instead
  // of letting the user's first real click silently eat the Render cold-start delay.
  useEffect(() => {
    (async () => {
      const awake = await pingApi(3500);
      if (awake) { setApiStatus("awake"); return; }
      setApiStatus("waking");
      // Render free-tier cold starts are typically 10-30s — keep polling.
      const ok = await pingApi(25000);
      setApiStatus(ok ? "awake" : "offline");
    })();
  }, []);

  useEffect(() => {
    setBodyText(endpoint.body ? JSON.stringify(endpoint.body, null, 2) : "");
    setResponse(null);
  }, [activeId]);

  async function send() {
    let parsed = {};
    if (bodyText.trim()) { try { parsed = JSON.parse(bodyText); } catch { return; } }
    if (endpoint.needsId && !selectedAgentId) return;
    setLoading(true);
    const resolvedPath = endpoint.path.replace("{id}", selectedAgentId);
    const res = await callApi(endpoint.method, resolvedPath, parsed);
    setLoading(false);
    setResponse(res);
    if (res.status >= 200 && res.status < 500) setApiStatus("awake");
    const list = await callApi("GET", "/v1/agents");
    if (list.status === 200 && list.body?.agents) setAgents(list.body.agents);
  }

  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 14, overflow: "hidden" }}>
      {apiStatus === "waking" && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 18px", background: T.amber + "14", borderBottom: `1px solid ${T.amber}33` }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: T.amber, animation: "noncePulse 1.4s infinite" }} />
          <span style={{ fontFamily: T.body, fontSize: 12.5, color: T.amber }}>Waking up the API — Render free tier spins down when idle. This takes 10-30 seconds.</span>
        </div>
      )}
      {apiStatus === "offline" && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 18px", background: T.red + "14", borderBottom: `1px solid ${T.red}33` }}>
          <span style={{ fontSize: 12 }}>✕</span>
          <span style={{ fontFamily: T.body, fontSize: 12.5, color: T.red }}>Can't reach api.nonce.dev right now. You can still try a request below.</span>
        </div>
      )}
      <div style={{ display: "flex", borderBottom: `1px solid ${T.border}`, overflowX: "auto" }}>
        {ENDPOINTS.map(ep => (
          <div key={ep.id} onClick={() => setActiveId(ep.id)} style={{
            padding: "12px 18px", cursor: "pointer", whiteSpace: "nowrap",
            borderBottom: activeId === ep.id ? `2px solid ${T.indigo}` : "2px solid transparent",
            background: activeId === ep.id ? T.indigoGlow2 : "transparent",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <span style={{ fontFamily: T.mono, fontSize: 9, fontWeight: 700, color: methodColor(ep.method) }}>{ep.method}</span>
            <span style={{ fontFamily: T.body, fontSize: 13, color: activeId === ep.id ? T.textPrimary : T.textMid }}>{ep.label}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", minHeight: 320 }}>
        <div style={{ padding: 22, borderRight: `1px solid ${T.border}` }}>
          <div style={{ fontFamily: T.mono, fontSize: 12, color: T.textDim, marginBottom: 16 }}>
            {endpoint.method} <span style={{ color: T.textPrimary }}>{endpoint.path.replace("{id}", selectedAgentId || "{id}")}</span>
          </div>

          {endpoint.needsId && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontFamily: T.mono, fontSize: 10, color: T.textDim, marginBottom: 6, letterSpacing: "0.06em" }}>AGENT ID</div>
              {agents.length === 0 ? (
                <div style={{ fontFamily: T.body, fontSize: 12, color: T.textDim }}>Issue an agent first →</div>
              ) : (
                <select value={selectedAgentId} onChange={e => setSelectedAgentId(e.target.value)} style={{ width: "100%", background: T.black, border: `1px solid ${T.border}`, borderRadius: 6, padding: "8px 10px", color: T.textPrimary, fontFamily: T.mono, fontSize: 12 }}>
                  <option value="">— select agent —</option>
                  {agents.map(a => <option key={a.id} value={a.id}>{a.name} [{a.status}]</option>)}
                </select>
              )}
            </div>
          )}

          {endpoint.body !== null && (
            <textarea value={bodyText} onChange={e => setBodyText(e.target.value)} style={{ width: "100%", height: 160, background: T.black, border: `1px solid ${T.border}`, borderRadius: 6, padding: 12, color: T.textPrimary, fontFamily: T.mono, fontSize: 12, resize: "vertical" }} spellCheck={false} />
          )}

          <Btn onClick={send} small style={{ marginTop: 14 }}>{loading ? "Sending…" : "▶ Send request"}</Btn>
        </div>

        <div style={{ padding: 22, overflow: "auto" }}>
          <div style={{ fontFamily: T.mono, fontSize: 10, color: T.textDim, marginBottom: 10, letterSpacing: "0.06em" }}>RESPONSE</div>
          {!response ? (
            <div style={{ fontFamily: T.body, fontSize: 12.5, color: T.textDim }}>Send a request to see the response here.</div>
          ) : (
            <>
              <div style={{ fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: response.status === 0 ? T.amber : response.status < 300 ? T.green : T.red, marginBottom: 10 }}>
                {response.status === 0 ? "⏳ NETWORK" : response.status < 300 ? "✓" : "✗"} {response.status === 0 ? "Request failed — see detail below" : `HTTP ${response.status}`}
              </div>
              <CodeBlock style={{ fontSize: 11.5 }}>{JSON.stringify(response.body, null, 2)}</CodeBlock>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DocsPage() {
  return (
    <div style={{ padding: "100px 5% 100px" }}>
      <div style={{ maxWidth: 1000, margin: "0 auto" }}>
        <Reveal>
          <div style={{ fontFamily: T.mono, fontSize: 11, color: T.indigo, letterSpacing: "0.12em", marginBottom: 12 }}>DOCUMENTATION</div>
          <h1 style={{ fontFamily: T.display, fontWeight: 700, fontSize: "clamp(32px, 5vw, 48px)", letterSpacing: "-0.04em", color: T.textPrimary, marginBottom: 16 }}>
            Five lines of code.<br />Production-grade identity.
          </h1>
          <p style={{ fontFamily: T.body, fontSize: 16, color: T.textMid, lineHeight: 1.65, maxWidth: 620, marginBottom: 20 }}>
            This console talks directly to the live NONCE API — issue an identity, verify it, rotate credentials, revoke it. Every request below is real.
          </p>
          <div style={{ display: "inline-flex", gap: 8, alignItems: "center", background: T.indigoGlow, border: `1px solid ${T.indigo}33`, borderRadius: 8, padding: "8px 14px", marginBottom: 40 }}>
            <span style={{ fontSize: 13 }}>●</span>
            <span style={{ fontFamily: T.body, fontSize: 12.5, color: T.indigoLight }}>Live API · agents issued here are real and use the org "acme-corp" demo namespace.</span>
          </div>
        </Reveal>

        <Reveal delay={100}><ApiConsole /></Reveal>

        <Reveal delay={150} style={{ marginTop: 64 }}>
          <h2 style={{ fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.textPrimary, marginBottom: 20, letterSpacing: "-0.02em" }}>Quickstart</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div>
              <div style={{ fontFamily: T.mono, fontSize: 11, color: T.textDim, marginBottom: 8 }}>1. Install the SDK</div>
              <CodeBlock>pip install nonce-sdk</CodeBlock>
            </div>
            <div>
              <div style={{ fontFamily: T.mono, fontSize: 11, color: T.textDim, marginBottom: 8 }}>2. Issue an identity</div>
              <CodeBlock>{`from nonce_sdk import NonceClient
client = NonceClient(org="acme-corp")
agent = client.issue(
    name="billing-bot",
    scopes=["finance:read"]
)`}</CodeBlock>
            </div>
          </div>
        </Reveal>

        <Reveal delay={200} style={{ marginTop: 56 }}>
          <h2 style={{ fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.textPrimary, marginBottom: 20, letterSpacing: "-0.02em" }}>API reference</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {[
              ["POST", "/v1/agents", "Issue a new agent identity — returns SPIFFE ID, X.509 cert, and JWT."],
              ["GET", "/v1/agents", "List all agents for your org, optionally filtered by status."],
              ["GET", "/v1/agents/:id", "Fetch a single agent's full record including audit log."],
              ["POST", "/v1/agents/:id/verify", "Validate an agent's certificate chain and JWT expiry."],
              ["POST", "/v1/agents/:id/rotate", "Issue fresh credentials. Old credentials invalidate immediately."],
              ["DELETE", "/v1/agents/:id/revoke", "Permanently revoke an identity. Cannot be undone."],
            ].map(([m, p, d]) => (
              <div key={p} style={{ display: "flex", gap: 16, padding: "14px 0", borderBottom: `1px solid ${T.border}`, alignItems: "baseline" }}>
                <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: methodColor(m), width: 50, flexShrink: 0 }}>{m}</span>
                <span style={{ fontFamily: T.mono, fontSize: 13, color: T.textPrimary, width: 200, flexShrink: 0 }}>{p}</span>
                <span style={{ fontFamily: T.body, fontSize: 13, color: T.textMid }}>{d}</span>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PRICING PAGE
// ════════════════════════════════════════════════════════════════════════════
function PricingCard({ tier, price, unit, features, cta, highlight }) {
  return (
    <div style={{ background: highlight ? T.indigoGlow2 : T.surface, border: `1px solid ${highlight ? T.indigo : T.border}`, borderRadius: 14, padding: "28px 24px", position: "relative", flex: 1, minWidth: 240 }}>
      {highlight && <div style={{ position: "absolute", top: -11, left: "50%", transform: "translateX(-50%)", background: T.indigo, color: "#fff", fontFamily: T.mono, fontSize: 10, fontWeight: 700, padding: "3px 12px", borderRadius: 20, letterSpacing: "0.08em", whiteSpace: "nowrap" }}>MOST POPULAR</div>}
      <div style={{ fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.textMid, marginBottom: 8, letterSpacing: "0.04em" }}>{tier.toUpperCase()}</div>
      <div style={{ fontFamily: T.display, fontWeight: 700, fontSize: 34, color: T.textPrimary, letterSpacing: "-0.03em" }}>{price}</div>
      <div style={{ fontFamily: T.mono, fontSize: 12, color: T.textDim, marginBottom: 22 }}>{unit}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 26 }}>
        {features.map((f, i) => (
          <div key={i} style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
            <span style={{ color: T.green, fontSize: 13 }}>✓</span>
            <span style={{ fontFamily: T.body, fontSize: 13, color: T.textMid, lineHeight: 1.5 }}>{f}</span>
          </div>
        ))}
      </div>
      <Btn variant={highlight ? "primary" : "secondary"} style={{ width: "100%", justifyContent: "center" }}>{cta}</Btn>
    </div>
  );
}
function PricingPage() {
  const [faqOpen, setFaqOpen] = useState(null);
  const faqs = [
    ["Is there really a free tier?", "Yes. Up to 10,000 credentials per month, forever, no credit card required."],
    ["What counts as a credential?", "Every time you issue, verify, rotate, or revoke an agent identity, that's one credential operation."],
    ["Can I self-host NONCE?", "Enterprise plans include a self-hosted option with full source access and your own Certificate Authority."],
    ["What happens if I exceed my plan?", "We'll notify you and you can upgrade — we never silently cut off issued credentials."],
  ];
  return (
    <div style={{ padding: "100px 5% 100px" }}>
      <div style={{ maxWidth: 1000, margin: "0 auto" }}>
        <Reveal style={{ textAlign: "center", marginBottom: 56 }}>
          <div style={{ fontFamily: T.mono, fontSize: 11, color: T.indigo, letterSpacing: "0.12em", marginBottom: 12 }}>PRICING</div>
          <h1 style={{ fontFamily: T.display, fontWeight: 700, fontSize: "clamp(32px, 5vw, 46px)", letterSpacing: "-0.04em", color: T.textPrimary, marginBottom: 14 }}>
            Start free. Pay as you grow.
          </h1>
          <p style={{ fontFamily: T.body, fontSize: 15, color: T.textMid }}>No seats. No bundles. Pay per credential issued.</p>
        </Reveal>

        <Reveal delay={100}>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 80 }}>
            <PricingCard tier="Free" price="$0" unit="up to 10,000 credentials / mo" cta="Start building"
              features={["10,000 credentials/month", "SPIFFE SVID issuance", "Python + Node.js SDKs", "7-day audit retention", "Community support"]} />
            <PricingCard tier="Developer" price="$0.001" unit="per credential · billed monthly" cta="Start free trial" highlight
              features={["Unlimited credentials", "90-day audit retention", "Webhook on revocation", "Email support", "99.9% uptime SLA"]} />
            <PricingCard tier="Enterprise" price="Custom" unit="annual contract · from $50K/yr" cta="Talk to sales"
              features={["Unlimited everything", "Compliance dashboard", "1-year audit retention", "SIEM + SSO integration", "Dedicated support"]} />
          </div>
        </Reveal>

        <Reveal delay={150}>
          <h2 style={{ fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.textPrimary, marginBottom: 24, textAlign: "center" }}>Frequently asked</h2>
          <div style={{ maxWidth: 700, margin: "0 auto" }}>
            {faqs.map(([q, a], i) => (
              <div key={q} style={{ borderBottom: `1px solid ${T.border}` }}>
                <div onClick={() => setFaqOpen(faqOpen === i ? null : i)} style={{ padding: "18px 4px", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontFamily: T.body, fontSize: 14.5, color: T.textPrimary, fontWeight: 500 }}>{q}</span>
                  <span style={{ color: T.indigo, fontSize: 14, transform: faqOpen === i ? "rotate(45deg)" : "none", transition: "transform 0.2s" }}>+</span>
                </div>
                {faqOpen === i && <div style={{ padding: "0 4px 18px", fontFamily: T.body, fontSize: 13.5, color: T.textMid, lineHeight: 1.6 }}>{a}</div>}
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// COMPANY PAGE
// ════════════════════════════════════════════════════════════════════════════
function CompanyPage() {
  return (
    <div style={{ padding: "100px 5% 100px" }}>
      <div style={{ maxWidth: 900, margin: "0 auto" }}>
        <Reveal>
          <div style={{ fontFamily: T.mono, fontSize: 11, color: T.indigo, letterSpacing: "0.12em", marginBottom: 12 }}>COMPANY</div>
          <h1 style={{ fontFamily: T.display, fontWeight: 700, fontSize: "clamp(32px, 5vw, 48px)", letterSpacing: "-0.04em", color: T.textPrimary, marginBottom: 24, lineHeight: 1.1 }}>
            Agents are a new kind<br />of identity primitive.
          </h1>
          <p style={{ fontFamily: T.body, fontSize: 16, color: T.textMid, lineHeight: 1.75, maxWidth: 680, marginBottom: 20 }}>
            Every existing identity system was built for humans or static machines. AI agents break every assumption: they're spawned dynamically at runtime, they spawn sub-agents across trust boundaries, they run for hours with persistent access, and they don't just read data — they act on it.
          </p>
          <p style={{ fontFamily: T.body, fontSize: 16, color: T.textMid, lineHeight: 1.75, maxWidth: 680, marginBottom: 56 }}>
            NONCE exists because nobody had built the developer-friendly identity layer for this new class of actor. SPIFFE gave us the right cryptographic foundation. We built the API that makes it usable in an afternoon instead of a quarter.
          </p>
        </Reveal>

        <Reveal delay={100}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 64 }}>
            {[["2026", "Founded"], ["72 hrs", "Concept to working backend"], ["SF", "Headquartered"]].map(([v, l]) => (
              <div key={l} style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 12, padding: 22, textAlign: "center" }}>
                <div style={{ fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.indigo, marginBottom: 4 }}>{v}</div>
                <div style={{ fontFamily: T.body, fontSize: 12.5, color: T.textDim }}>{l}</div>
              </div>
            ))}
          </div>
        </Reveal>

        <Reveal delay={150}>
          <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 16, padding: 40, textAlign: "center" }}>
            <NonceMark size={36} />
            <h2 style={{ fontFamily: T.display, fontWeight: 700, fontSize: 24, color: T.textPrimary, margin: "16px 0 10px" }}>Get in touch</h2>
            <p style={{ fontFamily: T.body, fontSize: 14, color: T.textMid, marginBottom: 22 }}>Press, partnerships, investors, or just want to talk identity infrastructure.</p>
            <Btn>hello@nonce.dev</Btn>
          </div>
        </Reveal>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// APP SHELL
// ════════════════════════════════════════════════════════════════════════════
export default function NonceWebsite() {
  const [page, setPage] = useState("home");

  const navigate = (p) => { setPage(p); window.scrollTo({ top: 0, behavior: "instant" }); };

  return (
    <div style={{ background: T.black, color: T.textPrimary, minHeight: "100vh" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        ::selection { background: rgba(99,102,241,0.3); }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: ${T.black}; }
        ::-webkit-scrollbar-thumb { background: ${T.border}; border-radius: 3px; }
        select option { background: ${T.surface}; }
        @keyframes noncePulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
        @media (max-width: 720px) {
          .nonce-nav-links { display: none !important; }
        }
      `}</style>
      <Nav page={page} setPage={navigate} />
      {page === "home" && <HomePage setPage={navigate} />}
      {page === "docs" && <DocsPage />}
      {page === "pricing" && <PricingPage />}
      {page === "company" && <CompanyPage />}
      <Footer setPage={navigate} />
    </div>
  );
}
