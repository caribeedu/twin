/** Twin Web Command Center — single-route SPA. */

const app = $("#app");
const toastEl = $("#toast");
const VAULT = "default";

const ENTITY_TYPES = [
  { id: "narrative", label: "Narratives", role: "account", list: "/api/narratives", show: (id) => `/api/narratives/${id}` },
  { id: "reflection", label: "Reflections", role: "question", list: "/api/reflections?status=all", show: (id) => `/api/reflections/${id}` },
  { id: "interpretation", label: "Interpretations", role: "candidate", list: "/api/interpretations?status=all", show: (id) => `/api/interpretations/${id}` },
  { id: "situation", label: "Situations", role: "cluster", list: "/api/situations", show: (id) => `/api/situations/${id}` },
  { id: "stance", label: "Stances", role: "posture", list: "/api/stances", show: (id) => `/api/stances/${id}` },
  { id: "evidence", label: "Evidence", role: "warrant", list: "/api/evidence", show: (id) => `/api/evidence/${id}` },
  { id: "relation", label: "Relations", role: "edge", list: "/api/relations", show: (id) => `/api/relations/${id}` },
  { id: "trace", label: "Traces", role: "ledger", list: "/api/traces", show: (id) => `/api/traces/${id}` },
  { id: "percept", label: "Percepts", role: "observation", list: "/api/percepts?limit=200", show: (id) => `/api/percepts/${id}` },
];

function $(sel, root = document) {
  return root.querySelector(sel);
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toast(msg, ok = true) {
  toastEl.hidden = false;
  toastEl.textContent = msg;
  toastEl.className = `toast ${ok ? "ok" : "err"}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { toastEl.hidden = true; }, 3200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const detail = data?.detail || data?.error || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function parseHash() {
  const raw = (location.hash || "#home").slice(1);
  const [pane, ...rest] = raw.split("/").filter(Boolean);
  return { pane: pane || "home", parts: rest };
}

function setChrome(eyebrow, title) {
  const e = $("#pane-eyebrow");
  const t = $("#pane-title");
  if (e) e.textContent = eyebrow;
  if (t) t.textContent = title;
}

function setActiveNav(pane) {
  document.querySelectorAll(".rail-nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === pane);
  });
}

function badge(status) {
  const s = (status || "").toLowerCase();
  let cls = "tag";
  if (s === "fresh" || s === "open" || s === "active" || s === "committed") cls += " ok";
  else if (s === "stale" || s === "pending" || s === "competing") cls += " warn";
  else if (s === "tombstoned" || s === "rejected" || s === "deprecated") cls += " err";
  return `<span class="${cls}">${esc(status || "—")}</span>`;
}

function empty(title, body = "") {
  return `<div class="empty"><strong>${esc(title)}</strong>${body ? `<p>${esc(body)}</p>` : ""}</div>`;
}

function entityHeadline(row, type) {
  if (type === "narrative") return row.account || row.id;
  if (type === "reflection") return row.text || row.question || row.id;
  if (type === "interpretation") return row.explanation || row.id;
  if (type === "stance") return row.statement || row.id;
  if (type === "situation") return row.summary || row.label || row.id;
  if (type === "evidence") return row.quote || row.source_id || row.id;
  if (type === "relation") return `${row.type || "rel"} · ${row.from_id} → ${row.to_id}`;
  if (type === "trace") return `${row.event_kind || "event"} · ${row.resource_id || row.id}`;
  if (type === "percept") return row.summary || row.text || row.source_type || row.id;
  return row.id;
}

function truncate(s, n = 140) {
  const t = String(s || "").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

/* ---------- panes ---------- */

async function paneHome() {
  setChrome("Home", "Overview");
  app.innerHTML = `<div class="center-grid loading">Loading…</div>`;
  try {
    const sum = await api(`/api/center/summary?vault=${encodeURIComponent(VAULT)}`);
    app.innerHTML = `
      <section class="hero-block entity-account">
        <p class="lede">Sense captures. Cognize forms accounts. Inject projects — with receipts.</p>
        <div class="stat-row">
          <div class="stat"><span class="stat-n">${sum.open_reflections}</span><span class="stat-l">Open Reflections</span></div>
          <div class="stat"><span class="stat-n">${sum.competing_interpretations}</span><span class="stat-l">Competing Interpretations</span></div>
          <div class="stat"><span class="stat-n">${sum.narratives}</span><span class="stat-l">Narratives</span></div>
          <div class="stat"><span class="stat-n">${sum.jobs_pending}</span><span class="stat-l">Jobs pending</span></div>
          <div class="stat"><span class="stat-n">${sum.connectors}</span><span class="stat-l">Connectors</span></div>
        </div>
        ${sum.cognize_halt ? `<div class="health-banner warn">Cognize halt: ${esc(sum.cognize_halt)}</div>` : `<div class="health-banner ok">Cognize gate clear</div>`}
        <div class="cta-row">
          <a class="btn primary" href="#explore/reflection">Explore Reflections</a>
          <a class="btn" href="#review">Review</a>
          <a class="btn ghost" href="#inject">Inject pack</a>
        </div>
      </section>`;
  } catch (err) {
    app.innerHTML = empty("Could not load overview", err.message);
  }
}

async function paneExplore(parts) {
  const type = parts[0] || "narrative";
  const id = parts[1];
  const meta = ENTITY_TYPES.find((e) => e.id === type) || ENTITY_TYPES[0];
  setChrome("Explore", meta.label);

  const tabs = ENTITY_TYPES.map((e) =>
    `<a class="chip ${e.id === meta.id ? "ok" : ""}" href="#explore/${e.id}">${esc(e.label)}</a>`
  ).join("");

  if (id) {
    app.innerHTML = `<div class="explore-layout">
      <div id="explore-open-refs" class="open-refs-strip entity-question"></div>
      <div class="explore-tabs">${tabs}</div>
      <div class="detail entity-${meta.role}">Loading…</div>
    </div>`;
    try {
      const openRefs = await api(`/api/reflections?vault=${encodeURIComponent(VAULT)}&status=open`);
      const refs = Array.isArray(openRefs) ? openRefs : [];
      $("#explore-open-refs", app).innerHTML = refs.length
        ? `<strong>Open Reflections</strong> ${refs.slice(0, 5).map((r) =>
            `<a class="chip" href="#explore/reflection/${encodeURIComponent(r.id)}">${esc(truncate(r.text || r.id, 48))}</a>`
          ).join("")}`
        : `<strong>Open Reflections</strong> <span class="muted">none</span>`;
      const row = await api(meta.show(id));
      $(".detail", app).innerHTML = renderDetail(meta, row);
    } catch (err) {
      $(".detail", app).innerHTML = empty("Not found", err.message);
    }
    return;
  }

  app.innerHTML = `<div class="explore-layout">
    <div id="explore-open-refs" class="open-refs-strip entity-question"></div>
    <div class="explore-tabs">${tabs}</div>
    <div class="entity-list entity-${meta.role}">Loading…</div>
  </div>`;
  try {
    const openRefs = await api(`/api/reflections?vault=${encodeURIComponent(VAULT)}&status=open`);
    const refs = Array.isArray(openRefs) ? openRefs : [];
    const strip = $("#explore-open-refs", app);
    strip.innerHTML = refs.length
      ? `<strong>Open Reflections</strong> ${refs.slice(0, 5).map((r) =>
          `<a class="chip" href="#explore/reflection/${encodeURIComponent(r.id)}">${esc(truncate(r.text || r.id, 48))}</a>`
        ).join("")}${refs.length > 5 ? `<span class="muted">+${refs.length - 5}</span>` : ""}`
      : `<strong>Open Reflections</strong> <span class="muted">none</span>`;

    const rows = await api(`${meta.list}${meta.list.includes("?") ? "&" : "?"}vault=${encodeURIComponent(VAULT)}`);
    const list = Array.isArray(rows) ? rows : (rows.items || rows.stances || []);
    const box = $(".entity-list", app);
    if (!list.length) {
      box.innerHTML = empty(`No ${meta.label.toLowerCase()} yet`);
      return;
    }
    box.innerHTML = list.map((row) => {
      const rid = row.id;
      const status = row.epistemic_status || row.status || row.kind || "";
      return `<a class="entity-row" href="#explore/${meta.id}/${encodeURIComponent(rid)}">
        <div class="entity-row-main">
          <strong>${esc(truncate(entityHeadline(row, meta.id)))}</strong>
          <span class="muted">${esc(rid)}</span>
        </div>
        ${status ? badge(status) : ""}
      </a>`;
    }).join("");
  } catch (err) {
    $(".entity-list", app).innerHTML = empty("Load failed", err.message);
  }
}

function renderDetail(meta, row) {
  const back = `<a class="btn ghost" href="#explore/${meta.id}">← ${esc(meta.label)}</a>`;
  if (meta.id === "narrative") {
    const eps = row.epistemic || {};
    const derived = row.derived_confidence || {};
    const indep = derived.independence || {};
    const epsStatus = eps.status || row.status || "";
    const evidence = row.evidence || [];
    const relations = row.relations || [];
    const openRefs = row.open_reflections || [];
    return `${back}
      <article class="detail-card entity-account" data-epistemic="${esc(epsStatus)}">
        <header class="detail-head">
          <h2>Narrative</h2>
          <span class="epistemic-badge">${badge(epsStatus)}</span>
          ${row.grain ? `<span class="tag type">${esc(row.grain)}</span>` : ""}
          ${derived.label ? `<span class="tag">${esc(derived.label)} confidence</span>` : ""}
        </header>
        <div class="account-body">${esc(row.account)}</div>
        <dl class="kv">
          <div><dt>Domain</dt><dd>${esc(row.domain || "—")}</dd></div>
          <div><dt>Sensitivity</dt><dd>${esc(row.sensitivity || "—")}</dd></div>
          <div><dt>Committed by</dt><dd>${esc(row.committed_by || "—")}</dd></div>
          <div><dt>Stale reason</dt><dd>${esc(eps.stale_reason || "—")}</dd></div>
          <div><dt>Independence</dt><dd>${esc(indep.display || "—")}</dd></div>
          <div><dt>Derived</dt><dd>${esc(derived.rationale || "read-time")}</dd></div>
        </dl>
        <h3>Evidence</h3>
        <ul class="plain">${evidence.length
          ? evidence.map((e) => `<li>
              <a href="#explore/evidence/${encodeURIComponent(e.id)}">${esc(e.id)}</a>
              ${e.dissent ? badge("dissent") : ""}
              <span class="muted">${esc(truncate(e.quote || "", 80))}</span>
            </li>`).join("")
          : (row.evidence_ids || []).map((e) =>
              `<li><a href="#explore/evidence/${encodeURIComponent(e)}">${esc(e)}</a></li>`).join("")
            || "<li class='muted'>None</li>"}</ul>
        <h3>Relations</h3>
        <ul class="plain">${relations.length
          ? relations.map((r) => `<li>
              <a href="#explore/relation/${encodeURIComponent(r.id)}">${esc(r.type)}</a>
              <span class="muted">${esc(r.from_id)} → ${esc(r.to_id)}</span>
            </li>`).join("")
          : "<li class='muted'>None</li>"}</ul>
        <h3 class="entity-question">Open Reflections</h3>
        <ul class="plain">${openRefs.length
          ? openRefs.map((r) => `<li>
              <a href="#explore/reflection/${encodeURIComponent(r.id)}">${esc(truncate(r.text || r.id))}</a>
            </li>`).join("")
          : "<li class='muted'>None in domain</li>"}</ul>
      </article>`;
  }
  if (meta.id === "reflection") {
    return `${back}
      <article class="detail-card entity-question">
        <header class="detail-head"><h2>Reflection</h2>${badge(row.status)}</header>
        <p class="question-body">${esc(row.text || row.question || "")}</p>
        <dl class="kv">
          <div><dt>Situations</dt><dd>${esc((row.situation_ids || []).join(", ") || "—")}</dd></div>
          <div><dt>Evidence</dt><dd>${esc((row.evidence_ids || []).join(", ") || "—")}</dd></div>
        </dl>
        <p class="muted">${esc(row.id)}</p>
      </article>`;
  }
  if (meta.id === "interpretation") {
    return `${back}
      <article class="detail-card entity-candidate">
        <header class="detail-head"><h2>Interpretation</h2>${badge(row.status)}</header>
        <p class="candidate-body">${esc(row.explanation || "")}</p>
        <dl class="kv">
          <div><dt>Reflections</dt><dd>${esc((row.reflection_ids || []).join(", ") || "—")}</dd></div>
          <div><dt>Situations</dt><dd>${esc((row.situation_ids || []).join(", ") || "—")}</dd></div>
        </dl>
        <a class="btn primary" href="#review">Open Review</a>
      </article>`;
  }
  if (meta.id === "situation") {
    return `${back}
      <article class="detail-card entity-cluster">
        <header class="detail-head"><h2>Situation</h2>${badge(row.status)}</header>
        <p class="cluster-body">${esc(row.summary || "Working cluster")}</p>
        <dl class="kv">
          <div><dt>Domain</dt><dd>${esc(row.domain || "—")}</dd></div>
          <div><dt>Lifecycle</dt><dd>${esc(row.status || "—")}</dd></div>
          <div><dt>Percepts</dt><dd>${esc(String((row.percept_ids || []).length))}</dd></div>
        </dl>
        <h3 class="entity-observation">Member percepts</h3>
        <ul class="plain">${(row.percept_ids || []).length
          ? row.percept_ids.map((p) =>
              `<li><a href="#explore/percept/${encodeURIComponent(p)}">${esc(p)}</a></li>`).join("")
          : "<li class='muted'>None linked</li>"}</ul>
      </article>`;
  }
  if (meta.id === "stance") {
    return `${back}
      <article class="detail-card entity-posture">
        <header class="detail-head"><h2>Stance</h2>${badge(row.status)}
          <span class="tag type">${esc(row.kind || "")}</span></header>
        <p class="posture-body">${esc(row.statement || "")}</p>
        <dl class="kv">
          <div><dt>Domain</dt><dd>${esc(row.domain || "—")}</dd></div>
          <div><dt>Strength</dt><dd>${esc(row.strength ?? "—")}</dd></div>
        </dl>
      </article>`;
  }
  if (meta.id === "evidence") {
    return `${back}
      <article class="detail-card entity-warrant">
        <header class="detail-head"><h2>Evidence</h2>${row.dissent ? badge("dissent") : ""}</header>
        <p class="warrant-body">${esc(row.quote || "")}</p>
        <dl class="kv">
          <div><dt>Percept</dt><dd><a href="#explore/percept/${encodeURIComponent(row.percept_id || "")}">${esc(row.percept_id || "—")}</a></dd></div>
          <div><dt>Target</dt><dd>${esc(row.target_kind || "")} ${esc(row.target_id || "")}</dd></div>
          <div><dt>Source</dt><dd>${esc(row.source_id || "—")}</dd></div>
          <div><dt>ACL</dt><dd>${esc((row.acl_tags || []).join(", ") || "—")}</dd></div>
        </dl>
      </article>`;
  }
  if (meta.id === "relation") {
    return `${back}
      <article class="detail-card entity-edge">
        <header class="detail-head"><h2>Relation</h2><span class="tag type">${esc(row.type)}</span></header>
        <p><code>${esc(row.from_id)}</code> → <code>${esc(row.to_id)}</code></p>
        <p class="muted">${esc(row.rationale || "")}</p>
      </article>`;
  }
  if (meta.id === "trace") {
    return `${back}
      <article class="detail-card entity-ledger">
        <header class="detail-head"><h2>Trace</h2><span class="tag">${esc(row.event_kind)}</span></header>
        <dl class="kv">
          <div><dt>Resource</dt><dd>${esc(row.resource_kind || "")} ${esc(row.resource_id || "")}</dd></div>
          <div><dt>When</dt><dd>${esc(row.created_at || "—")}</dd></div>
        </dl>
      </article>`;
  }
  return `${back}
    <article class="detail-card entity-${meta.role}">
      <header class="detail-head"><h2>${esc(meta.label.slice(0, -1) || meta.id)}</h2>${row.status ? badge(row.status) : ""}</header>
      <pre class="json-block">${esc(JSON.stringify(row, null, 2))}</pre>
    </article>`;
}

async function paneReview() {
  setChrome("Review", "Interpretations & commit");
  app.innerHTML = `<div class="split-panes"><section id="rev-list">Loading…</section><section id="rev-commit"></section></div>`;
  try {
    const [openRefs, competing] = await Promise.all([
      api(`/api/reflections?vault=${encodeURIComponent(VAULT)}&status=open`),
      api(`/api/interpretations?vault=${encodeURIComponent(VAULT)}&status=competing`),
    ]);
    const refs = Array.isArray(openRefs) ? openRefs : [];
    const ints = Array.isArray(competing) ? competing : [];
    $("#rev-list").innerHTML = `
      <h3 class="entity-question">Open Reflections</h3>
      ${refs.length ? refs.map((r) =>
        `<a class="entity-row" href="#explore/reflection/${encodeURIComponent(r.id)}">
          <strong>${esc(truncate(r.text || r.question || r.id))}</strong></a>`).join("") : empty("No open Reflections")}
      <h3 class="entity-candidate">Competing Interpretations</h3>
      ${ints.length ? ints.map((i) =>
        `<a class="entity-row" href="#explore/interpretation/${encodeURIComponent(i.id)}">
          <strong>${esc(truncate(i.explanation || i.id))}</strong>${badge(i.status)}</a>`).join("") : empty("No competing Interpretations")}`;

    $("#rev-commit").innerHTML = `
      <h3 class="entity-account">Commit Narrative</h3>
      <form id="nar-commit-form" class="stack-form">
        <label>Account<textarea name="account" rows="5" required></textarea></label>
        <label>Evidence ids (comma-separated)<input name="evidence" required /></label>
        <label>Interpretation ids<input name="interpretations" placeholder="optional" /></label>
        <label>Actor<input name="actor" value="user" required /></label>
        <label>Domain<input name="domain" value="technical" /></label>
        <p id="nar-token" class="muted">Preview for a commit token first.</p>
        <div class="cta-row">
          <button type="button" class="btn" id="nar-preview">Preview token</button>
          <button type="submit" class="btn primary">Commit</button>
        </div>
      </form>`;

    let previewToken = "";
    $("#nar-preview").addEventListener("click", async () => {
      const fd = new FormData($("#nar-commit-form"));
      try {
        const body = commitBody(fd);
        const prev = await api("/api/narratives/commit-preview", { method: "POST", body: JSON.stringify(body) });
        previewToken = prev.preview_token || "";
        $("#nar-token").textContent = previewToken ? `Token: ${previewToken}` : "No token";
        toast("Preview ready");
      } catch (err) {
        toast(err.message, false);
      }
    });
    $("#nar-commit-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (!previewToken) {
        toast("Preview a token before commit", false);
        return;
      }
      const fd = new FormData(ev.target);
      try {
        const body = { ...commitBody(fd), preview_token: previewToken };
        const out = await api("/api/narratives/commit", { method: "POST", body: JSON.stringify(body) });
        toast(`Committed ${out.narrative_id}`);
        location.hash = `#explore/narrative/${out.narrative_id}`;
      } catch (err) {
        toast(err.message, false);
      }
    });
  } catch (err) {
    app.innerHTML = empty("Review failed", err.message);
  }
}

function commitBody(fd) {
  const evidence = String(fd.get("evidence") || "").split(/[,\s]+/).filter(Boolean);
  const interpretations = String(fd.get("interpretations") || "").split(/[,\s]+/).filter(Boolean);
  return {
    account: fd.get("account"),
    evidence_ids: evidence,
    interpretation_ids: interpretations,
    dissent_ids: [],
    actor: fd.get("actor") || "user",
    domain: fd.get("domain") || "technical",
    vault_id: VAULT,
  };
}

async function paneCognize() {
  setChrome("Cognize", "Pipeline status");
  app.innerHTML = `<div class="stack">Loading…</div>`;
  try {
    const [sum, health] = await Promise.all([
      api(`/api/center/summary?vault=${encodeURIComponent(VAULT)}`),
      api("/api/health/cognition").catch((e) => ({ error: e.message })),
    ]);
    app.innerHTML = `
      <section class="detail-card">
        <p>Open Reflections: <strong>${sum.open_reflections}</strong></p>
        <p>Competing Interpretations: <strong>${sum.competing_interpretations}</strong></p>
        <p>Halt: <strong>${esc(sum.cognize_halt || "none")}</strong></p>
        <p class="muted">Run cognition from the TUI Command Center or <code>twin cognize run</code>.</p>
        <pre class="json-block">${esc(JSON.stringify(health, null, 2))}</pre>
      </section>`;
  } catch (err) {
    app.innerHTML = empty("Cognize pane failed", err.message);
  }
}

async function paneSense() {
  setChrome("Sense", "Percepts · Connectors · Jobs");
  app.innerHTML = `<div class="split-panes"><section id="sense-a">Loading…</section><section id="sense-b"></section></div>`;
  try {
    const [percepts, connectors, jobs] = await Promise.all([
      api("/api/percepts?limit=50"),
      api("/api/connectors").catch(() => []),
      api("/api/runtime/jobs?limit=40").catch(() => []),
    ]);
    const plist = Array.isArray(percepts) ? percepts : [];
    const clist = Array.isArray(connectors) ? connectors : (connectors.connectors || []);
    const jlist = Array.isArray(jobs) ? jobs : [];
    $("#sense-a").innerHTML = `
      <h3 class="entity-observation">Recent Percepts</h3>
      ${plist.length ? plist.map((p) =>
        `<a class="entity-row" href="#explore/percept/${encodeURIComponent(p.id)}">
          <strong>${esc(truncate(p.summary || p.text || p.source_type || p.id))}</strong>
          <span class="muted">${esc(p.id)}</span></a>`).join("") : empty("No percepts")}`;
    $("#sense-b").innerHTML = `
      <h3>Connectors</h3>
      ${clist.length ? clist.map((c) =>
        `<div class="entity-row"><strong>${esc(c.connector_type || c.id)}</strong>
          ${badge(c.status)}${c.id ? `<span class="muted">${esc(c.id)}</span>` : ""}</div>`).join("") : empty("No connectors yet", "twin connector setup · or TUI Connectors")}
      <h3>Jobs</h3>
      ${jlist.length ? jlist.map((j) =>
        `<div class="entity-row"><strong>${esc(j.kind || j.id)}</strong>${badge(j.status)}</div>`).join("") : empty("No jobs")}`;
  } catch (err) {
    app.innerHTML = empty("Sense pane failed", err.message);
  }
}

async function paneInject() {
  setChrome("Inject", "Context pack");
  app.innerHTML = `
    <section class="detail-card entity-warrant">
      <form id="pack-form" class="stack-form">
        <label>Query<input name="query" required placeholder="What was decided about…?" /></label>
        <label>Domain<input name="domain" value="technical" /></label>
        <button class="btn primary" type="submit">Build pack</button>
      </form>
      <div id="pack-meta" class="muted"></div>
      <pre id="pack-out" class="json-block" hidden></pre>
    </section>`;
  $("#pack-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const out = $("#pack-out");
    const meta = $("#pack-meta");
    out.hidden = true;
    try {
      const data = await api("/api/context_pack", {
        method: "POST",
        body: JSON.stringify({
          query: fd.get("query"),
          target_domain: fd.get("domain") || "technical",
        }),
      });
      meta.textContent = `Narratives: ${(data.narratives || []).length} · Reflections: ${(data.open_reflections || []).length}`;
      out.hidden = false;
      out.textContent = data.context_pack || JSON.stringify(data, null, 2);
    } catch (err) {
      toast(err.message, false);
    }
  });
}

async function paneOps() {
  setChrome("Ops", "Health & Stance proposals");
  app.innerHTML = `<div class="stack">Loading…</div>`;
  try {
    const [health, runtime, proposals] = await Promise.all([
      api("/api/health/cognition").catch((e) => ({ error: e.message })),
      api("/api/runtime/health").catch((e) => ({ error: e.message })),
      api("/api/stances/proposals").catch(() => []),
    ]);
    const props = Array.isArray(proposals) ? proposals : [];
    app.innerHTML = `
      <section class="split-panes">
        <div class="detail-card">
          <h3>Cognition health</h3>
          <pre class="json-block">${esc(JSON.stringify(health, null, 2))}</pre>
          <h3>Runtime</h3>
          <pre class="json-block">${esc(JSON.stringify(runtime, null, 2))}</pre>
        </div>
        <div class="detail-card entity-posture" id="stance-ops">
          <h3>Pending Stance proposals</h3>
          ${props.length ? props.map((p) => `
            <div class="entity-row stance-prop" data-id="${esc(p.id)}">
              <div class="entity-row-main">
                <strong>${esc(truncate(p.statement || p.id))}</strong>
                <span class="muted">${esc(p.id)}</span>
              </div>
              ${badge(p.status)}
              <div class="cta-row">
                <button type="button" class="btn stance-preview" data-id="${esc(p.id)}">Preview</button>
                <button type="button" class="btn primary stance-approve" data-id="${esc(p.id)}" disabled>Approve</button>
              </div>
            </div>`).join("") : empty("No pending proposals", "Approve requires preview token")}
          <p id="stance-token" class="muted">Preview a proposal to unlock Approve.</p>
        </div>
      </section>`;

    const tokens = {};
    app.querySelectorAll(".stance-preview").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        try {
          const prev = await api(`/api/stances/proposals/${encodeURIComponent(id)}/preview`, {
            method: "POST",
            body: JSON.stringify({}),
          });
          tokens[id] = prev.preview_token || prev.token || "";
          const row = btn.closest(".stance-prop");
          row?.querySelector(".stance-approve")?.removeAttribute("disabled");
          $("#stance-token").textContent = tokens[id]
            ? `Token for ${id}: ${tokens[id]}`
            : "Preview returned no token";
          toast("Stance preview ready");
        } catch (err) {
          toast(err.message, false);
        }
      });
    });
    app.querySelectorAll(".stance-approve").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        const token = tokens[id];
        if (!token) {
          toast("Preview first", false);
          return;
        }
        try {
          await api(`/api/stances/proposals/${encodeURIComponent(id)}/approve`, {
            method: "POST",
            body: JSON.stringify({ preview_token: token }),
          });
          toast(`Approved ${id}`);
          paneOps();
        } catch (err) {
          toast(err.message, false);
        }
      });
    });
  } catch (err) {
    app.innerHTML = empty("Ops failed", err.message);
  }
}

async function route() {
  const { pane, parts } = parseHash();
  setActiveNav(pane === "explore" ? "explore" : pane);
  const views = {
    home: () => paneHome(),
    explore: () => paneExplore(parts),
    review: () => paneReview(),
    cognize: () => paneCognize(),
    sense: () => paneSense(),
    inject: () => paneInject(),
    ops: () => paneOps(),
  };
  const fn = views[pane] || views.home;
  await fn();
}

window.addEventListener("hashchange", () => { route().catch((e) => toast(e.message, false)); });
route().catch((e) => toast(e.message, false));
