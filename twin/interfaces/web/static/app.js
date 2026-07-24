/** Twin serve UI — purple/white cognitive core */

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const toastEl = $("#toast");

const state = {
  view: "home",
  review: { queue: [], index: 0, loading: false },
};

function toast(msg, kind = "") {
  toastEl.hidden = false;
  toastEl.className = `toast ${kind}`.trim();
  toastEl.textContent = msg;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { toastEl.hidden = true; }, 2400);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { Accept: "application/json", ...(opts.body ? { "Content-Type": "application/json" } : {}) },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch (_) { /* ignore */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setNav(view) {
  document.querySelectorAll(".nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === view);
  });
}

function route() {
  const hash = (location.hash || "#home").slice(1).split("?")[0] || "home";
  state.view = hash;
  setNav(hash);
  const views = { home, review, search, pack, memories, status };
  (views[hash] || home)();
}

/* —— Home —— */

async function home() {
  app.innerHTML = `
    <section class="hero">
      <article class="core-card">
        <div class="core-head">
          <div class="mark" aria-hidden="true"></div>
          <h1>Twin</h1>
          <p>Persistent Cognitive Core</p>
        </div>
        ${pillar("mem", "◆", "Memory", "Persistent knowledge")}
        ${pillar("jud", "⚖", "Judgment", "Evaluate & decide")}
        ${pillar("pri", "🛡", "Privacy", "You control access")}
        ${pillar("ctx", "▣", "Context", "Right info, right time")}
        ${pillar("kg", "◈", "Knowledge Graph", "Entities & relationships")}
        ${pillar("ev", "▤", "Evidence", "Traceable & verifiable")}
      </article>
      <aside class="spoke-grid">
        <div class="spoke"><span class="dot"></span><div><strong>You</strong><p>The same mind across every tool</p></div></div>
        <div class="spoke"><span class="dot"></span><div><strong>Cursor / Codex</strong><p>Implementation, repos, automation</p></div></div>
        <div class="spoke"><span class="dot"></span><div><strong>Claude / ChatGPT</strong><p>Reasoning, analysis, ideation</p></div></div>
        <div class="spoke"><span class="dot"></span><div><strong>Local models</strong><p>Private reasoning via Ollama</p></div></div>
      </aside>
    </section>
    <div class="stats" id="home-stats">
      <div class="stat"><b>—</b><span>Review queue</span></div>
      <div class="stat"><b>—</b><span>Memories</span></div>
      <div class="stat"><b>—</b><span>Confirmed</span></div>
      <div class="stat"><b>—</b><span>Candidates</span></div>
    </div>
    <div class="panel">
      <h2>Cognitive continuity</h2>
      <p class="lede">Switch tools without losing context. Review candidates, search memory, and pack safe context for any LLM.</p>
      <div class="row">
        <a class="btn primary" href="#review">Open review</a>
        <a class="btn" href="#search">Search</a>
        <a class="btn" href="#pack">Build pack</a>
        <a class="btn ghost" href="#status">System status</a>
      </div>
    </div>
  `;
  try {
    const [queue, mems, metrics] = await Promise.all([
      api("/api/review/queue?limit=200"),
      api("/api/memories"),
      api("/api/metrics").catch(() => null),
    ]);
    const confirmed = mems.filter((m) => m.status === "confirmed").length;
    const candidates = mems.filter((m) => m.status === "candidate").length;
    const stats = $("#home-stats");
    const vals = [
      queue.length,
      metrics?.memories?.total ?? mems.length,
      confirmed,
      candidates,
    ];
    [...stats.children].forEach((el, i) => {
      el.querySelector("b").textContent = vals[i];
    });
  } catch (err) {
    toast(err.message, "err");
  }
}

function pillar(cls, glyph, title, desc) {
  return `<div class="pillar"><span class="ico ${cls}">${glyph}</span><strong>${title}</strong><span>${desc}</span></div>`;
}

/* —— Review —— */

async function review() {
  app.innerHTML = `
    <div class="panel">
      <h2>Review workbench</h2>
      <p class="lede">Priority queue — approve memories that should enter retrieval & packs.</p>
      <div class="legend" id="review-legend">
        <span><kbd>A</kbd> approve</span>
        <span><kbd>R</kbd> reject</span>
        <span><kbd>S</kbd> skip</span>
        <span><kbd>N</kbd> / <kbd>P</kbd> next / prev</span>
        <span><kbd>E</kbd> focus edit</span>
      </div>
      <div id="review-body" class="empty"><span class="spinner"></span> Loading queue…</div>
    </div>
  `;
  state.review.loading = true;
  try {
    const queue = await api("/api/review/queue?limit=200");
    state.review.queue = queue;
    if (state.review.index >= queue.length) state.review.index = Math.max(0, queue.length - 1);
    renderReviewItem();
  } catch (err) {
    $("#review-body").innerHTML = `<div class="empty"><strong>Could not load queue</strong>${esc(err.message)}</div>`;
  } finally {
    state.review.loading = false;
  }
}

async function renderReviewItem() {
  const box = $("#review-body");
  if (!box) return;
  const { queue, index } = state.review;
  if (!queue.length) {
    box.innerHTML = `<div class="empty"><strong>Queue empty</strong>Nothing awaiting review. Ingest + extract to fill it.</div>`;
    return;
  }
  const mem = queue[index];
  let evidence = [];
  let neighbor = null;
  let nEvidence = [];
  try {
    const full = await api(`/api/memories/${mem.id}`);
    evidence = full.evidence || [];
  } catch (_) { /* ignore */ }
  try {
    const neighbors = await api(`/api/memories/${mem.id}/neighbors`);
    if (neighbors?.length) {
      neighbor = neighbors[0];
      const nf = await api(`/api/memories/${neighbor.id}`);
      nEvidence = nf.evidence || [];
    }
  } catch (_) { /* ignore */ }

  const domains = ["work", "technical", "personal_preferences", "assistant_preferences",
    "personal", "relationship", "family", "health", "finance", "social", "legal", "emotional", "general"];
  const sens = ["public", "internal", "private", "restricted"];

  box.innerHTML = `
    <div class="meta">Item ${index + 1} / ${queue.length}
      · <button type="button" class="btn ghost" id="rev-prev">Prev</button>
      <button type="button" class="btn ghost" id="rev-next">Next</button>
    </div>
    ${mem.review_reason ? `<div class="reason">⚠ ${esc(mem.review_reason)}</div>` : ""}
    <div class="pair">
      ${memCard(mem, evidence, "Candidate")}
      ${neighbor ? memCard(neighbor, nEvidence, `Neighbor · sim ${(neighbor.similarity ?? 0).toFixed(2)}`)
        : `<div class="mem-card"><div class="meta">No close neighbor</div></div>`}
    </div>
    <form class="row" id="review-form">
      <div class="field"><label>Domain</label>
        <select name="domain">${domains.map((d) =>
          `<option value="${d}" ${d === mem.domain ? "selected" : ""}>${d}</option>`).join("")}</select>
      </div>
      <div class="field"><label>Sensitivity</label>
        <select name="sensitivity">${sens.map((s) =>
          `<option value="${s}" ${s === mem.sensitivity ? "selected" : ""}>${s}</option>`).join("")}</select>
      </div>
      <button type="button" class="btn ok" data-act="approve">A · Approve</button>
      <button type="button" class="btn err" data-act="reject">R · Reject</button>
      <button type="button" class="btn" data-act="update">E · Save meta</button>
      <button type="button" class="btn ghost" data-act="skip">S · Skip</button>
    </form>
  `;

  $("#rev-prev")?.addEventListener("click", () => {
    state.review.index = Math.max(0, index - 1);
    renderReviewItem();
  });
  $("#rev-next")?.addEventListener("click", () => {
    state.review.index = Math.min(queue.length - 1, index + 1);
    renderReviewItem();
  });
  $("#review-form")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "skip") {
      state.review.index = Math.min(queue.length - 1, index + 1);
      renderReviewItem();
      return;
    }
    const form = $("#review-form");
    const domain = form.domain.value;
    const sensitivity = form.sensitivity.value;
    btn.disabled = true;
    try {
      await api(`/api/memories/${mem.id}/review?action=${act}&domain=${encodeURIComponent(domain)}&sensitivity=${encodeURIComponent(sensitivity)}`, {
        method: "POST",
      });
      toast(act === "approve" ? "Approved" : act === "reject" ? "Rejected" : "Saved", "ok");
      if (act === "approve" || act === "reject") {
        state.review.queue.splice(index, 1);
        if (state.review.index >= state.review.queue.length) {
          state.review.index = Math.max(0, state.review.queue.length - 1);
        }
      }
      renderReviewItem();
    } catch (err) {
      toast(err.message, "err");
      btn.disabled = false;
    }
  });
}

function memCard(mem, evidence, label) {
  const flags = (mem.quality_flags || []).slice(0, 6)
    .map((f) => `<span class="chip">${esc(f)}</span>`).join("");
  const quotes = (evidence || []).slice(0, 2)
    .map((e) => `<blockquote>${esc((e.quote || "").slice(0, 240))}</blockquote>`).join("");
  return `
    <article class="mem-card">
      <div class="meta">${esc(label)}</div>
      <h3>${esc(mem.title)}</h3>
      <div class="meta">${esc(mem.type)} · ${esc(mem.domain)} · ${esc(mem.sensitivity)}
        · conf ${(mem.confidence ?? 0).toFixed(2)}
        · prio <strong style="color:var(--purple)">${(mem.review_priority ?? 0).toFixed(2)}</strong>
        · ${esc((mem.created_at || "").slice(0, 16))}
      </div>
      <div class="flags">${flags}</div>
      <p>${esc(mem.summary || "")}</p>
      ${quotes}
    </article>`;
}

function onReviewKey(e) {
  if (state.view !== "review") return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  const form = $("#review-form");
  if (!form) return;
  const key = e.key.toLowerCase();
  if (key === "a") { e.preventDefault(); form.querySelector('[data-act="approve"]')?.click(); }
  if (key === "r") { e.preventDefault(); form.querySelector('[data-act="reject"]')?.click(); }
  if (key === "s") { e.preventDefault(); form.querySelector('[data-act="skip"]')?.click(); }
  if (key === "e") { e.preventDefault(); form.querySelector('[data-act="update"]')?.click(); }
  if (key === "n") { e.preventDefault(); $("#rev-next")?.click(); }
  if (key === "p") { e.preventDefault(); $("#rev-prev")?.click(); }
}

/* —— Search —— */

function search() {
  app.innerHTML = `
    <div class="panel">
      <h2>Search</h2>
      <p class="lede">Hybrid retrieval — text + semantic + graph, filtered by the domain firewall.</p>
      <form class="row" id="search-form">
        <div class="field" style="flex:2"><label>Query</label>
          <input name="q" required placeholder="e.g. webhook architecture decisions" /></div>
        <div class="field"><label>Domain</label>
          <select name="domain">
            <option value="technical">technical</option>
            <option value="work">work</option>
            <option value="personal_preferences">personal_preferences</option>
            <option value="assistant_preferences">assistant_preferences</option>
          </select>
        </div>
        <div class="field"><label>Limit</label>
          <input name="limit" type="number" min="1" max="50" value="10" /></div>
        <button class="btn primary" type="submit">Search</button>
      </form>
      <div id="search-out" style="margin-top:1rem"></div>
    </div>
  `;
  $("#search-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const out = $("#search-out");
    out.innerHTML = `<span class="spinner"></span>`;
    try {
      const q = encodeURIComponent(fd.get("q"));
      const domain = encodeURIComponent(fd.get("domain"));
      const limit = encodeURIComponent(fd.get("limit") || "10");
      const data = await api(`/api/search?q=${q}&domain=${domain}&limit=${limit}`);
      if (!data.hits?.length) {
        out.innerHTML = `<div class="empty"><strong>No hits</strong>Try another query or domain.</div>`;
        return;
      }
      out.innerHTML = data.hits.map((h) => {
        const score = h.score ?? 0;
        return `<div class="hit">
          <div><div class="score">${score.toFixed(3)}</div>
            <div class="bar"><i style="width:${Math.round(Math.min(1, score) * 100)}%"></i></div>
            <div class="meta">${esc(h.why || "")}</div>
          </div>
          <div>
            <strong>${esc(h.title)}</strong>
            <div class="meta">[${esc(h.type)}] ${esc(h.domain)} · ${esc(h.status)}</div>
            <p>${esc((h.summary || "").slice(0, 220))}</p>
          </div>
        </div>`;
      }).join("") + (data.blocked?.length
        ? `<p class="meta" style="margin-top:1rem">${data.blocked.length} blocked by firewall</p>`
        : "");
    } catch (err) {
      out.innerHTML = `<div class="empty"><strong>Search failed</strong>${esc(err.message)}</div>`;
    }
  });
}

/* —— Pack —— */

function pack() {
  app.innerHTML = `
    <div class="panel">
      <h2>Context pack</h2>
      <p class="lede">Privacy-filtered pack for an LLM — confirmed memories only by default.</p>
      <form id="pack-form">
        <div class="field"><label>Task / query</label>
          <textarea name="query" required placeholder="What are you about to do?"></textarea></div>
        <div class="row" style="margin-top:.75rem">
          <div class="field"><label>Domain</label>
            <select name="target_domain">
              <option value="technical">technical</option>
              <option value="work">work</option>
              <option value="personal_preferences">personal_preferences</option>
              <option value="assistant_preferences">assistant_preferences</option>
            </select>
          </div>
          <div class="field"><label>Persona</label>
            <select name="persona">
              <option value="individual">individual</option>
              <option value="developer">developer</option>
              <option value="manager">manager</option>
            </select>
          </div>
          <div class="field"><label>Max tokens</label>
            <input name="max_tokens" type="number" value="1200" min="100" max="8000" /></div>
          <div class="field"><label>Candidates</label>
            <select name="include_candidates">
              <option value="false">confirmed only</option>
              <option value="true">include candidates</option>
            </select>
          </div>
        </div>
        <div class="row" style="margin-top:1rem">
          <button class="btn primary" type="submit">Build pack</button>
        </div>
      </form>
      <div id="pack-meta" style="margin-top:1rem"></div>
      <div id="pack-out"></div>
    </div>
  `;
  $("#pack-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const out = $("#pack-out");
    const meta = $("#pack-meta");
    out.innerHTML = `<span class="spinner"></span> Building…`;
    meta.innerHTML = "";
    try {
      const body = {
        query: fd.get("query"),
        target_domain: fd.get("target_domain"),
        persona: fd.get("persona"),
        max_tokens: Number(fd.get("max_tokens") || 1200),
        include_candidates: fd.get("include_candidates") === "true",
      };
      const data = await api("/api/context_pack", { method: "POST", body: JSON.stringify(body) });
      meta.innerHTML = `<div class="row">
        <span class="chip">confidence ${(data.confidence ?? 0).toFixed(2)}</span>
        <span class="chip">sources ${(data.sources || []).length}</span>
        <span class="chip">blocked ${data.blocked_count ?? (data.blocked || []).length}</span>
        <span class="chip">${esc(data.mode || "compact")}</span>
      </div>`;
      out.innerHTML = `<pre class="pack-out">${esc(data.context_pack || "(empty pack)")}</pre>`;
      toast("Pack ready", "ok");
    } catch (err) {
      out.innerHTML = `<div class="empty"><strong>Pack failed</strong>${esc(err.message)}</div>`;
      toast(err.message, "err");
    }
  });
}

/* —— Memories —— */

async function memories() {
  app.innerHTML = `
    <div class="panel">
      <h2>Memories</h2>
      <p class="lede">Browse stored memory items.</p>
      <div class="row" style="margin-bottom:1rem">
        <div class="field"><label>Status</label>
          <select id="mem-status">
            <option value="">all</option>
            <option value="candidate">candidate</option>
            <option value="confirmed">confirmed</option>
            <option value="rejected">rejected</option>
          </select>
        </div>
        <button class="btn" id="mem-reload">Refresh</button>
      </div>
      <div id="mem-list"><span class="spinner"></span></div>
    </div>
  `;
  const load = async () => {
    const status = $("#mem-status").value;
    const list = $("#mem-list");
    list.innerHTML = `<span class="spinner"></span>`;
    try {
      const q = status ? `?status=${encodeURIComponent(status)}` : "";
      const rows = await api(`/api/memories${q}`);
      if (!rows.length) {
        list.innerHTML = `<div class="empty"><strong>No memories</strong></div>`;
        return;
      }
      list.innerHTML = rows.slice(0, 200).map((m) => `
        <article class="mem-card">
          <h3>${esc(m.title)}</h3>
          <div class="meta">${esc(m.status)} · ${esc(m.type)} · ${esc(m.domain)}
            · prio ${(m.review_priority ?? 0).toFixed(2)} · ${esc(m.id)}</div>
          <p>${esc((m.summary || "").slice(0, 280))}</p>
        </article>`).join("");
    } catch (err) {
      list.innerHTML = `<div class="empty"><strong>Failed</strong>${esc(err.message)}</div>`;
    }
  };
  $("#mem-reload").addEventListener("click", load);
  $("#mem-status").addEventListener("change", load);
  load();
}

/* —— Status —— */

const HEALTH_LABELS = {
  ok: { title: "Overall health", good: "All checks passed", bad: "Issues detected" },
  problems: { title: "Issues found", empty: "None — store looks consistent" },
  problem_count: { title: "Issue count" },
  stats: { title: "Integrity snapshot" },
};

const STAT_LABELS = {
  memories: { title: "Memories scanned", hint: "Candidates + confirmed + rejected" },
  orphan_evidence: { title: "Orphan evidence", hint: "Evidence pointing at missing percepts" },
  confirmed_without_evidence: {
    title: "Confirmed without evidence",
    hint: "Approved memories lacking quotes",
  },
  dead_letters_open: { title: "Open dead letters", hint: "Failed runtime jobs awaiting retry" },
};

const METRIC_SECTION_LABELS = {
  percepts: "Perception",
  memories: "Memory store",
  quality: "Quality",
  firewall: "Privacy firewall",
  sessions: "Sessions",
  product: "Product signals",
};

const METRIC_FIELD_LABELS = {
  total: "Total",
  unprocessed: "Awaiting extract",
  by_sensor: "By sensor",
  by_status: "By status",
  by_type: "By type",
  by_domain: "By domain",
  needs_review: "Needs review",
  avg_confidence: "Avg confidence",
  approval_rate: "Approval rate",
  duplicate_evidence_ratio: "Duplicate evidence ratio",
  review_backlog_ratio: "Review backlog",
  duplicate_rate: "Duplicate rate",
  conflict_rate: "Conflict rate",
  unsupported_memory_rate: "Unsupported rate",
  stale_memory_rate: "Stale rate",
  merged_rate: "Merged rate",
  split_rate: "Split rate",
  avg_evidence_count: "Avg evidence / memory",
  evidence_coverage: "Evidence coverage",
  avg_review_priority: "Avg review priority",
  blocks_logged: "Blocks logged",
  by_consolidation: "By consolidation",
  by_task_profile: "By task profile",
  avg_pack_tokens: "Avg pack tokens",
  memories_created: "Memories created in sessions",
  feedback_by_verdict: "Feedback by verdict",
  context_relevance_rate: "Context relevance",
  re_explanation_rate: "Re-explanation rate",
  memory_usage_rate: "Memory usage rate",
};

function labelOf(map, key) {
  return map[key]?.title || map[key] || humanizeKey(key);
}

function humanizeKey(key) {
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(3);
  }
  if (Array.isArray(v)) return v.length ? v.map(String).join(", ") : "None";
  if (typeof v === "object") {
    return Object.entries(v)
      .map(([k, val]) => `${humanizeKey(k)}: ${formatValue(val)}`)
      .join(" · ") || "None";
  }
  return String(v);
}

function healthTone(ok, count) {
  if (ok === true || count === 0) return "ok";
  if (typeof count === "number" && count > 0) return "fail";
  if (ok === false) return "fail";
  return "warn";
}

function renderHealth(health) {
  if (health?.error) {
    return `<div class="empty"><strong>Health unavailable</strong>${esc(health.error)}</div>`;
  }
  const ok = Boolean(health.ok);
  const problems = Array.isArray(health.problems) ? health.problems : [];
  const count = health.problem_count ?? problems.length;
  const stats = health.stats || {};
  const tone = healthTone(ok, count);
  const mark = tone === "ok" ? "✓" : tone === "fail" ? "✗" : "!";
  const summary = ok
    ? HEALTH_LABELS.ok.good
    : `${HEALTH_LABELS.ok.bad} (${count})`;

  const statCards = Object.entries(stats).map(([key, val]) => {
    const meta = STAT_LABELS[key] || { title: humanizeKey(key), hint: "" };
    const bad = typeof val === "number" && val > 0
      && (key === "orphan_evidence" || key === "confirmed_without_evidence" || key === "dead_letters_open");
    return `<div class="stat ${bad ? "stat-warn" : ""}">
      <b>${esc(formatValue(val))}</b>
      <span>${esc(meta.title)}</span>
      ${meta.hint ? `<em class="stat-hint">${esc(meta.hint)}</em>` : ""}
    </div>`;
  }).join("");

  const problemList = problems.length
    ? `<ul class="check-list problem-list">${problems.map((p) =>
      `<li><span class="mark-status fail">!</span><div>${esc(p)}</div></li>`).join("")}</ul>`
    : `<p class="meta">${esc(HEALTH_LABELS.problems.empty)}</p>`;

  return `
    <div class="health-banner ${tone}">
      <span class="mark-status ${tone}">${mark}</span>
      <div>
        <strong>${esc(HEALTH_LABELS.ok.title)}</strong>
        <div class="meta">${esc(summary)}</div>
      </div>
    </div>
    <div class="stats" style="margin:1rem 0">${statCards || `<div class="stat"><b>0</b><span>No stats</span></div>`}</div>
    <h3 class="section-title">${esc(HEALTH_LABELS.problems.title)}
      <span class="chip ${count ? "err" : ""}">${count}</span>
    </h3>
    ${problemList}
  `;
}

function renderMetrics(metrics) {
  if (metrics?.error) {
    return `<div class="empty"><strong>Metrics unavailable</strong>${esc(metrics.error)}</div>`;
  }
  const sections = Object.entries(metrics || {}).map(([section, data]) => {
    const title = METRIC_SECTION_LABELS[section] || humanizeKey(section);
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      return `<div class="metric-block"><h4>${esc(title)}</h4>
        <div class="meta">${esc(formatValue(data))}</div></div>`;
    }
    const rows = Object.entries(data).map(([k, v]) => {
      const label = METRIC_FIELD_LABELS[k] || humanizeKey(k);
      if (v && typeof v === "object" && !Array.isArray(v)) {
        const chips = Object.entries(v).map(([kk, vv]) =>
          `<span class="chip">${esc(humanizeKey(kk))}: ${esc(formatValue(vv))}</span>`).join(" ");
        return `<div class="metric-row"><span class="metric-key">${esc(label)}</span>
          <div class="flags">${chips || '<span class="meta">None</span>'}</div></div>`;
      }
      return `<div class="metric-row"><span class="metric-key">${esc(label)}</span>
        <span class="metric-val">${esc(formatValue(v))}</span></div>`;
    }).join("");
    return `<div class="metric-block"><h4>${esc(title)}</h4>${rows}</div>`;
  }).join("");
  return sections || `<div class="empty"><strong>No metrics</strong></div>`;
}

async function status() {
  app.innerHTML = `
    <div class="panel">
      <h2>System status</h2>
      <p class="lede">Integrity of the cognitive store plus product quality signals.</p>
      <div id="status-body"><span class="spinner"></span></div>
    </div>
  `;
  const body = $("#status-body");
  try {
    const [health, metrics] = await Promise.all([
      api("/api/health/cognition").catch((e) => ({ error: e.message })),
      api("/api/metrics").catch((e) => ({ error: e.message })),
    ]);
    body.innerHTML = `
      <h3 class="section-title">Integrity</h3>
      ${renderHealth(health)}
      <h3 class="section-title" style="margin-top:1.5rem">Product metrics</h3>
      ${renderMetrics(metrics)}
    `;
  } catch (err) {
    body.innerHTML = `<div class="empty"><strong>Status unavailable</strong>${esc(err.message)}</div>`;
  }
}

/* —— boot —— */

window.addEventListener("hashchange", route);
document.addEventListener("keydown", onReviewKey);
route();
