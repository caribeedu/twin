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
  { id: "evidence", label: "Evidences", role: "warrant", list: "/api/evidence", show: (id) => `/api/evidence/${id}` },
  { id: "trace", label: "Traces", role: "ledger", list: "/api/traces", show: (id) => `/api/traces/${id}` },
  { id: "percept", label: "Percepts", role: "observation", list: "/api/percepts?limit=200", show: (id) => `/api/percepts/${id}` },
  { id: "relation", label: "Relations", role: "edge", list: "/api/relations", show: (id) => `/api/relations/${id}` },
];

const CONNECTOR_LABELS = {
  github: "GitHub",
  slack: "Slack",
  gmail: "Gmail",
  mail: "Mail",
  outlook: "Outlook",
  calendar: "Calendar",
  meeting: "Meeting",
  fireflies: "Fireflies",
  document: "Document",
  folder: "Folder",
  git: "Git",
  episode_reflect: "Derived",
  pattern_reflect: "Derived",
};

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

function setChrome(eyebrow, title, { home = false } = {}) {
  const top = $("#center-top");
  const e = $("#pane-eyebrow");
  const t = $("#pane-title");
  if (top) top.hidden = !!home;
  if (e) e.textContent = eyebrow;
  if (t) t.textContent = title;
}

function setExploreChrome(meta, query = "") {
  const q = String(query || "").trim();
  setChrome("Explore", q ? `Search in ${meta.label}` : meta.label);
}

function rowSearchText(row, type) {
  return `${entityHeadline(row, type)} ${row.id || ""} ${row.type || ""} ${row.from_id || ""} ${row.to_id || ""}`;
}

function setActiveNav(pane) {
  const key = pane === "explore" ? "explore" : pane;
  document.querySelectorAll(".center-tabs [data-nav]").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === key);
  });
}

function sectionGo(href, label = "Open") {
  return `<a class="section-go" href="${esc(href)}"><span>${esc(label)}</span><span class="section-go-arrow" aria-hidden="true">→</span></a>`;
}

/** Mock until host session telemetry exists. */
const MOCK_SESSIONS = [
  { provider: "Claude", open: 2 },
  { provider: "ChatGPT", open: 1 },
  { provider: "Antigravity", open: 0 },
  { provider: "Cursor", open: 3 },
];

function fuzzyScore(query, text) {
  const q = String(query || "").trim().toLowerCase();
  const t = String(text || "").toLowerCase();
  if (!q) return 0;
  if (t.includes(q)) return 100 - Math.min(40, t.indexOf(q));
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++;
  }
  return qi === q.length ? 40 : 0;
}

/** Case-insensitive substring match (Explore search — no fuzzy subsequences). */
function textIncludes(query, text) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  return String(text || "").toLowerCase().includes(q);
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
  let raw = row.id;
  if (type === "narrative") raw = row.account || row.id;
  else if (type === "reflection") raw = row.text || row.question || row.id;
  else if (type === "interpretation") raw = row.explanation || row.id;
  else if (type === "stance") raw = row.statement || row.id;
  else if (type === "situation") raw = row.summary || row.label || row.id;
  else if (type === "evidence") raw = row.quote || row.source_id || row.id;
  else if (type === "relation") raw = `${row.type || "rel"} · ${row.from_id} → ${row.to_id}`;
  else if (type === "trace") raw = `${row.event_kind || "event"} · ${row.resource_id || row.id}`;
  else if (type === "percept") {
    if (isDerivedPercept(row)) {
      raw = row.content || row.summary || row.text
        || connectorLabel(row.source_sensor) || "Derived percept";
    } else {
      const kind = [row.percept_type, row.source_sensor]
        .filter(Boolean)
        .map((s) => String(s).replace(/_/g, " "))
        .join(" · ");
      raw = row.content || row.summary || row.text || kind || row.id;
    }
  }
  // List title = first non-empty line (accounts/reflections are often multi-line MD)
  const line = String(raw || "").split("\n").map((l) => l.trim()).find(Boolean) || String(row.id || "");
  return line;
}

function truncate(s, n = 140) {
  const t = String(s || "").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

/** Strip common markdown markers for compare / plain truncate. */
function stripMd(s) {
  return String(s || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Lightweight markdown → safe HTML (no external deps). */
function renderMd(src) {
  const text = String(src || "").replace(/\r\n/g, "\n").trim();
  if (!text) return "";

  const escapeText = (s) => esc(s);
  const inline = (s) => {
    let t = escapeText(s);
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    t = t.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, "$1<em>$2</em>");
    t = t.replace(/(^|[^_])_([^_]+)_(?!_)/g, "$1<em>$2</em>");
    t = t.replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    );
    return t;
  };

  const blocks = [];
  const lines = text.split("\n");
  let i = 0;
  let para = [];
  let list = null; // { ordered: bool, items: [] }

  const flushPara = () => {
    if (!para.length) return;
    blocks.push(`<p>${inline(para.join(" "))}</p>`);
    para = [];
  };
  const flushList = () => {
    if (!list) return;
    const tag = list.ordered ? "ol" : "ul";
    blocks.push(
      `<${tag}>${list.items.map((it) => `<li>${inline(it)}</li>`).join("")}</${tag}>`,
    );
    list = null;
  };

  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      flushPara();
      flushList();
      i += 1;
      const code = [];
      while (i < lines.length && !/^```/.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1;
      blocks.push(`<pre class="md-code"><code>${escapeText(code.join("\n"))}</code></pre>`);
      continue;
    }
    if (!line.trim()) {
      flushPara();
      flushList();
      i += 1;
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      flushPara();
      flushList();
      const level = heading[1].length;
      blocks.push(`<h${level + 2} class="md-h">${inline(heading[2])}</h${level + 2}>`);
      i += 1;
      continue;
    }
    const ul = /^\s*[-*+]\s+(.+)$/.exec(line);
    if (ul) {
      flushPara();
      if (!list || list.ordered) {
        flushList();
        list = { ordered: false, items: [] };
      }
      list.items.push(ul[1]);
      i += 1;
      continue;
    }
    const ol = /^\s*\d+\.\s+(.+)$/.exec(line);
    if (ol) {
      flushPara();
      if (!list || !list.ordered) {
        flushList();
        list = { ordered: true, items: [] };
      }
      list.items.push(ol[1]);
      i += 1;
      continue;
    }
    flushList();
    para.push(line.trim());
    i += 1;
  }
  flushPara();
  flushList();
  return blocks.join("");
}

function renderMdInline(src) {
  const html = renderMd(src);
  // Prefer single-line inline HTML for titles
  const m = /^<p>(.*)<\/p>$/s.exec(html.trim());
  return m ? m[1] : html || esc(src);
}

function connectorLabel(sensor) {
  const raw = String(sensor || "").trim();
  if (!raw || /^unknown$/i.test(raw)) return "";
  const key = raw.toLowerCase().replace(/\s+/g, "_");
  if (CONNECTOR_LABELS[key]) return CONNECTOR_LABELS[key];
  return raw
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
    .join(" ");
}

function titleHtml(row, type) {
  return renderMdInline(entityHeadline(row, type));
}

/** Parse GitHub PR percept content into structured meta + remaining body. */
function parseGithubPrContent(content) {
  const lines = String(content || "").replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length && !lines[i].trim()) i += 1;
  if (i >= lines.length) return null;

  const titleM = lines[i].trim().match(/^GitHub pull request\s+(\S+)#(\d+):\s*(.*)$/i);
  if (!titleM) return null;
  const repo = titleM[1];
  const number = titleM[2];
  const prTitle = (titleM[3] || "").trim();
  i += 1;
  while (i < lines.length && !lines[i].trim()) i += 1;

  let state = "";
  let mergedAt = "";
  let base = "";
  let head = "";
  if (i < lines.length) {
    const stateLine = lines[i].trim();
    const sm = stateLine.match(
      /^state:\s*([A-Za-z]+)(?:\s*·\s*merged at\s+(\S+))?\s*·\s*(.+?)\s*←\s*(.+?)(?:\s+This is the FINAL.*)?$/i,
    );
    if (sm) {
      state = sm[1].toUpperCase();
      mergedAt = sm[2] || "";
      base = sm[3].trim();
      head = sm[4].trim();
      i += 1;
      while (i < lines.length && !lines[i].trim()) i += 1;
    }
  }

  let note = "";
  if (i < lines.length) {
    const noteLine = lines[i].trim();
    if (/^This is the FINAL/i.test(noteLine) || /^Closed WITHOUT merging/i.test(noteLine)) {
      note = noteLine;
      i += 1;
      while (i < lines.length && !lines[i].trim()) i += 1;
    }
  }

  const body = lines.slice(i).join("\n").trim();
  return { repo, number, prTitle, state, mergedAt, base, head, note, body };
}

function isDerivedPercept(row) {
  const id = String(row?.id || "");
  const t = String(row?.percept_type || "").toLowerCase();
  const s = String(row?.source_sensor || "").toLowerCase();
  return (
    id.startsWith("pct_derived_")
    || id.startsWith("pct_reflect_")
    || id.startsWith("pct_pattern_")
    || /^pctreflect/i.test(id)
    || /^pctpattern/i.test(id)
    || t === "derived"
    || t.startsWith("derived_")
    || t.includes("reflection") // legacy episode_reflection / pattern_reflection
    || s.includes("reflect")
  );
}

function perceptKindLabel(row) {
  return isDerivedPercept(row) ? "Derived" : "Observed";
}

function relationEdgeLabel(type) {
  const raw = String(type || "").replace(/_/g, "-").toLowerCase().trim();
  if (!raw) return "";
  // Structural origin labels that just repeat the entity kind — omit from edges.
  const entityKinds = new Set([
    "percept", "evidence", "situation", "reflection", "interpretation",
    "narrative", "stance", "trace", "relation", "entity", "origin",
    "source", "connector", "from", "to", "next", "contains", "related",
  ]);
  if (entityKinds.has(raw)) return "";
  const map = {
    "same-originating-decision": "Same origin",
    "same origin": "Same origin",
    contradicts: "Contradicts",
    supports: "Supports",
    "depends-on": "Depends on",
    supersedes: "Supersedes",
    continues: "Continues",
    "part-of": "Part of",
    "same-as": "Same as",
  };
  if (map[raw]) return map[raw];
  return raw
    .split("-")
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function renderPrMetaCard(pr) {
  if (!pr) return "";
  const bits = [];
  bits.push(`<span class="pr-ref">${esc(pr.repo)}#${esc(pr.number)}</span>`);
  if (pr.state) {
    const stateCls = pr.state === "MERGED"
      ? "pr-state--merged"
      : pr.state === "OPEN"
        ? "pr-state--open"
        : pr.state === "CLOSED"
          ? "pr-state--closed"
          : "";
    bits.push(`<span class="pr-state ${stateCls}">${esc(pascalStatus(pr.state))}</span>`);
  }
  if (pr.mergedAt) bits.push(`<span class="pr-merged">${esc(formatWhen(pr.mergedAt))}</span>`);
  if (pr.base || pr.head) {
    bits.push(
      `<span class="pr-branches"><code>${esc(pr.base || "?")}</code>`
      + `<span aria-hidden="true"> ← </span>`
      + `<code>${esc(pr.head || "?")}</code></span>`,
    );
  }
  return `<div class="pr-meta" aria-label="Pull request details">
    <p class="pr-meta-line">${bits.join('<span class="pr-dot" aria-hidden="true"> · </span>')}</p>
    ${pr.note ? `<p class="pr-note">${esc(pr.note)}</p>` : ""}
  </div>`;
}

/** Body text for expand: full field minus the list title line (no duplicate). */
function expandBodyText(meta, row) {
  const full =
    row.account || row.text || row.question || row.explanation || row.summary
    || row.statement || row.quote || row.content || "";
  if (!full) return "";
  const title = entityHeadline(row, meta.id);
  const lines = String(full).replace(/\r\n/g, "\n").split("\n");
  let start = 0;
  while (start < lines.length && !lines[start].trim()) start += 1;
  if (start < lines.length) {
    const first = lines[start].trim();
    if (first === title || stripMd(first) === stripMd(title)) {
      start += 1;
      while (start < lines.length && !lines[start].trim()) start += 1;
    }
  }
  const rest = lines.slice(start).join("\n").trim();
  if (!rest) return "";
  if (stripMd(rest) === stripMd(title)) return "";
  return rest;
}

/* ---------- panes ---------- */

function pascalKind(kind, label) {
  if (label) return label;
  const s = String(kind || "");
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "Item";
}

function pascalStatus(status) {
  const s = String(status || "").trim();
  if (!s) return "";
  return s
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join("");
}

function reviewStatusClass(status) {
  const key = String(status || "").toLowerCase().replace(/[_\s]+/g, "-");
  const known = new Set([
    "open", "competing", "pending", "active", "committed", "fresh",
    "stale", "closed", "resolved", "rejected", "deprecated", "working",
  ]);
  if (known.has(key)) return `review-status review-status--${key}`;
  if (["open", "active", "committed", "fresh", "resolved"].includes(key)) {
    return "review-status review-status--open";
  }
  if (["competing", "pending", "stale", "working"].includes(key)) {
    return "review-status review-status--competing";
  }
  if (["rejected", "deprecated", "closed"].includes(key)) {
    return "review-status review-status--rejected";
  }
  return "review-status";
}

function formatWhen(iso) {
  if (!iso) return "";
  const raw = String(iso).trim();
  const m = raw.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
  if (m) return `${m[1]} ${m[2]}`;
  return raw.length >= 16 ? raw.slice(0, 16).replace("T", " ") : raw;
}

function reviewMetaLine(meta) {
  const m = meta || {};
  const situations = m.situations ?? 0;
  const evidence = m.evidence ?? 0;
  return `Situations: ${situations} - Evidence: ${evidence}`;
}

function reviewCard(item) {
  const kind = pascalKind(item.kind, item.kind_label);
  const statusLabel = pascalStatus(item.status);
  const metaLine = reviewMetaLine(item.meta);
  const title = item.title || truncate(item.text || item.id, 100);
  const body = item.text && item.text !== title ? truncate(item.text, 180) : "";
  return `
    <a class="review-home-card" href="${esc(item.href)}">
      <div class="review-home-top">
        <span class="review-kind">${esc(kind)}</span>
        ${statusLabel
          ? `<span class="${reviewStatusClass(item.status)}">${esc(statusLabel)}</span>`
          : ""}
        <span class="review-id muted">${esc(item.id)}</span>
      </div>
      <strong class="review-title">${esc(title)}</strong>
      ${body ? `<p class="review-excerpt">${esc(body)}</p>` : ""}
      <div class="review-home-foot muted">
        ${formatWhen(item.created_at) ? `<span>${esc(formatWhen(item.created_at))}</span>` : ""}
        ${metaLine ? `<span>${esc(metaLine)}</span>` : ""}
      </div>
    </a>`;
}

async function paneHome() {
  setChrome("Home", "General");
  app.innerHTML = `<div class="home-dash loading">Loading…</div>`;
  try {
    const sum = await api(`/api/center/summary?vault=${encodeURIComponent(VAULT)}`);
    const counts = sum.counts || {};
    const review = sum.review_items || [];
    const reviewOpen =
      (sum.open_reflections ?? 0) + (sum.competing_interpretations ?? 0);
    const domains = sum.domains || [];
    const entityTiles = [
      ["narratives", "Narratives", "#explore/narrative"],
      ["reflections", "Reflections", "#explore/reflection"],
      ["interpretations", "Interpretations", "#explore/interpretation"],
      ["situations", "Situations", "#explore/situation"],
      ["stances", "Stances", "#explore/stance"],
      ["evidence", "Evidences", "#explore/evidence"],
      ["traces", "Traces", "#explore/trace"],
      ["percepts", "Percepts", "#explore/percept"],
      ["relations", "Relations", "#explore/relation"],
    ];
    const domainOptions = domains.length
      ? domains.map((d) =>
          `<option value="${esc(d.id)}">${esc(d.label)} (${d.count})</option>`
        ).join("")
      : `<option value="" disabled selected>No domains with content yet</option>`;

    app.innerHTML = `
      <div class="home-dash">
        <section class="home-card home-sessions home-card--compact">
          ${sectionGo("#sessions", "Sessions")}
          <h2 class="home-card-title">Active sessions</h2>
          <div class="session-grid">
            ${MOCK_SESSIONS.map((s) => `
              <div class="session-pill">
                <span class="session-n">${s.open}</span>
                <span class="session-l">${esc(s.provider)}</span>
              </div>`).join("")}
          </div>
        </section>

        <section class="home-card home-jobs home-card--compact">
          ${sectionGo("#sense", "Jobs")}
          <h2 class="home-card-title">Jobs</h2>
          <div class="jobs-pair">
            <div class="job-stat">
              <span class="stat-n">${sum.jobs_running ?? 0}</span>
              <span class="stat-l">Running</span>
            </div>
            <div class="job-stat">
              <span class="stat-n">${sum.jobs_pending ?? 0}</span>
              <span class="stat-l">Pending</span>
            </div>
          </div>
        </section>

        <section class="home-card home-entities">
          ${sectionGo("#explore", "Explore")}
          <h2 class="home-card-title">Substrate</h2>
          <div class="entity-count-row">
            ${entityTiles.map(([key, label, href]) => `
              <a class="entity-count" href="${href}">
                <span class="stat-n">${counts[key] ?? 0}</span>
                <span class="stat-l">${esc(label)}</span>
              </a>`).join("")}
          </div>
        </section>

        <section class="home-card home-review">
          ${sectionGo("#review", "Review")}
          <h2 class="home-card-title">To review (${reviewOpen})</h2>
          <div class="review-home-list">
            ${review.length
              ? review.map(reviewCard).join("")
              : `<div class="empty"><strong>Nothing waiting</strong><p>Open Reflections and competing Interpretations land here.</p></div>`}
          </div>
        </section>

        <div class="home-rail">
          <section class="home-card home-health">
            ${sectionGo("#ops", "Health")}
            <h2 class="home-card-title">Health</h2>
            <div id="home-health-body" class="home-health-body">
              <div class="muted">Loading doctor…</div>
            </div>
          </section>

          <section class="home-card home-search">
            ${sectionGo("#explore", "Explore")}
            <h2 class="home-card-title">Search</h2>
            <div class="search-bar">
              <select id="home-search-type" aria-label="Entity type">
                <option value="all">All entities</option>
                ${ENTITY_TYPES.map((e) => `<option value="${e.id}">${esc(e.label)}</option>`).join("")}
              </select>
              <input id="home-search-q" type="search" placeholder="Fuzzy search…" autocomplete="off" />
            </div>
            <div id="home-search-results" class="search-results" hidden></div>
          </section>

          <section class="home-card home-inject">
            <h2 class="home-card-title">Inject</h2>
            <p class="home-card-sub muted">Build a context pack in place</p>
            <form id="home-pack-form" class="stack-form compact">
              <label>Query<input name="query" required placeholder="What was decided about…?" /></label>
              <label>Domain
                <select name="domain" ${domains.length ? "required" : "disabled"}>
                  ${domainOptions}
                </select>
              </label>
              <button class="btn primary" type="submit" ${domains.length ? "" : "disabled"}>Build pack</button>
            </form>
            <div id="home-pack-meta" class="muted"></div>
            <pre id="home-pack-out" class="json-block" hidden></pre>
          </section>
        </div>
      </div>`;

    wireHomeSearch();
    wireHomeInject();
    loadHomeDoctor(sum).finally(() => syncReviewToRailHeight());
    syncReviewToRailHeight();
  } catch (err) {
    app.innerHTML = empty("Could not load overview", err.message);
  }
}

let _reviewRailSync = null;

function syncReviewToRailHeight() {
  const review = $(".home-review", app);
  const rail = $(".home-rail", app);
  if (!review || !rail) return;

  const apply = () => {
    // Match Review card to Search + Inject + Health (gaps + padding included).
    const h = Math.round(rail.getBoundingClientRect().height);
    if (h > 0) review.style.height = `${h}px`;
  };
  apply();

  if (_reviewRailSync) {
    _reviewRailSync.disconnect();
    _reviewRailSync = null;
  }
  if (typeof ResizeObserver === "function") {
    _reviewRailSync = new ResizeObserver(() => apply());
    _reviewRailSync.observe(rail);
  }
}

function friendlyDoctorName(name) {
  const raw = String(name || "");
  const map = {
    "dependency:fastapi": "FastAPI",
    "dependency:mcp": "MCP SDK",
    "dependency:psycopg": "Postgres driver",
    "dependency:cryptography": "Crypto library",
    "store:sqlite": "SQLite store",
    "store:postgres": "Postgres store",
    "store:migrations": "Schema migrations",
    "store:connection": "Store connection",
    "review:queue": "Review queue",
    "runtime:queue": "Runtime queue",
    "llm:provider": "LLM provider",
    "llm:server": "LLM server",
    "llm:api_key": "LLM API key",
    "embedder": "Embeddings",
    "config:policies": "Policies",
    "config:judgment": "Judgment profile",
    "encryption": "Encryption key",
    "mcp:cursor": "Cursor MCP",
    "mcp:claude-code": "Claude Code MCP",
    "mcp:claude-desktop": "Claude Desktop MCP",
    "connectors:schedule": "Connector schedule",
    "connectors:credentials": "Connector credentials",
    "connectors:instances": "Connector instances",
    "connectors:due": "Due connectors",
    "acc:feed": "Analysis feed",
    "ollama:extraction": "Ollama extraction model",
    "ollama:embeddings": "Ollama embedding model",
    "ollama:models": "Ollama models",
    "ollama:server": "Ollama server",
  };
  if (map[raw]) return map[raw];
  if (raw.startsWith("connectors:auth:")) return "Connector auth";
  if (raw.startsWith("mcp:")) {
    const client = raw.slice(4).replace(/[-_]/g, " ");
    return `${client.replace(/\b\w/g, (c) => c.toUpperCase())} MCP`;
  }
  if (raw.startsWith("dependency:")) {
    return `${raw.slice(11)} package`;
  }
  return raw
    .split(":")
    .map((part) => part.replace(/[_-]/g, " "))
    .map((part) => part.replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(" · ");
}

function friendlyDoctorDetail(name, detail) {
  let d = String(detail || "").trim();
  if (!d) return "";
  // Shorten absolute sqlite URLs / home paths
  d = d.replace(/sqlite:\/\/+/, "");
  d = d.replace(/\/home\/[^/]+\//g, "~/");
  if (name === "store:sqlite" || name === "store:postgres") {
    const leaf = d.split("/").pop();
    if (leaf) d = leaf;
  }
  if (name && name.startsWith("connectors:auth:")) {
    const id = name.slice("connectors:auth:".length);
    d = `${id.slice(0, 14)}${id.length > 14 ? "…" : ""} · ${d}`;
  }
  if (name === "llm:server") {
    d = d.replace(/^https?:\/\/[^ ]+\s*·\s*/, "");
  }
  return truncate(d, 72);
}

async function loadHomeDoctor(sum) {
  const box = $("#home-health-body");
  if (!box) return;
  try {
    let doc = null;
    let lastErr = null;
    for (const path of ["/api/health/doctor", "/api/doctor"]) {
      try {
        doc = await api(path);
        break;
      } catch (err) {
        lastErr = err;
      }
    }
    if (!doc) throw lastErr || new Error("doctor unavailable");

    const checks = Array.isArray(doc.checks) ? doc.checks : [];
    const counts = doc.counts || {
      ok: checks.filter((c) => c.status === "ok").length,
      warn: checks.filter((c) => c.status === "warn").length,
      fail: checks.filter((c) => c.status === "fail").length,
    };
    const ordered = [
      ...checks.filter((c) => c.status === "fail"),
      ...checks.filter((c) => c.status === "warn"),
      ...checks.filter((c) => c.status === "ok"),
    ];
    const mark = (status) => (
      status === "fail" ? "✗" : (status === "warn" ? "!" : "✓")
    );
    box.innerHTML = `
      <div class="doctor-compact">
        <div class="doctor-score" aria-label="Doctor counts">
          <span class="doctor-chip doctor-chip--ok">✓ ${counts.ok ?? 0}</span>
          <span class="doctor-chip doctor-chip--warn">! ${counts.warn ?? 0}</span>
          <span class="doctor-chip doctor-chip--fail">✗ ${counts.fail ?? 0}</span>
        </div>
        <p class="doctor-kv muted">
          <span>${esc(doc.llm || "—")}</span>
          <span>${esc(doc.model || "—")}</span>
          <span>embed ${esc(doc.embedder || "—")}</span>
        </p>
        ${sum?.cognize_halt
          ? `<p class="doctor-halt">cognize halt · ${esc(sum.cognize_halt)}</p>`
          : ""}
        <ul class="doctor-issues doctor-issues--all">
          ${ordered.map((c) => {
            const label = friendlyDoctorName(c.name);
            const detail = friendlyDoctorDetail(c.name, c.detail);
            return `
            <li>
              <span class="doctor-mark doctor-mark--${esc(c.status)}">${mark(c.status)}</span>
              <span class="doctor-issue-text">
                <strong>${esc(label)}</strong>
                ${detail ? ` <span class="muted">${esc(detail)}</span>` : ""}
              </span>
            </li>`;
          }).join("")}
        </ul>
      </div>`;
  } catch (err) {
    box.innerHTML = `
      ${sum?.cognize_halt
        ? `<div class="health-banner warn">Cognize halt · ${esc(sum.cognize_halt)}</div>`
        : `<div class="health-banner ok">Cognize gate clear</div>`}
      <p class="muted">Doctor unavailable · ${esc(err.message)} — restart <code>twin serve</code></p>`;
  }
}

function wireHomeInject() {
  const form = $("#home-pack-form");
  if (!form) return;
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const out = $("#home-pack-out");
    const meta = $("#home-pack-meta");
    out.hidden = true;
    try {
      const pack = await api("/api/context_pack", {
        method: "POST",
        body: JSON.stringify({
          query: fd.get("query"),
          target_domain: fd.get("domain") || "technical",
        }),
      });
      meta.textContent = `Narratives: ${(pack.narratives || []).length} · Reflections: ${(pack.open_reflections || []).length}`;
      out.hidden = false;
      out.textContent = pack.context_pack || JSON.stringify(pack, null, 2);
      toast("Pack built");
    } catch (err) {
      toast(err.message, false);
    }
  });
}

let _searchCache = null;
async function loadSearchCorpus() {
  if (_searchCache) return _searchCache;
  const items = [];
  await Promise.all(ENTITY_TYPES.map(async (meta) => {
    try {
      const rows = await api(`${meta.list}${meta.list.includes("?") ? "&" : "?"}vault=${encodeURIComponent(VAULT)}`);
      const list = Array.isArray(rows) ? rows : (rows.items || rows.stances || []);
      for (const row of list.slice(0, 200)) {
        const headline = entityHeadline(row, meta.id);
        items.push({
          type: meta.id,
          label: meta.label,
          id: row.id,
          text: `${headline} ${row.id}`,
          headline,
          href: `#explore/${meta.id}/${encodeURIComponent(row.id)}`,
        });
      }
    } catch {
      /* skip missing endpoints */
    }
  }));
  _searchCache = items;
  return items;
}

function wireHomeSearch() {
  const input = $("#home-search-q");
  const typeEl = $("#home-search-type");
  const box = $("#home-search-results");
  if (!input || !box) return;

  let timer = null;
  const run = async () => {
    const q = input.value.trim();
    const type = typeEl.value;
    if (q.length < 2) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = `<div class="muted">Searching…</div>`;
    try {
      const corpus = await loadSearchCorpus();
      const hits = corpus
        .filter((item) => type === "all" || item.type === type)
        .map((item) => ({ ...item, score: fuzzyScore(q, item.text) }))
        .filter((item) => item.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 12);
      box.innerHTML = hits.length
        ? hits.map((h) => `
            <a class="search-hit" href="${h.href}">
              <span class="tag">${esc(h.label)}</span>
              <strong>${esc(truncate(stripMd(h.headline), 72))}</strong>
              <span class="muted">${esc(h.id)}</span>
            </a>`).join("")
        : `<div class="muted">No matches</div>`;
    } catch (err) {
      box.innerHTML = `<div class="muted">${esc(err.message)}</div>`;
    }
  };

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(run, 180);
  });
  typeEl.addEventListener("change", run);
}

async function paneSessions() {
  setChrome("Sessions", "Active host sessions");
  const total = MOCK_SESSIONS.reduce((n, s) => n + s.open, 0);
  app.innerHTML = `
    <section class="detail-card">
      <p class="lede">Mock telemetry — ${total} open sessions across providers.</p>
      <div class="session-grid session-grid--lg">
        ${MOCK_SESSIONS.map((s) => `
          <div class="session-pill">
            <span class="session-n">${s.open}</span>
            <span class="session-l">${esc(s.provider)}</span>
          </div>`).join("")}
      </div>
      <p class="muted">Real host session counts will replace this when the provider bridge lands.</p>
    </section>`;
}

function entityTypeFromId(id) {
  const s = String(id || "");
  const map = {
    nar: "narrative",
    ref: "reflection",
    intp: "interpretation",
    sit: "situation",
    jud: "stance",
    evac: "evidence",
    ev: "evidence",
    crel: "relation",
    rel: "relation",
    trc: "trace",
    pct: "percept",
  };
  const underscored = s.split("_")[0];
  if (map[underscored]) return map[underscored];
  // Legacy / compact ids without underscore (e.g. pctreflect…)
  const prefixes = Object.keys(map).sort((a, b) => b.length - a.length);
  for (const pre of prefixes) {
    if (s.startsWith(pre) && s.length > pre.length) return map[pre];
  }
  return null;
}

function exploreHref(type, id) {
  return `#explore/${type}/${encodeURIComponent(id)}`;
}

async function fetchEntityBundle(meta, id) {
  const row = await api(meta.show(id));
  let relations = Array.isArray(row.relations) ? [...row.relations] : [];
  if (!relations.length) {
    try {
      const q = `vault=${encodeURIComponent(VAULT)}`;
      const [fromR, toR] = await Promise.all([
        api(`/api/relations?${q}&from_id=${encodeURIComponent(id)}`),
        api(`/api/relations?${q}&to_id=${encodeURIComponent(id)}`),
      ]);
      const map = new Map();
      for (const r of [...(Array.isArray(fromR) ? fromR : []), ...(Array.isArray(toR) ? toR : [])]) {
        if (r?.id) map.set(r.id, r);
      }
      relations = [...map.values()];
    } catch {
      /* relations optional */
    }
  }
  return { row, relations };
}

/** Classify edges into past (left) / future (right) / related for the lineage strip. */
function classifyLineage(entityId, relations) {
  const left = [];
  const right = [];
  const peers = [];
  const seen = new Set();

  const push = (bucket, other, label) => {
    if (!other || other === entityId) return;
    const key = `${other}|${label}`;
    if (seen.has(key)) return;
    seen.add(key);
    bucket.push({ id: other, type: entityTypeFromId(other), label });
  };

  for (const rel of relations || []) {
    const raw = String(rel.type || "").replace(/_/g, "-");
    const from = rel.from_id;
    const to = rel.to_id;
    if (raw === "supersedes" || raw === "continues") {
      // from = newer / continuing; to = earlier
      if (from === entityId) push(left, to, raw);
      else if (to === entityId) push(right, from, raw);
      continue;
    }
    if (raw === "depends-on") {
      if (from === entityId) push(left, to, raw);
      else if (to === entityId) push(right, from, raw);
      continue;
    }
    if (raw === "part-of") {
      if (from === entityId) push(right, to, "part of");
      else if (to === entityId) push(left, from, "contains");
      continue;
    }
    if (raw === "same-originating-decision") {
      if (from === entityId) push(left, to, "same origin");
      else if (to === entityId) push(left, from, "same origin");
      continue;
    }
    // Parallel / competing links stay on the same layer (not Past/Next).
    if (
      raw === "contradicts"
      || raw === "supports"
      || raw === "related"
      || raw === "same-as"
    ) {
      if (from === entityId) push(peers, to, raw);
      else if (to === entityId) push(peers, from, raw);
      continue;
    }
    if (from === entityId) push(peers, to, raw);
    else if (to === entityId) push(peers, from, raw);
  }
  return { left, right, peers, related: peers };
}

/** Structural origins for each entity kind (not only Relation rows). */
function originNodesFor(meta, row) {
  const out = [];
  const seen = new Set();
  const add = (id, label, typeHint) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    out.push({
      id,
      type: entityTypeFromId(id) || typeHint || null,
      label: label || typeHint || "origin",
    });
  };

  switch (meta.id) {
    case "reflection":
      for (const id of row.evidence_ids || []) add(id, "evidence", "evidence");
      for (const e of row.evidence || []) add(e.id || e, "evidence", "evidence");
      for (const id of row.situation_ids || []) add(id, "situation", "situation");
      break;
    case "interpretation":
      for (const id of row.reflection_ids || []) add(id, "reflection", "reflection");
      for (const id of row.situation_ids || []) add(id, "situation", "situation");
      for (const id of row.evidence_ids || []) add(id, "evidence", "evidence");
      for (const e of row.evidence || []) add(e.id || e, "evidence", "evidence");
      break;
    case "narrative":
      for (const e of row.evidence || []) add(e.id || e, "evidence", "evidence");
      for (const id of row.evidence_ids || []) add(id, "evidence", "evidence");
      for (const r of row.open_reflections || []) add(r.id || r, "reflection", "reflection");
      break;
    case "evidence":
      if (row.percept_id) add(row.percept_id, "percept", "percept");
      if (row.source_id && entityTypeFromId(row.source_id)) {
        add(row.source_id, "source", entityTypeFromId(row.source_id));
      }
      break;
    case "situation":
      for (const id of row.percept_ids || []) add(id, "percept", "percept");
      break;
    case "stance":
      for (const id of row.evidence_ids || []) add(id, "evidence", "evidence");
      for (const id of row.narrative_ids || []) add(id, "narrative", "narrative");
      break;
    case "relation":
      if (row.from_id) add(row.from_id, "from", entityTypeFromId(row.from_id));
      break;
    case "trace":
      if (row.resource_id) {
        add(
          row.resource_id,
          row.resource_kind || "resource",
          entityTypeFromId(row.resource_id) || row.resource_kind,
        );
      }
      break;
    case "percept": {
      if (isDerivedPercept(row)) {
        const md = row.metadata || {};
        for (const id of md.source_percept_ids || md.percept_ids || []) {
          add(id, "source", "percept");
        }
        for (const id of md.evidence_ids || []) add(id, "evidence", "evidence");
        for (const e of md.evidence || []) add(e.id || e, "evidence", "evidence");
        // Connector synthetic is wrong for Cognize-derived percepts — skip it.
        break;
      }
      let sensor = row.source_sensor || "";
      let label = connectorLabel(sensor);
      if (!label && /^GitHub\b/i.test(String(row.content || ""))) {
        sensor = "github";
        label = "GitHub";
      }
      if (!label && row.percept_type && !/^unknown$/i.test(row.percept_type)) {
        label = connectorLabel(row.percept_type) || pascalStatus(row.percept_type);
        sensor = row.percept_type;
      }
      if (label) {
        out.push({
          id: `origin:${sensor || label}`,
          type: null,
          title: label,
          label: "connector",
          synthetic: true,
        });
      }
      break;
    }
    default:
      break;
  }
  return out;
}

function downstreamNodesFor(meta, row) {
  const out = [];
  const seen = new Set();
  const add = (id, label, typeHint) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    out.push({
      id,
      type: entityTypeFromId(id) || typeHint || null,
      label: label || typeHint || "next",
    });
  };
  if (meta.id === "relation" && row.to_id) {
    add(row.to_id, "to", entityTypeFromId(row.to_id));
  }
  if (meta.id === "evidence" && row.target_id) {
    add(
      row.target_id,
      row.target_kind || "target",
      entityTypeFromId(row.target_id) || row.target_kind,
    );
  }
  return out;
}

function linkedSeedNodes(row) {
  const out = [];
  const add = (id, hint) => {
    if (!id) return;
    out.push({ id, type: entityTypeFromId(id) || hint, label: hint || "linked" });
  };
  for (const id of row.evidence_ids || []) add(id, "evidence");
  for (const id of row.situation_ids || []) add(id, "situation");
  for (const id of row.reflection_ids || []) add(id, "reflection");
  for (const id of row.percept_ids || []) add(id, "percept");
  if (row.percept_id) add(row.percept_id, "percept");
  if (row.target_id) add(row.target_id, row.target_kind || "linked");
  return out;
}

function mergeNodes(primary, extra) {
  const seen = new Set(primary.map((n) => n.id));
  const out = [...primary];
  for (const n of extra) {
    if (!n?.id || seen.has(n.id)) continue;
    seen.add(n.id);
    out.push(n);
  }
  return out;
}

const _titleCache = new Map();

async function resolveNodeTitle(n) {
  if (n.synthetic) {
    const t = n.title || connectorLabel(String(n.id || "").replace(/^origin:/, "")) || n.id;
    return t;
  }
  if (n.title && n.title !== n.id) return n.title;
  const cached = _titleCache.get(n.id);
  if (cached && cached !== n.id) return cached;
  const type = n.type;
  const meta = type ? ENTITY_TYPES.find((e) => e.id === type) : null;
  if (!meta) {
    return n.title || n.id;
  }
  try {
    const row = await api(meta.show(n.id));
    const title = stripMd(entityHeadline(row, type)) || n.id;
    _titleCache.set(n.id, title);
    return title;
  } catch {
    _titleCache.set(n.id, n.id);
    return n.id;
  }
}

async function fetchRelationsFor(id) {
  try {
    const q = `vault=${encodeURIComponent(VAULT)}`;
    const [fromR, toR] = await Promise.all([
      api(`/api/relations?${q}&from_id=${encodeURIComponent(id)}`),
      api(`/api/relations?${q}&to_id=${encodeURIComponent(id)}`),
    ]);
    const map = new Map();
    for (const r of [...(Array.isArray(fromR) ? fromR : []), ...(Array.isArray(toR) ? toR : [])]) {
      if (r?.id) map.set(r.id, r);
    }
    return [...map.values()];
  } catch {
    return [];
  }
}

function normalizeFlowEdgeType(type) {
  return String(type || "").replace(/_/g, "-").toLowerCase().trim();
}

/** Collapse A→B and B→A of the same type into one bidirectional edge. */
function dedupeFlowEdges(edges) {
  const map = new Map();
  for (const e of edges || []) {
    const fromId = e.from_id;
    const toId = e.to_id;
    if (!fromId || !toId || fromId === toId) continue;
    const type = normalizeFlowEdgeType(e.type || e.label || "related");
    const lo = fromId < toId ? fromId : toId;
    const hi = fromId < toId ? toId : fromId;
    const key = `${lo}|${hi}|${type}`;
    const existing = map.get(key);
    if (!existing) {
      map.set(key, {
        from_id: fromId,
        to_id: toId,
        type: e.type || e.label || "related",
        bidirectional: !!e.bidirectional,
      });
      continue;
    }
    if (existing.from_id !== fromId || existing.to_id !== toId || e.bidirectional) {
      existing.bidirectional = true;
    }
  }
  return [...map.values()];
}

function flowEdgeGeometry(a, b, idx) {
  const sameCol = Math.abs(a.x - b.x) < 40;
  let d;
  let lx;
  let ly;
  if (sameCol) {
    const down = b.y >= a.y;
    const y1 = down ? a.y + a.h / 2 - 2 : a.y - a.h / 2 + 2;
    const y2 = down ? b.y - b.h / 2 + 2 : b.y + b.h / 2 - 2;
    const side = (idx % 2 === 0) ? 1 : -1;
    const lane = a.x + side * (a.w / 2 + 40 + (idx % 4) * 18);
    const x1 = a.x + side * (a.w / 2 - 4);
    const x2 = b.x + side * (b.w / 2 - 4);
    d = `M ${x1} ${y1} C ${lane} ${y1}, ${lane} ${y2}, ${x2} ${y2}`;
    lx = lane + side * 10;
    ly = (y1 + y2) / 2;
  } else {
    const ltr = b.x > a.x;
    const x1 = ltr ? a.x + a.w / 2 - 4 : a.x - a.w / 2 + 4;
    const x2 = ltr ? b.x - b.w / 2 + 4 : b.x + b.w / 2 - 4;
    const y1 = a.y;
    const y2 = b.y;
    const mx = (x1 + x2) / 2;
    const bump = ((idx % 7) - 3) * 16;
    d = `M ${x1} ${y1} C ${mx} ${y1 + bump}, ${mx} ${y2 - bump}, ${x2} ${y2}`;
    lx = mx;
    ly = (y1 + y2) / 2 + bump * 0.15 - 12;
  }
  return { d, lx, ly, sameCol };
}

function buildFlowEdgeSvg(edges, pos, markerId) {
  const deduped = dedupeFlowEdges(edges);
  return deduped.map((e, idx) => {
    const a = pos.get(e.from_id);
    const b = pos.get(e.to_id);
    if (!a || !b) return "";
    const label = relationEdgeLabel(e.type || e.label || "");
    const { d, lx, ly, sameCol } = flowEdgeGeometry(a, b, idx);
    const labelHtml = label
      ? `<foreignObject x="${lx - 52}" y="${ly - 12}" width="104" height="24">
        <div xmlns="http://www.w3.org/1999/xhtml" class="flow-edge-label">${esc(label)}</div>
      </foreignObject>`
      : "";
    const markers = e.bidirectional
      ? `marker-start="url(#${markerId})" marker-end="url(#${markerId})"`
      : `marker-end="url(#${markerId})"`;
    return `<g class="flow-edge${sameCol ? " flow-edge--local" : ""}${e.bidirectional ? " flow-edge--bidir" : ""}" data-from="${esc(e.from_id)}" data-to="${esc(e.to_id)}">
      <path d="${d}" ${markers} />
      ${labelHtml}
    </g>`;
  }).join("");
}

function readFlowNodePos(el) {
  return {
    x: parseFloat(el.style.left) + el.offsetWidth / 2,
    y: parseFloat(el.style.top) + el.offsetHeight / 2,
    w: el.offsetWidth,
    h: el.offsetHeight,
  };
}

function redrawFlowEdges(canvas) {
  const svg = $(".flow-graph-svg", canvas);
  if (!svg) return;
  let edges = [];
  try {
    edges = JSON.parse(canvas.dataset.edges || "[]");
  } catch {
    edges = [];
  }
  const markerId = canvas.dataset.markerId || "flow-arrow";
  const pos = new Map();
  canvas.querySelectorAll(".flow-node[data-node-id]").forEach((el) => {
    pos.set(el.dataset.nodeId, readFlowNodePos(el));
  });
  const defs = svg.querySelector("defs");
  svg.innerHTML = "";
  if (defs) svg.appendChild(defs);
  else {
    svg.insertAdjacentHTML("afterbegin", `<defs>
      <marker id="${markerId}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#9a92b8" />
      </marker>
    </defs>`);
  }
  svg.insertAdjacentHTML("beforeend", buildFlowEdgeSvg(edges, pos, markerId));
}

function bindGraphPan(root) {
  root.querySelectorAll("[data-graph-pan]").forEach((viewport) => {
    if (viewport.dataset.panBound === "1") return;
    viewport.dataset.panBound = "1";
    const canvas = $(".flow-graph-canvas", viewport);
    if (!canvas) return;
    let tx = 0;
    let ty = 0;
    let scale = 1;
    let mode = null; // "pan" | "node"
    let sx = 0;
    let sy = 0;
    let ox = 0;
    let oy = 0;
    let nodeEl = null;
    let nodeStartLeft = 0;
    let nodeStartTop = 0;
    let moved = false;

    const apply = () => {
      canvas.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    };
    apply();

    const toCanvasDelta = (dx, dy) => ({
      x: dx / scale,
      y: dy / scale,
    });

    viewport.addEventListener("pointerdown", (ev) => {
      if (ev.target.closest("button")) return;
      const node = ev.target.closest(".flow-node");
      sx = ev.clientX;
      sy = ev.clientY;
      moved = false;
      if (node) {
        // Kill native link/image drag so cards can be repositioned.
        ev.preventDefault();
        mode = "node";
        nodeEl = node;
        nodeStartLeft = parseFloat(node.style.left) || 0;
        nodeStartTop = parseFloat(node.style.top) || 0;
        node.classList.add("is-dragging");
        viewport.classList.add("is-dragging-node");
      } else {
        mode = "pan";
        viewport.classList.add("is-panning");
        ox = tx;
        oy = ty;
      }
      viewport.setPointerCapture?.(ev.pointerId);
    });

    viewport.addEventListener("dragstart", (ev) => {
      if (ev.target.closest(".flow-node")) ev.preventDefault();
    });

    viewport.addEventListener("pointermove", (ev) => {
      if (!mode) return;
      const dx = ev.clientX - sx;
      const dy = ev.clientY - sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      if (mode === "pan") {
        tx = ox + dx;
        ty = oy + dy;
        apply();
        return;
      }
      if (mode === "node" && nodeEl) {
        const d = toCanvasDelta(dx, dy);
        nodeEl.style.left = `${nodeStartLeft + d.x}px`;
        nodeEl.style.top = `${nodeStartTop + d.y}px`;
        redrawFlowEdges(canvas);
      }
    });

    const end = (ev) => {
      const el = nodeEl;
      const wasMoved = moved;
      const wasNode = mode === "node";
      if (el) el.classList.remove("is-dragging");
      mode = null;
      nodeEl = null;
      moved = false;
      viewport.classList.remove("is-panning");
      viewport.classList.remove("is-dragging-node");
      // Click (no drag) → navigate
      if (wasNode && el && !wasMoved) {
        const href = el.dataset.href;
        if (href) location.hash = href.startsWith("#") ? href.slice(1) : href;
      }
    };
    viewport.addEventListener("pointerup", end);
    viewport.addEventListener("pointercancel", end);

    const shell = viewport.closest(".flow-graph");
    shell?.querySelector("[data-graph-reset]")?.addEventListener("click", () => {
      tx = 0; ty = 0; scale = 1; apply();
      // Restore initial positions if stored
      try {
        const initial = JSON.parse(canvas.dataset.initialPos || "{}");
        canvas.querySelectorAll(".flow-node[data-node-id]").forEach((el) => {
          const p = initial[el.dataset.nodeId];
          if (!p) return;
          el.style.left = `${p.left}px`;
          el.style.top = `${p.top}px`;
        });
        redrawFlowEdges(canvas);
      } catch { /* keep current */ }
    });
    shell?.querySelector("[data-graph-zoom-in]")?.addEventListener("click", () => {
      scale = Math.min(1.8, scale + 0.12); apply();
    });
    shell?.querySelector("[data-graph-zoom-out]")?.addEventListener("click", () => {
      scale = Math.max(0.55, scale - 0.12); apply();
    });
  });
}

/** Layered HTML+SVG flowchart with pan/zoom chrome. */
function renderFlowGraph({
  title = "Graph",
  subtitle = "",
  nodes = [],
  edges = [],
  focusId = "",
  layerOf = null,
} = {}) {
  if (!nodes.length) return empty(`No ${title.toLowerCase()} yet`);

  const typeOrder = [
    "percept", "evidence", "situation", "reflection", "interpretation",
    "narrative", "stance", "trace", "entity", "origin",
  ];

  const layers = new Map();
  if (typeof layerOf === "function") {
    for (const n of nodes) {
      const li = Number(layerOf(n)) || 0;
      if (!layers.has(li)) layers.set(li, []);
      layers.get(li).push(n);
    }
  } else {
    const byType = new Map();
    for (const n of nodes) {
      const t = n.type || "entity";
      if (!byType.has(t)) byType.set(t, []);
      byType.get(t).push(n);
    }
    let i = 0;
    for (const t of typeOrder) {
      if (!byType.has(t)) continue;
      layers.set(i, byType.get(t));
      i += 1;
    }
    for (const [t, list] of byType) {
      if (typeOrder.includes(t)) continue;
      layers.set(i, list);
      i += 1;
    }
  }

  const layerKeys = [...layers.keys()].sort((a, b) => a - b);
  const colW = 420;
  const rowH = 128;
  const nodeW = 230;
  const nodeH = 80;
  const padX = 80;
  const padY = 64;
  const maxRows = Math.max(...layerKeys.map((k) => layers.get(k).length), 1);
  const width = Math.max(900, padX * 2 + layerKeys.length * colW);
  const height = Math.max(460, padY * 2 + maxRows * rowH);

  const pos = new Map();
  layerKeys.forEach((lk, ci) => {
    const col = layers.get(lk);
    col.forEach((n, ri) => {
      pos.set(n.id, {
        x: padX + ci * colW + colW / 2,
        y: padY + ri * rowH + rowH / 2,
        w: nodeW,
        h: nodeH,
        col: ci,
      });
    });
  });

  for (let pass = 0; pass < 2; pass += 1) {
    layerKeys.forEach((lk, ci) => {
      if (ci === 0) return;
      const col = layers.get(lk);
      const scores = new Map();
      for (const n of col) {
        let sum = 0;
        let c = 0;
        for (const e of edges) {
          const other = e.from_id === n.id ? e.to_id : (e.to_id === n.id ? e.from_id : null);
          if (!other || !pos.has(other)) continue;
          const op = pos.get(other);
          if (op.col >= ci) continue;
          sum += op.y;
          c += 1;
        }
        scores.set(n.id, c ? sum / c : pos.get(n.id).y);
      }
      col.sort((a, b) => (scores.get(a.id) || 0) - (scores.get(b.id) || 0));
      col.forEach((n, ri) => {
        pos.get(n.id).y = padY + ri * rowH + rowH / 2;
      });
    });
  }

  const markerId = `flow-arrow-${Math.random().toString(36).slice(2, 9)}`;
  const edgeSvg = buildFlowEdgeSvg(edges, pos, markerId);

  const initialPos = {};
  const nodesHtml = nodes.map((n) => {
    const p = pos.get(n.id);
    if (!p) return "";
    const isFocus = focusId && n.id === focusId;
    const title = truncate(stripMd(n.title || n.id), 72);
    const kind = n.synthetic ? "Origin" : (n.type || "entity");
    const left = p.x - p.w / 2;
    const top = p.y - p.h / 2;
    initialPos[n.id] = { left, top };
    const style = `left:${left}px;top:${top}px;width:${p.w}px;min-height:${p.h}px`;
    if (n.synthetic) {
      return `<div class="flow-node flow-node--origin${isFocus ? " is-focus" : ""}" data-node-id="${esc(n.id)}" draggable="false" style="${style}">
        <span class="flow-node-kind">${esc(kind)}</span>
        <strong class="flow-node-title">${esc(title)}</strong>
      </div>`;
    }
    const href = n.type && n.type !== "entity" ? exploreHref(n.type, n.id) : "#explore";
    return `<div class="flow-node${isFocus ? " is-focus" : ""}" role="link" tabindex="0" data-href="${esc(href)}" data-explore-nav="1" data-node-id="${esc(n.id)}" title="${esc(n.id)}" draggable="false" style="${style}">
      <span class="flow-node-kind">${esc(kind)}</span>
      <strong class="flow-node-title">${esc(title)}</strong>
    </div>`;
  }).join("");

  const colLabels = layerKeys.map((lk, ci) => {
    const x = padX + ci * colW + colW / 2;
    let label;
    if (typeof layerOf === "function") {
      label = lk === 0 ? "Here" : (lk < 0 ? "Past" : "Next");
    } else {
      label = (layers.get(lk)[0] || {}).type || "entity";
    }
    return `<div class="flow-col-label" style="left:${x}px">${esc(String(label))}</div>`;
  }).join("");

  const edgesJson = esc(JSON.stringify(dedupeFlowEdges(edges).map((e) => ({
    from_id: e.from_id,
    to_id: e.to_id,
    type: e.type || e.label || "related",
    bidirectional: !!e.bidirectional,
  }))));
  const initialJson = esc(JSON.stringify(initialPos));

  return `<section class="flow-graph" aria-label="${esc(title)}">
    <header class="flow-graph-head">
      <div>
        <h3>${esc(title)}</h3>
        ${subtitle ? `<p class="muted">${esc(subtitle)}</p>` : ""}
      </div>
      <div class="flow-graph-toolbar">
        <button type="button" class="flow-graph-btn" data-graph-zoom-out title="Zoom out">−</button>
        <button type="button" class="flow-graph-btn" data-graph-zoom-in title="Zoom in">+</button>
        <button type="button" class="flow-graph-btn" data-graph-reset title="Reset view">Reset</button>
        <span class="muted flow-graph-hint">Drag cards · pan background</span>
      </div>
    </header>
    <div class="flow-graph-viewport" data-graph-pan>
      <div class="flow-graph-canvas" style="width:${width}px;height:${height}px" data-edges="${edgesJson}" data-initial-pos="${initialJson}" data-marker-id="${esc(markerId)}">
        ${colLabels}
        <svg class="flow-graph-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
          <defs>
            <marker id="${markerId}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#9a92b8" />
            </marker>
          </defs>
          ${edgeSvg}
        </svg>
        <div class="flow-graph-nodes">${nodesHtml}</div>
      </div>
    </div>
  </section>`;
}

async function buildLineageNetwork(entityId, meta, row, seedRelations, { maxDepth = 6, maxNodes = 48 } = {}) {
  const nodes = new Map();
  const edges = [];
  const depth = new Map();
  const relCache = new Map([[entityId, seedRelations || []]]);
  const edgeSeen = new Set();

  const addNode = (n) => {
    if (!n?.id || nodes.has(n.id)) return;
    nodes.set(n.id, {
      id: n.id,
      type: n.type || entityTypeFromId(n.id) || "entity",
      title: n.title || null,
      synthetic: !!n.synthetic,
      label: n.label || "",
    });
  };

  const addEdge = (fromId, toId, type) => {
    if (!fromId || !toId || fromId === toId) return;
    const key = `${fromId}|${toId}|${type}`;
    if (edgeSeen.has(key)) return;
    edgeSeen.add(key);
    edges.push({ from_id: fromId, to_id: toId, type: type || "related" });
  };

  addNode({
    id: entityId,
    type: meta.id,
    title: stripMd(entityHeadline(row, meta.id)),
  });
  depth.set(entityId, 0);

  // Structural origins on root (skip connector synthetic for derived percepts)
  for (const o of originNodesFor(meta, row)) {
    addNode(o);
    if (!depth.has(o.id)) depth.set(o.id, -1);
    addEdge(o.id, entityId, o.label || "origin");
  }

  let frontier = [entityId];
  for (let hop = 0; hop < maxDepth && frontier.length && nodes.size < maxNodes; hop += 1) {
    const next = [];
    for (const id of frontier) {
      let rels = relCache.get(id);
      if (!rels) {
        // eslint-disable-next-line no-await-in-loop
        rels = await fetchRelationsFor(id);
        relCache.set(id, rels);
      }
      const classified = classifyLineage(id, rels);
      const walk = [
        ...classified.left.map((n) => ({ n, dir: -1 })),
        ...classified.right.map((n) => ({ n, dir: 1 })),
        ...classified.peers.map((n) => ({ n, dir: 0 })),
      ];
      for (const { n, dir } of walk) {
        if (!n?.id) continue;
        addNode(n);
        const nd = (depth.get(id) || 0) + dir;
        if (!depth.has(n.id)) {
          depth.set(n.id, nd);
          next.push(n.id);
        }
        if (dir < 0) addEdge(n.id, id, n.label);
        else addEdge(id, n.id, n.label);
        if (nodes.size >= maxNodes) break;
      }
      if (nodes.size >= maxNodes) break;
    }
    frontier = next;
  }

  // Any leftover peer links on the root stay on the Here layer.
  const classifiedRoot = classifyLineage(entityId, seedRelations || []);
  for (const n of classifiedRoot.peers.slice(0, 12)) {
    if (nodes.has(n.id)) continue;
    if (nodes.size >= maxNodes) break;
    addNode(n);
    depth.set(n.id, 0);
    addEdge(entityId, n.id, n.label || "related");
  }

  const list = [...nodes.values()];
  await Promise.all(list.map(async (n) => {
    n.title = await resolveNodeTitle(n);
  }));

  return { nodes: list, edges, depth };
}

async function renderLineageGraph(entityId, meta, relations, row) {
  const net = await buildLineageNetwork(entityId, meta, row, relations, {
    maxDepth: 6,
    maxNodes: 56,
  });
  const past = [...net.depth.values()].filter((d) => d < 0);
  const next = [...net.depth.values()].filter((d) => d > 0);
  const depthNote = (past.length || next.length)
    ? `${net.nodes.length} nodes · drag cards to rearrange`
    : "No linked entities yet";
  return renderFlowGraph({
    title: "Lineage",
    subtitle: depthNote,
    nodes: net.nodes,
    edges: net.edges,
    focusId: entityId,
    layerOf: (n) => net.depth.get(n.id) || 0,
  });
}

async function renderExpandBody(meta, row, relations) {
  let bodyText = expandBodyText(meta, row);
  let prMetaHtml = "";
  if (meta.id === "percept") {
    const pr = parseGithubPrContent(row.content);
    if (pr) {
      prMetaHtml = renderPrMetaCard(pr);
      bodyText = pr.body || "";
    }
  }

  const kv = [];
  const add = (k, v) => {
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return;
    kv.push([k, Array.isArray(v) ? v.join(", ") : String(v)]);
  };
  add("ID", row.id);
  add("Domain", row.domain);
  add("Sensitivity", row.sensitivity);
  add("Grain", row.grain);
  add("Committed by", row.committed_by);
  add("Stale reason", row.epistemic?.stale_reason);
  add("Kind", row.kind || row.type || row.event_kind || (meta.id === "percept" && isDerivedPercept(row) ? "Derived" : ""));
  add("Strength", row.strength);
  add("Source", row.source_id);
  if (meta.id === "percept" && !isDerivedPercept(row)) {
    const origin = connectorLabel(row.source_sensor);
    if (origin) add("Origin", origin);
  }
  add("Created", formatWhen(row.created_at || row.ingested_at));
  if (row.derived_confidence?.label) add("Confidence", row.derived_confidence.label);

  const kvHtml = kv.length
    ? `<dl class="kv expand-kv">${kv.map(([k, v]) =>
        `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`
    : "";

  const descHtml = bodyText
    ? `<div class="expand-body md-body">${renderMd(bodyText)}</div>`
    : "";

  const lineageHtml = await renderLineageGraph(row.id, meta, relations, row);

  return `
    <div class="expand-panel entity-${meta.role}">
      ${prMetaHtml}
      ${descHtml}
      ${kvHtml}
      ${lineageHtml}
    </div>`;
}

/** Build titled nodes/edges for the Relations flowchart (once per load). */
async function buildRelationFlowData(relations) {
  const edges = (Array.isArray(relations) ? relations : [])
    .filter((r) => r?.from_id && r?.to_id)
    .map((r) => ({ from_id: r.from_id, to_id: r.to_id, type: r.type, id: r.id }));
  const nodeMap = new Map();
  const ensure = (id) => {
    if (!nodeMap.has(id)) {
      nodeMap.set(id, { id, type: entityTypeFromId(id) || "entity" });
    }
    return nodeMap.get(id);
  };
  for (const e of edges) {
    ensure(e.from_id);
    ensure(e.to_id);
  }
  const nodes = [...nodeMap.values()];
  await Promise.all(nodes.map(async (n) => {
    n.title = await resolveNodeTitle({ id: n.id, type: n.type === "entity" ? null : n.type });
  }));
  return { edges, nodes, nodeMap };
}

function filterRelationFlowData(data, query = "") {
  const q = String(query || "").trim();
  if (!q) return { edges: data.edges, nodes: data.nodes };
  const { nodeMap } = data;
  const nodeHit = (id) => {
    const n = nodeMap.get(id);
    return textIncludes(q, `${id} ${n?.title || ""} ${n?.type || ""}`);
  };
  const edges = data.edges.filter((e) =>
    textIncludes(q, `${e.id || ""} ${e.type || ""} ${e.from_id} ${e.to_id}`)
    || nodeHit(e.from_id)
    || nodeHit(e.to_id));
  const keep = new Set();
  for (const e of edges) {
    keep.add(e.from_id);
    keep.add(e.to_id);
  }
  return { edges, nodes: data.nodes.filter((n) => keep.has(n.id)) };
}

/** Full-graph Explore view for Relations (no accordion list). */
function renderRelationsFlowchart(data, focusId, query = "") {
  const q = String(query || "").trim();
  if (!data.edges.length) return empty("No relations yet");
  const { edges, nodes } = filterRelationFlowData(data, q);
  if (q && !edges.length) {
    return empty("No matches", `Nothing in Relations for “${q}”`);
  }
  return renderFlowGraph({
    title: q ? "Search in Relations" : "Relations",
    subtitle: `${edges.length} edges · ${nodes.length} nodes · drag to pan`,
    nodes,
    edges,
    focusId,
  });
}

function wireExploreSearch(meta, box, { onQuery } = {}) {
  const input = $("#explore-search-q", app);
  if (!input) return;

  let timer = null;
  const apply = () => {
    const q = input.value;
    setExploreChrome(meta, q);
    if (onQuery) {
      onQuery(q.trim());
      return;
    }
    const term = q.trim();
    let shown = 0;
    box.querySelectorAll(".entity-item").forEach((item) => {
      const hay = item.dataset.search || item.textContent || "";
      const ok = !term || textIncludes(term, hay);
      item.hidden = !ok;
      if (ok) shown += 1;
    });
    box.querySelectorAll(".percept-group").forEach((g) => {
      const any = [...g.querySelectorAll(".entity-item")].some((el) => !el.hidden);
      g.classList.toggle("is-search-empty", !any);
    });
    let emptyEl = $(".explore-search-empty", box);
    if (term && shown === 0) {
      if (!emptyEl) {
        emptyEl = document.createElement("div");
        emptyEl.className = "explore-search-empty";
        box.appendChild(emptyEl);
      }
      emptyEl.hidden = false;
      emptyEl.innerHTML = empty("No matches", `Nothing in ${meta.label} for “${term}”`);
    } else if (emptyEl) {
      emptyEl.hidden = true;
    }
  };

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(apply, 120);
  });
}

async function paneExplore(parts) {
  const type = parts[0] || "narrative";
  const focusId = parts[1] || "";
  const meta = ENTITY_TYPES.find((e) => e.id === type) || ENTITY_TYPES[0];
  setExploreChrome(meta);

  let counts = {};
  try {
    const sum = await api(`/api/center/summary?vault=${encodeURIComponent(VAULT)}`);
    counts = sum.counts || {};
    if (counts.evidence == null && sum.evidence != null) counts.evidence = sum.evidence;
  } catch {
    counts = {};
  }

  const tabs = ENTITY_TYPES.map((e) => {
    const key = e.id === "evidence" ? "evidence" : `${e.id}s`;
    const n = counts[key] ?? 0;
    const active = e.id === meta.id ? " active" : "";
    return `<a class="chip${active}" href="#explore/${e.id}">${esc(e.label)} (${n})</a>`;
  }).join("");

  app.innerHTML = `<div class="explore-layout">
    <div class="explore-tabs">${tabs}</div>
    <div class="explore-search">
      <input id="explore-search-q" type="search" placeholder="Search" autocomplete="off" aria-label="Search ${esc(meta.label)}" />
    </div>
    <div class="entity-list entity-${meta.role}">Loading…</div>
  </div>`;

  const box = $(".entity-list", app);

  if (meta.id === "relation") {
    try {
      const rows = await api(`${meta.list}${meta.list.includes("?") ? "&" : "?"}vault=${encodeURIComponent(VAULT)}`);
      const list = Array.isArray(rows) ? rows : [];
      box.classList.add("entity-list--graph");
      const data = await buildRelationFlowData(list);
      const paint = (q) => {
        box.innerHTML = renderRelationsFlowchart(data, focusId, q);
        bindGraphPan(box);
      };
      paint("");
      wireExploreSearch(meta, box, { onQuery: paint });
    } catch (err) {
      box.innerHTML = empty("Load failed", err.message);
    }
    return;
  }

  try {
    const rows = await api(`${meta.list}${meta.list.includes("?") ? "&" : "?"}vault=${encodeURIComponent(VAULT)}`);
    const list = Array.isArray(rows) ? rows : (rows.items || rows.stances || []);
    if (!list.length) {
      box.innerHTML = empty(`No ${meta.label.toLowerCase()} yet`);
      const input = $("#explore-search-q", app);
      input?.addEventListener("input", () => setExploreChrome(meta, input.value));
      return;
    }

    const renderArticle = (row) => {
      const rid = row.id;
      const status = row.epistemic_status || row.status || "";
      const statusLabel = pascalStatus(status);
      const open = focusId && rid === focusId;
      const kind = meta.id === "percept" ? perceptKindLabel(row) : "";
      const kindSlug = kind === "Derived" ? "derived" : (kind === "Observed" ? "observed" : "");
      const search = rowSearchText(row, meta.id);
      return `<article class="entity-item${open ? " is-open" : ""}${kindSlug ? ` entity-item--${kindSlug}` : ""}" data-id="${esc(rid)}" data-search="${esc(search)}"${kindSlug ? ` data-percept-kind="${kindSlug}"` : ""}>
        <button type="button" class="entity-row entity-row--toggle" aria-expanded="${open ? "true" : "false"}">
          ${statusLabel
            ? `<span class="entity-status ${reviewStatusClass(status)}">${esc(statusLabel)}</span>`
            : `<span class="entity-status entity-status--empty" aria-hidden="true"></span>`}
          <div class="entity-row-main">
            ${kind ? `<span class="percept-kind percept-kind--${kindSlug}">${esc(kind)}</span>` : ""}
            <strong class="entity-title">${titleHtml(row, meta.id)}</strong>
            <span class="muted">${esc(rid)}</span>
          </div>
          <span class="entity-chevron" aria-hidden="true"></span>
        </button>
        <div class="entity-expand" ${open ? "" : "hidden"}></div>
      </article>`;
    };

    if (meta.id === "percept") {
      const observed = list.filter((r) => !isDerivedPercept(r));
      const derived = list.filter((r) => isDerivedPercept(r));
      box.innerHTML = `
        <div class="percept-filters" role="tablist" aria-label="Percept kind">
          <button type="button" class="percept-filter is-active" data-filter="all" role="tab" aria-selected="true">All (${list.length})</button>
          <button type="button" class="percept-filter" data-filter="observed" role="tab" aria-selected="false">Observed (${observed.length})</button>
          <button type="button" class="percept-filter" data-filter="derived" role="tab" aria-selected="false">Derived (${derived.length})</button>
        </div>
        ${observed.length ? `<section class="percept-group" data-percept-group="observed">
          <h3 class="percept-group-title">Observed</h3>
          <p class="percept-group-sub muted">Sense input from connectors</p>
          ${observed.map(renderArticle).join("")}
        </section>` : ""}
        ${derived.length ? `<section class="percept-group" data-percept-group="derived">
          <h3 class="percept-group-title">Derived</h3>
          <p class="percept-group-sub muted">Cognize-synthesized percepts (episode &amp; pattern arcs)</p>
          ${derived.map(renderArticle).join("")}
        </section>` : ""}`;
      const filters = $(".percept-filters", box);
      filters?.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".percept-filter");
        if (!btn) return;
        const filter = btn.dataset.filter || "all";
        filters.querySelectorAll(".percept-filter").forEach((el) => {
          const on = el === btn;
          el.classList.toggle("is-active", on);
          el.setAttribute("aria-selected", on ? "true" : "false");
        });
        box.querySelectorAll(".percept-group").forEach((g) => {
          const show = filter === "all" || g.dataset.perceptGroup === filter;
          g.classList.toggle("is-filtered-out", !show);
        });
        ev.preventDefault();
        ev.stopPropagation();
      });
    } else {
      box.innerHTML = list.map(renderArticle).join("");
    }

    const expandItem = async (item, { pushHash = true } = {}) => {
      const rid = item.dataset.id;
      const btn = $(".entity-row--toggle", item);
      const panel = $(".entity-expand", item);
      const wasOpen = item.classList.contains("is-open");

      // Collapse others
      box.querySelectorAll(".entity-item.is-open").forEach((el) => {
        if (el === item) return;
        el.classList.remove("is-open");
        const b = $(".entity-row--toggle", el);
        const p = $(".entity-expand", el);
        if (b) b.setAttribute("aria-expanded", "false");
        if (p) {
          p.hidden = true;
          p.innerHTML = "";
        }
      });

      if (wasOpen && pushHash) {
        item.classList.remove("is-open");
        btn.setAttribute("aria-expanded", "false");
        panel.hidden = true;
        panel.innerHTML = "";
        if (location.hash !== `#explore/${meta.id}`) {
          history.replaceState(null, "", `#explore/${meta.id}`);
        }
        return;
      }

      item.classList.add("is-open");
      btn.setAttribute("aria-expanded", "true");
      panel.hidden = false;
      panel.innerHTML = `<div class="expand-loading muted">Loading…</div>`;
      if (pushHash) {
        const next = `#explore/${meta.id}/${encodeURIComponent(rid)}`;
        if (location.hash !== next) history.replaceState(null, "", next);
      }
      try {
        const { row, relations } = await fetchEntityBundle(meta, rid);
        panel.innerHTML = await renderExpandBody(meta, row, relations);
        bindGraphPan(panel);
      } catch (err) {
        panel.innerHTML = empty("Could not load", err.message);
      }
    };

    box.addEventListener("click", (ev) => {
      const nav = ev.target.closest("[data-explore-nav]");
      if (nav) {
        // allow default hash navigation → route() reloads list for that type
        return;
      }
      const btn = ev.target.closest(".entity-row--toggle");
      if (!btn) return;
      const item = btn.closest(".entity-item");
      if (!item) return;
      expandItem(item).catch((e) => toast(e.message, false));
    });

    if (focusId) {
      const safeId = (typeof CSS !== "undefined" && CSS.escape)
        ? CSS.escape(focusId)
        : focusId.replace(/["\\]/g, "\\$&");
      const target = box.querySelector(`.entity-item[data-id="${safeId}"]`);
      if (target) {
        await expandItem(target, { pushHash: false });
        target.scrollIntoView({ block: "nearest", behavior: "smooth" });
      } else {
        // ID not in list page — still try to show a floating expand at top
        const shell = document.createElement("article");
        shell.className = "entity-item is-open entity-item--orphan";
        shell.dataset.id = focusId;
        shell.innerHTML = `
          <div class="entity-row">
            <div class="entity-row-main">
              <strong>${esc(focusId)}</strong>
              <span class="muted">Not in current list page</span>
            </div>
          </div>
          <div class="entity-expand"></div>`;
        box.prepend(shell);
        const panel = $(".entity-expand", shell);
        try {
          const { row, relations } = await fetchEntityBundle(meta, focusId);
          const status = row.epistemic_status || row.status || "";
          const statusLabel = pascalStatus(status);
          $(".entity-row", shell).innerHTML = `
            ${statusLabel
              ? `<span class="entity-status ${reviewStatusClass(status)}">${esc(statusLabel)}</span>`
              : `<span class="entity-status entity-status--empty" aria-hidden="true"></span>`}
            <div class="entity-row-main">
              <strong class="entity-title">${titleHtml(row, meta.id)}</strong>
              <span class="muted">${esc(focusId)}</span>
            </div>`;
          panel.innerHTML = await renderExpandBody(meta, row, relations);
          bindGraphPan(panel);
        } catch (err) {
          panel.innerHTML = empty("Not found", err.message);
        }
      }
    }

    wireExploreSearch(meta, box);
  } catch (err) {
    box.innerHTML = empty("Load failed", err.message);
  }
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
          <strong>${esc(truncate(entityHeadline(p, "percept")))}</strong>
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
  setActiveNav(pane);
  _searchCache = null;
  const views = {
    home: () => paneHome(),
    sessions: () => paneSessions(),
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
