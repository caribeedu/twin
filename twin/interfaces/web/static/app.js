/** Twin serve UI — purple/white cognitive core */

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const toastEl = $("#toast");

const state = {
  view: "home",
  review: {
    queue: [],
    index: 0,
    loading: false,
    selectedRelatedId: null,
    findings: [],
    neighbors: [],
    quality: null,
    splitOpen: false,
  },
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

function humanizeKey(key) {
  return String(key ?? "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Friendly UI labels — option values stay as implementation ids. */
const LABELS = {
  domain: {
    work: "Work",
    technical: "Technical",
    personal_preferences: "Personal preferences",
    assistant_preferences: "Assistant preferences",
    personal: "Personal",
    relationship: "Relationships",
    family: "Family",
    health: "Health",
    finance: "Finance",
    social: "Social",
    legal: "Legal",
    emotional: "Emotional",
    general: "General",
  },
  type: {
    event: "Event",
    fact: "Fact",
    decision: "Decision",
    preference: "Preference",
    belief: "Belief",
    task: "Task",
    procedure: "Procedure",
    relationship: "Relationship",
    communication_act: "Communication",
    constraint: "Constraint",
  },
  status: {
    candidate: "Needs review",
    confirmed: "Confirmed",
    rejected: "Rejected",
    deprecated: "Deprecated",
    contradicted: "Contradicted",
    merged: "Merged",
    split: "Split",
    archived: "Archived",
    unsupported: "Unsupported",
    stale: "Stale",
    deleted: "Deleted",
  },
  sensitivity: {
    public: "Public",
    internal: "Internal",
    private: "Private",
    restricted: "Restricted",
  },
  persona: {
    individual: "Individual",
    developer: "Developer",
    manager: "Manager",
    partner: "Partner",
    son: "Family",
    friend: "Friend",
    "assistant-user": "Assistant user",
  },
  flag: {
    exact_duplicate: "Exact duplicate",
    near_duplicate: "Near duplicate",
    possible_duplicate: "Possible duplicate",
    possible_conflict: "Possible conflict",
    conflict: "Conflict",
    contradiction: "Contradiction",
    possible_supersedence: "May supersede another",
    possible_merge: "Possible merge",
    possible_split: "Possible split",
    possibly_related: "Possibly related",
    related: "Related",
    scope_difference: "Different scope",
    weak_evidence: "Weak evidence",
    low_specificity: "Low specificity",
    high_future_reuse: "High reuse value",
    evidence_mapping_required: "Needs evidence mapping",
    cross_source_temporal_conflict: "Cross-source temporal conflict",
    claim_match: "Same claim",
    stale: "Stale",
    unsupported: "Unsupported",
  },
  action: {
    confirm: "Approve",
    reject: "Reject",
    edit: "Edit",
    merge: "Merge",
    split: "Split",
    supersede: "Supersede",
    contradict: "Mark conflict",
    defer: "Defer",
    archive: "Archive",
    request_more_evidence: "Request evidence",
    attach_evidence: "Attach evidence",
    none: "Review",
  },
  altitude: {
    ground: "Ground",
    linked: "Linked",
    distilled: "Distilled",
    stance: "Stance",
  },
  sensor: {
    github: "GitHub",
    slack: "Slack",
    git: "Git",
    document: "Document",
    meeting: "Meeting",
    mail: "Mail",
    email: "Email",
    episode: "Episode",
    episode_reflect: "Episode reflection",
    pattern: "Pattern",
    workspace: "Workspace",
    unknown: "Unknown",
  },
  kind: {
    pull_request: "pull request",
    commit: "commit",
    message: "message",
    thread_reply: "reply",
    issue: "issue",
    channel: "channel",
    episode: "episode",
    episode_reflection: "reflection",
  },
  why: {
    "text match": "Text match",
    "semantic similarity": "Semantic match",
    "entity match": "Entity match",
    "weak match": "Weak match",
    "project match": "Project match",
  },
  reason: {
    deferred: "Deferred for later",
    formation_conflict: "Formation conflict",
    "formation conflict": "Formation conflict",
    temporal_belief_refresh: "Belief may be outdated",
    "all supporting evidence removed": "Evidence removed",
    "more evidence requested": "More evidence requested",
    "restored from reject — re-review required": "Restored — needs re-review",
    "merged synthesis — confirm": "Merged — confirm synthesis",
    "condensed near-duplicates — confirm": "Condensed near-duplicates — confirm synthesis",
    episode_reflect: "Episode reflection",
    semantic: "Semantic similarity",
    entity: "Shared entity",
    project: "Same project",
    contradicts: "Contradicts",
    supersedes: "Supersedes",
    related_to: "Related",
    merged_into: "Merged into",
    split_into: "Split into",
  },
  mode: {
    compact: "Compact",
    detailed: "Detailed",
    full: "Full",
  },
};

function reasonLabel(raw) {
  if (!raw) return "";
  const key = String(raw);
  if (LABELS.reason[key]) return LABELS.reason[key];
  if (key.startsWith("contradicted by ")) return "Contradicted by another memory";
  if (key.startsWith("contradicts ")) return "Contradicts another memory";
  if (key.startsWith("graph expansion")) return "Related via graph";
  return humanizeKey(key);
}

const DOMAIN_OPTIONS = [
  "technical", "work", "personal_preferences", "assistant_preferences",
  "personal", "relationship", "family", "health", "finance", "social",
  "legal", "emotional", "general",
];
const SENSITIVITY_OPTIONS = ["public", "internal", "private", "restricted"];
const STATUS_FILTER_OPTIONS = ["", "candidate", "confirmed", "rejected"];
const PERSONA_OPTIONS = ["individual", "developer", "manager"];
const PACK_DOMAIN_OPTIONS = [
  "technical", "work", "personal_preferences", "assistant_preferences",
];

function label(kind, value) {
  if (value == null || value === "") return kind === "status" ? "All" : "—";
  const map = LABELS[kind] || {};
  const key = String(value);
  return map[key] || humanizeKey(key);
}

function selectOptions(kind, values, selected) {
  return values.map((v) => {
    const sel = v === selected || (v === "" && !selected) ? " selected" : "";
    const text = v === "" ? "All" : label(kind, v);
    return `<option value="${esc(v)}"${sel}>${esc(text)}</option>`;
  }).join("");
}

function pct01(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return 0;
  return Math.round(Math.max(0, Math.min(1, x)) * 100);
}

function tag(text, cls = "") {
  return `<span class="tag ${cls}">${esc(text)}</span>`;
}

function friendlySourceText(raw) {
  const text = String(raw || "").trim();
  if (!text) return "Source";
  // Already-friendly labels from the API (e.g. "GitHub · pull request · #3").
  if (LABELS.sensor[text]) return LABELS.sensor[text];
  if (LABELS.reason[text]) return LABELS.reason[text];
  // Rewrite bare snake_case tokens inside compound labels.
  return text
    .split(" · ")
    .map((part) => {
      const p = part.trim();
      if (LABELS.sensor[p]) return LABELS.sensor[p];
      if (LABELS.kind[p]) return LABELS.kind[p];
      if (p.includes(" ") || /[#/]/.test(p)) return p;
      return humanizeKey(p);
    })
    .join(" · ");
}

function sourceTags(mem) {
  const refs = mem.source_refs || [];
  const seen = new Set();
  const chips = [];
  const push = (text, url) => {
    const friendly = friendlySourceText(text);
    const key = friendly.toLowerCase();
    if (!friendly || seen.has(key)) return;
    // Drop synthetic "Episode reflection" when a concrete source chip exists.
    if (key === "episode reflection" && [...seen].some((k) => k !== "episode reflection")) {
      return;
    }
    seen.add(key);
    if (url) {
      chips.push(
        `<span class="tag source"><a href="${esc(url)}" target="_blank" rel="noopener">${esc(friendly)}</a></span>`,
      );
    } else {
      chips.push(tag(friendly, "source"));
    }
  };
  if (refs.length) {
    for (const r of refs.slice(0, 4)) {
      push(r.label || r.sensor || "source", r.url);
    }
  } else {
    const sensors = mem.sources || [];
    if (!sensors.length && mem.source_label) {
      push(mem.source_label);
    } else {
      for (const s of sensors) push(s);
    }
  }
  // If we added concrete chips first, strip any leftover reflection chip.
  const concrete = chips.filter((c) => !/Episode reflection/i.test(c));
  return (concrete.length ? concrete : chips).join("");
}

function memTags(mem, {
  showStatus = true,
  showAltitude = false,
  showSources = false,
  showFlags = true,
} = {}) {
  const parts = [];
  if (showStatus && mem.status) {
    const st = String(mem.status);
    const tone = st === "confirmed" ? "ok"
      : st === "candidate" ? "warn"
        : st === "rejected" || st === "contradicted" ? "err" : "";
    parts.push(tag(label("status", st), tone));
  }
  if (mem.type) parts.push(tag(label("type", mem.type), "type"));
  if (mem.domain) parts.push(tag(label("domain", mem.domain), "domain"));
  if (mem.sensitivity) parts.push(tag(label("sensitivity", mem.sensitivity), "sens"));
  if (showAltitude) {
    const altitude = mem.altitude || (mem.payload && mem.payload.altitude);
    if (altitude) {
      parts.push(tag(label("altitude", altitude), `altitude altitude-${altitude}`));
    }
  }
  const payload = mem.payload || {};
  if (mem.condensed || payload.condensed || (payload.merged_from && payload.merged_from.length)) {
    parts.push(tag("Condensed", "ok"));
  }
  if (showFlags) {
    for (const f of (mem.quality_flags || []).slice(0, 8)) {
      const key = String(f);
      parts.push(tag(label("flag", key), "flag"));
    }
  }
  if (showSources) {
    const src = sourceTags(mem);
    if (src) parts.push(src);
  }
  return `<div class="tags">${parts.join("")}</div>`;
}

function flagTags(flags) {
  const list = (flags || []).slice(0, 8);
  if (!list.length) return "";
  return `<div class="tags flags">${list.map((f) => {
    const key = String(f);
    return tag(label("flag", key), "flag");
  }).join("")}</div>`;
}

function memAccordion(title, itemsHtml) {
  if (!itemsHtml) return "";
  return `
    <details class="mem-accordion">
      <summary>${esc(title)}</summary>
      <ul class="mem-accordion-list">${itemsHtml}</ul>
    </details>`;
}

function evidenceAccordion(evidence) {
  const rows = (evidence || []).filter((e) => (e.quote || "").trim());
  if (!rows.length) return "";
  const items = rows.slice(0, 8).map((e) => {
    const q = String(e.quote || "").trim();
    const shown = q.length > 320 ? `${q.slice(0, 320)}…` : q;
    return `<li class="evidence-item">“${esc(shown)}”</li>`;
  }).join("");
  const title = rows.length === 1 ? "Evidence" : `Evidence (${rows.length})`;
  return memAccordion(title, items);
}

function sourcesAccordion(mem) {
  const refs = mem.source_refs || [];
  if (!refs.length) return "";
  const items = refs.map((r) => {
    const text = friendlySourceText(r.label || r.sensor || "source");
    if (r.url) {
      return `<li><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(text)}</a></li>`;
    }
    return `<li>${esc(text)}</li>`;
  }).join("");
  return memAccordion("Sources", items);
}

function basedInAccordion(mem) {
  const rows = mem.based_in || [];
  if (!rows.length) return "";
  const items = rows.map((r) => {
    const st = r.status && r.status !== "unknown"
      ? ` <span class="meta">(${esc(label("status", r.status))})</span>`
      : "";
    return `<li><span class="based-in-title">${esc(r.title || r.id || "Memory")}</span>${st}</li>`;
  }).join("");
  return memAccordion("Based in", items);
}

function altitudeLabel(mem) {
  const k = mem.altitude || (mem.payload && mem.payload.altitude) || "ground";
  return LABELS.altitude[k] || k;
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
  const views = { home, review, narratives, search, pack, memories, status };
  (views[hash] || home)();
}

/* —— Home —— */

async function home() {
  app.innerHTML = `
    <section class="hero">
      <article class="core-card">
        <div class="core-head">
          <img class="mark" src="/static/logo.svg" width="48" height="48" alt="" />
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
      <p class="lede">Resolve duplicates, conflicts and weak claims — then approve what should enter retrieval.</p>
      <div class="legend" id="review-legend">
        <span><kbd>A</kbd> approve</span>
        <span><kbd>R</kbd> reject</span>
        <span><kbd>S</kbd> skip</span>
        <span><kbd>M</kbd> merge</span>
        <span><kbd>N</kbd> / <kbd>P</kbd> next / prev</span>
        <span><kbd>E</kbd> save details</span>
      </div>
      <div id="review-body" class="empty"><span class="spinner"></span> Loading queue…</div>
    </div>
  `;
  state.review.loading = true;
  state.review.selectedRelatedId = null;
  state.review.findings = [];
  state.review.neighbors = [];
  state.review.quality = null;
  state.review.splitOpen = false;
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

function findingLabel(type) {
  return LABELS.flag[type] || humanizeKey(type);
}

function actionLabel(action) {
  return LABELS.action[action] || humanizeKey(action);
}

function reviewFormMeta() {
  const form = $("#review-form");
  return {
    domain: form?.domain?.value || undefined,
    sensitivity: form?.sensitivity?.value || undefined,
  };
}

function removeFromReviewQueue(ids) {
  const drop = new Set((ids || []).filter(Boolean));
  if (!drop.size) return;
  const { queue, index } = state.review;
  const currentId = queue[index]?.id;
  state.review.queue = queue.filter((m) => !drop.has(m.id));
  if (currentId && drop.has(currentId)) {
    state.review.index = Math.min(
      state.review.index,
      Math.max(0, state.review.queue.length - 1),
    );
  } else {
    const next = state.review.queue.findIndex((m) => m.id === currentId);
    state.review.index = next >= 0 ? next : Math.max(0, state.review.queue.length - 1);
  }
  state.review.selectedRelatedId = null;
  state.review.splitOpen = false;
}

async function resolveMemory(memoryId, payload) {
  const meta = reviewFormMeta();
  return api(`/api/memories/${memoryId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ ...meta, ...payload }),
  });
}

function defaultSplitParts(mem) {
  const summary = String(mem.summary || mem.title || "").trim();
  const bits = summary.split(/\s+(?:and|,)\s+/i).filter((s) => s.trim().length > 12);
  if (bits.length >= 2) {
    return bits.slice(0, 2).map((s, i) => ({
      title: s.slice(0, 80),
      summary: s,
    }));
  }
  const mid = Math.max(40, Math.floor(summary.length / 2));
  const cut = summary.lastIndexOf(" ", mid);
  const a = summary.slice(0, cut > 20 ? cut : mid).trim() || `${mem.title} (part 1)`;
  const b = summary.slice(cut > 20 ? cut : mid).trim() || `${mem.title} (part 2)`;
  return [
    { title: a.slice(0, 80), summary: a },
    { title: b.slice(0, 80), summary: b },
  ];
}

/** Plain-language framing for each finding type. */
function issueGuide(finding) {
  const type = finding.type || "";
  const guides = {
    possible_conflict: {
      title: "Possible conflict",
      ask: "Do these two memories disagree about the same thing?",
    },
    possible_supersedence: {
      title: "Newer version?",
      ask: "Did this memory replace the related one?",
    },
    near_duplicate: {
      title: "Near duplicate",
      ask: "Are these basically the same memory?",
    },
    exact_duplicate: {
      title: "Exact duplicate",
      ask: "Reject this copy, or merge them into one?",
    },
    possible_merge: {
      title: "Possible merge",
      ask: "Should these be combined into one memory?",
    },
    possible_split: {
      title: "Compound memory",
      ask: "Does this mix two claims that should be separate?",
    },
    weak_evidence: {
      title: "Weak evidence",
      ask: "Keep asking for sources, or approve anyway later?",
    },
    low_specificity: {
      title: "Too vague",
      ask: "Edit domain/sensitivity below, or split if it mixes topics.",
    },
    possibly_related: {
      title: "Related, not conflicting",
      ask: "Usually safe to ignore — only act if they truly collide.",
    },
    scope_difference: {
      title: "Different scope",
      ask: "They can coexist (e.g. prod vs dev). Ignore unless wrong.",
    },
  };
  return guides[type] || {
    title: findingLabel(type),
    ask: finding.reason || "Choose what should happen to this memory.",
  };
}

/**
 * Decision buttons: primary (suggested) + secondary in a disclosure.
 * Labels describe the *outcome*, not the internal verb.
 */
function findingActionsHtml(finding, relatedId) {
  const act = finding.suggested_action || "none";
  const hasRel = Boolean(relatedId);
  const type = finding.type || "";
  const primary = [];
  const secondary = [];
  const push = (bucket, action, label, hint, cls = "") => {
    bucket.push({ action, label, hint, cls });
  };

  if (type === "possible_conflict" || act === "contradict") {
    push(primary, "contradict", "They disagree", "Keep both; mark as conflicting", "warn");
    if (hasRel) {
      push(secondary, "supersede", "This replaces the other", "Deprecate related; approve this");
      push(secondary, "supersede_by", "The other already won", "Deprecate this; keep related");
      push(secondary, "merge", "Same claim — merge", "Combine into one memory");
    }
    push(secondary, "dismiss", "False alarm", "Not a real conflict");
  } else if (type === "possible_supersedence" || act === "supersede") {
    push(primary, "supersede", "This replaces the other", "Deprecate related; approve this", "ok");
    if (hasRel) {
      push(secondary, "supersede_by", "The other already won", "Deprecate this instead");
      push(secondary, "contradict", "They still disagree", "Mark as conflict, keep both");
      push(secondary, "merge", "Same claim — merge", "Combine into one");
    }
    push(secondary, "dismiss", "Both can stay", "Not a replacement");
  } else if (type === "near_duplicate" || type === "possible_merge" || act === "merge") {
    push(primary, "merge", "Merge into one", "Combine this with the related memory", "ok");
    if (hasRel) {
      push(secondary, "supersede", "Keep this, drop related", "Deprecate the other copy");
      push(secondary, "reject", "Reject this copy", "Related is enough");
    }
    push(secondary, "dismiss", "Keep both", "Not duplicates");
  } else if (type === "exact_duplicate" || act === "reject") {
    push(primary, "reject", "Reject this copy", "Related already covers it", "err");
    if (hasRel) push(secondary, "merge", "Merge instead", "Combine into one");
    push(secondary, "dismiss", "Keep both", "Not a duplicate");
  } else if (type === "possible_split" || act === "split") {
    push(primary, "split", "Split into parts…", "Break into two clearer memories");
    push(secondary, "dismiss", "Fine as one", "Leave compound");
  } else if (type === "weak_evidence" || act === "request_more_evidence") {
    push(primary, "request_evidence", "Ask for more evidence", "Stay in review until sources land", "warn");
    push(secondary, "dismiss", "Evidence is enough", "Clear this warning");
  } else if (act === "archive") {
    push(primary, "archive", "Archive", "Remove from active memory", "err");
    push(secondary, "dismiss", "Keep active", "Ignore archive hint");
  } else if (act === "confirm" || type === "scope_difference") {
    push(primary, "dismiss", "Looks fine — clear issue", "They can coexist", "ok");
    push(secondary, "confirm", "Approve memory now", "Confirm this candidate");
  } else if (act === "defer" || type === "possibly_related") {
    push(primary, "dismiss", "Ignore for now", "Not actionable", "ok");
    push(secondary, "defer", "Defer memory", "Stay in queue, lower urgency");
    if (hasRel) {
      push(secondary, "merge", "Merge with related", "Combine into one");
      push(secondary, "contradict", "Mark as conflict", "They disagree");
    }
  } else {
    if (hasRel) {
      push(primary, "merge", "Merge with related", "Combine into one");
      push(secondary, "contradict", "Mark as conflict", "They disagree");
      push(secondary, "supersede", "This replaces the other", "Deprecate related");
    }
    push(secondary, "dismiss", "Clear issue", "Nothing to do");
  }

  // Ensure dismiss always available once.
  if (![...primary, ...secondary].some((b) => b.action === "dismiss")) {
    push(secondary, "dismiss", "Clear issue", "Nothing to do");
  }

  const btnHtml = (b) => `
    <button type="button" class="btn issue-btn ${b.cls}" data-resolve="${esc(b.action)}"
      data-finding="${esc(finding.id)}" data-related="${esc(relatedId || "")}"
      title="${esc(b.hint || "")}">
      <span class="issue-btn-label">${esc(b.label)}</span>
      ${b.hint ? `<span class="issue-btn-hint">${esc(b.hint)}</span>` : ""}
    </button>`;

  const primaryHtml = primary.map(btnHtml).join("");
  const secondaryHtml = secondary.length
    ? `<details class="issue-more">
        <summary>Other options</summary>
        <div class="issue-actions secondary">${secondary.map(btnHtml).join("")}</div>
      </details>`
    : "";

  return `<div class="issue-actions primary">${primaryHtml}</div>${secondaryHtml}`;
}

function issuesPanelHtml(findings, neighbors) {
  if (!findings?.length) {
    return `
      <div class="issues-panel empty-issues">
        <div class="issues-head">
          <strong>No open issues</strong>
          <button type="button" class="btn ghost" id="rev-reanalyze">Re-analyze</button>
        </div>
        <p class="meta">Approve if this memory should enter retrieval, or pick a related memory below.</p>
      </div>`;
  }
  const cards = findings.map((f, i) => {
    const relatedId = f.related_memory_id
      || state.review.selectedRelatedId
      || neighbors[0]?.id
      || "";
    const relatedTitle = f.related?.title
      || neighbors.find((n) => n.id === f.related_memory_id)?.title
      || "";
    const guide = issueGuide(f);
    const conf = pct01(f.confidence);
    const weak = conf !== "" && Number(conf) < 55;
    return `
      <article class="issue-card" data-finding-id="${esc(f.id)}" data-related="${esc(f.related_memory_id || "")}">
        <div class="issue-top">
          <span class="issue-step">Issue ${i + 1}</span>
          <span class="tag warn">${esc(guide.title)}</span>
          ${weak ? `<span class="meta">Low confidence (${conf}%) — double-check</span>`
            : conf ? `<span class="meta">${conf}% sure</span>` : ""}
        </div>
        <p class="issue-ask">${esc(guide.ask)}</p>
        ${relatedTitle
          ? `<p class="issue-related">Compared with:
              <button type="button" class="linkish" data-select-related="${esc(f.related_memory_id || relatedId)}">${esc(relatedTitle)}</button>
              <span class="meta">(click to show on the right)</span>
            </p>`
          : ""}
        ${f.reason && f.reason !== guide.ask
          ? `<p class="issue-reason meta">${esc(f.reason)}</p>` : ""}
        ${findingActionsHtml(f, f.related_memory_id || relatedId)}
      </article>`;
  }).join("");
  return `
    <div class="issues-panel">
      <div class="issues-head">
        <div>
          <strong>${findings.length} thing${findings.length === 1 ? "" : "s"} to decide</strong>
          <p class="meta" style="margin:0.2rem 0 0">Pick what should happen. Primary button is the usual answer; open Other options if not.</p>
        </div>
        <button type="button" class="btn ghost" id="rev-reanalyze">Re-analyze</button>
      </div>
      <div class="issue-list">${cards}</div>
    </div>`;
}

function neighborRailHtml(neighbors, selectedId) {
  if (!neighbors?.length) {
    return `
      <aside class="neighbor-rail empty-rail">
        <div class="card-kicker">Related memories</div>
        <p class="meta">No similar memories nearby.</p>
      </aside>`;
  }
  const items = neighbors.slice(0, 10).map((n) => {
    const pct = pct01(n.similarity);
    const active = n.id === selectedId ? "active" : "";
    return `
      <button type="button" class="neighbor-chip ${active}" data-select-related="${esc(n.id)}">
        <span class="neighbor-score">${pct}%</span>
        <span class="neighbor-title">${esc(n.title || n.id)}</span>
        <span class="neighbor-why">${esc(reasonLabel(n.reason) || "")}</span>
      </button>`;
  }).join("");
  return `
    <aside class="neighbor-rail">
      <div class="card-kicker">Related memories</div>
      <p class="meta">Click one to compare.</p>
      <div class="neighbor-list">${items}</div>
      <details class="issue-more neighbor-more">
        <summary>Tools for selected</summary>
        <div class="neighbor-tools" id="neighbor-tools">
          <button type="button" class="btn ok issue-btn" data-resolve="merge" data-related="${esc(selectedId || "")}">
            <span class="issue-btn-label">M · Merge</span>
            <span class="issue-btn-hint">Same claim — combine</span>
          </button>
          <button type="button" class="btn warn issue-btn" data-resolve="contradict" data-related="${esc(selectedId || "")}">
            <span class="issue-btn-label">They disagree</span>
            <span class="issue-btn-hint">Keep both as conflict</span>
          </button>
          <button type="button" class="btn issue-btn" data-resolve="supersede" data-related="${esc(selectedId || "")}">
            <span class="issue-btn-label">This replaces the other</span>
            <span class="issue-btn-hint">Deprecate related</span>
          </button>
          <button type="button" class="btn issue-btn" data-resolve="supersede_by" data-related="${esc(selectedId || "")}">
            <span class="issue-btn-label">The other already won</span>
            <span class="issue-btn-hint">Deprecate this candidate</span>
          </button>
        </div>
      </details>
    </aside>`;
}

function splitPanelHtml(mem) {
  if (!state.review.splitOpen) return "";
  const parts = defaultSplitParts(mem);
  return `
    <div class="split-panel" id="split-panel">
      <div class="issues-head"><strong>Split into parts</strong></div>
      <div class="pair">
        <div class="field"><label>Part 1 title</label>
          <input name="p1_title" value="${esc(parts[0].title)}" /></div>
        <div class="field"><label>Part 2 title</label>
          <input name="p2_title" value="${esc(parts[1].title)}" /></div>
      </div>
      <div class="pair">
        <div class="field"><label>Part 1 summary</label>
          <textarea name="p1_summary" rows="3">${esc(parts[0].summary)}</textarea></div>
        <div class="field"><label>Part 2 summary</label>
          <textarea name="p2_summary" rows="3">${esc(parts[1].summary)}</textarea></div>
      </div>
      <div class="row tight">
        <button type="button" class="btn ok" id="split-confirm">Confirm split</button>
        <button type="button" class="btn ghost" id="split-cancel">Cancel</button>
      </div>
    </div>`;
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
  box.innerHTML = `<div class="empty"><span class="spinner"></span> Loading item…</div>`;

  let evidence = [];
  let neighbors = [];
  let findings = [];
  let quality = null;
  try {
    const full = await api(`/api/memories/${mem.id}`);
    evidence = full.evidence || [];
    Object.assign(mem, full);
  } catch (_) { /* ignore */ }
  try {
    neighbors = await api(`/api/memories/${mem.id}/neighbors`) || [];
  } catch (_) { neighbors = []; }
  try {
    quality = await api(`/api/memories/${mem.id}/quality`);
    findings = quality?.issues || [];
  } catch (_) {
    try {
      findings = await api(`/api/memories/${mem.id}/findings`) || [];
    } catch (_) { findings = []; }
  }

  state.review.neighbors = neighbors;
  state.review.findings = findings;
  state.review.quality = quality;
  if (!state.review.selectedRelatedId) {
    const fromFinding = findings.find((f) => f.related_memory_id)?.related_memory_id;
    state.review.selectedRelatedId = fromFinding || neighbors[0]?.id || null;
  }
  const selectedId = state.review.selectedRelatedId;
  let related = neighbors.find((n) => n.id === selectedId) || null;
  let relatedEvidence = [];
  if (selectedId && !related) {
    try {
      related = await api(`/api/memories/${selectedId}`);
    } catch (_) { related = null; }
  }
  if (related) {
    try {
      const nf = await api(`/api/memories/${related.id}`);
      relatedEvidence = nf.evidence || [];
      related = { ...related, ...nf };
    } catch (_) { /* ignore */ }
  }

  const neighPct = related?.similarity != null ? pct01(related.similarity) : null;
  const neighWhy = related?.reason ? reasonLabel(related.reason) : "";
  const neighHeading = related
    ? `Related · ${neighPct != null ? `${neighPct}% match` : "selected"}${neighWhy ? ` · ${neighWhy}` : ""}`
    : "";

  box.innerHTML = `
    <div class="toolbar">
      <span class="meta">Item ${index + 1} of ${queue.length}</span>
      <div class="row tight">
        <button type="button" class="btn ghost" id="rev-prev">Prev</button>
        <button type="button" class="btn ghost" id="rev-next">Next</button>
      </div>
    </div>
    ${mem.review_reason
      ? `<div class="reason">⚠ ${esc(reasonLabel(mem.review_reason))}</div>` : ""}
    <div class="review-compare">
      ${memCard(mem, evidence, "Candidate")}
      ${related
        ? memCard(related, relatedEvidence, neighHeading)
        : `<div class="mem-card empty-card"><div class="meta">No similar memory nearby</div></div>`}
      ${neighborRailHtml(neighbors, selectedId)}
    </div>
    <form class="row review-controls" id="review-form">
      <div class="field"><label>Domain</label>
        <select name="domain">${selectOptions("domain", DOMAIN_OPTIONS, mem.domain)}</select>
      </div>
      <div class="field"><label>Sensitivity</label>
        <select name="sensitivity">${selectOptions("sensitivity", SENSITIVITY_OPTIONS, mem.sensitivity)}</select>
      </div>
      <button type="button" class="btn ok" data-act="approve">A · Approve</button>
      <button type="button" class="btn err" data-act="reject">R · Reject</button>
      <button type="button" class="btn" data-act="update">E · Save details</button>
      <button type="button" class="btn" data-act="defer">Defer</button>
      <button type="button" class="btn ghost" data-act="archive">Archive</button>
      <button type="button" class="btn ghost" data-act="skip">S · Skip</button>
    </form>
    ${issuesPanelHtml(findings, neighbors)}
    ${splitPanelHtml(mem)}
  `;

  bindReviewHandlers(mem);
}

function bindReviewHandlers(mem) {
  const { queue, index } = state.review;

  $("#rev-prev")?.addEventListener("click", () => {
    state.review.index = Math.max(0, index - 1);
    state.review.selectedRelatedId = null;
    state.review.splitOpen = false;
    renderReviewItem();
  });
  $("#rev-next")?.addEventListener("click", () => {
    state.review.index = Math.min(queue.length - 1, index + 1);
    state.review.selectedRelatedId = null;
    state.review.splitOpen = false;
    renderReviewItem();
  });

  $("#rev-reanalyze")?.addEventListener("click", async () => {
    try {
      toast("Re-analyzing…");
      const quality = await api(`/api/memories/${mem.id}/quality?refresh=true`);
      state.review.quality = quality;
      state.review.findings = quality?.issues || [];
      renderReviewItem();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  for (const pick of document.querySelectorAll("[data-select-related]")) {
    pick.addEventListener("click", () => {
      state.review.selectedRelatedId = pick.dataset.selectRelated;
      renderReviewItem();
    });
  }

  for (const resolveBtn of document.querySelectorAll("[data-resolve]")) {
    resolveBtn.addEventListener("click", async () => {
      const action = resolveBtn.dataset.resolve;
      const findingId = resolveBtn.dataset.finding || undefined;
      const related = resolveBtn.dataset.related || state.review.selectedRelatedId || undefined;

      if (action === "split") {
        state.review.splitOpen = true;
        renderReviewItem();
        return;
      }
      if (["merge", "contradict", "supersede", "supersede_by"].includes(action) && !related) {
        toast("Select a related memory first", "err");
        return;
      }
      resolveBtn.disabled = true;
      try {
        const out = await resolveMemory(mem.id, {
          action,
          related_memory_id: related || null,
          finding_id: findingId || null,
        });
        const labels = {
          merge: "Merged into one",
          contradict: "Marked as conflicting",
          supersede: "This replaced the other",
          supersede_by: "Related kept; this deprecated",
          dismiss: "Issue cleared",
          archive: "Archived",
          request_evidence: "Staying in review for evidence",
          defer: "Deferred",
          confirm: "Approved",
          reject: "Rejected this copy",
        };
        toast(labels[action] || "Resolved", "ok");
        if (out.removed_from_queue?.length) {
          removeFromReviewQueue(out.removed_from_queue);
        }
        renderReviewItem();
      } catch (err) {
        toast(err.message, "err");
        resolveBtn.disabled = false;
      }
    });
  }

  $("#split-cancel")?.addEventListener("click", () => {
    state.review.splitOpen = false;
    renderReviewItem();
  });
  $("#split-confirm")?.addEventListener("click", async () => {
    const panel = $("#split-panel");
    if (!panel) return;
    const parts = [
      {
        title: panel.querySelector('[name="p1_title"]').value.trim(),
        summary: panel.querySelector('[name="p1_summary"]').value.trim(),
      },
      {
        title: panel.querySelector('[name="p2_title"]').value.trim(),
        summary: panel.querySelector('[name="p2_summary"]').value.trim(),
      },
    ];
    if (parts.some((p) => !p.title || !p.summary)) {
      toast("Both parts need title and summary", "err");
      return;
    }
    try {
      const out = await resolveMemory(mem.id, { action: "split", parts });
      toast("Split into candidates", "ok");
      removeFromReviewQueue(out.removed_from_queue || [mem.id]);
      renderReviewItem();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#review-form")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "skip") {
      state.review.index = Math.min(queue.length - 1, index + 1);
      state.review.selectedRelatedId = null;
      state.review.splitOpen = false;
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
      const msg = {
        approve: "Approved",
        reject: "Rejected",
        update: "Saved",
        defer: "Deferred",
        archive: "Archived",
      }[act] || "Done";
      toast(msg, "ok");
      if (act === "approve" || act === "reject" || act === "archive") {
        removeFromReviewQueue([mem.id]);
      }
      renderReviewItem();
    } catch (err) {
      toast(err.message, "err");
      btn.disabled = false;
    }
  });
}

function fmtWhen(iso) {
  if (!iso) return "";
  return String(iso).slice(0, 16).replace("T", " ");
}

/** Body text only when it adds something beyond the title (CLI does the same). */
function memBody(mem, { max = 0 } = {}) {
  const title = String(mem?.title || "").trim();
  let summary = String(mem?.summary || "").trim();
  if (!summary || summary === title) return "";
  // Echo / short extracts: title is truncated summary ("foo…").
  if (title.endsWith("...") && summary.startsWith(title.slice(0, -3))) {
    const rest = summary.slice(title.length - 3).trim();
    if (!rest) return "";
    // Still mostly the same sentence — prefer full summary only if much longer.
    if (summary.length <= title.length + 12) return "";
  }
  if (max && summary.length > max) {
    // Break on a word boundary so the web UI never mid-cuts a sentence.
    let cut = summary.slice(0, max);
    const sp = cut.lastIndexOf(" ");
    if (sp > Math.floor(max * 0.6)) cut = cut.slice(0, sp);
    summary = `${cut.trimEnd()}…`;
  }
  return summary;
}

function memBodyHtml(mem, { max = 0 } = {}) {
  const full = String(mem?.summary || "").trim();
  const shown = memBody(mem, { max });
  if (!shown) return "";
  if (!max || full.length <= max || shown === full) {
    return `<p class="mem-summary">${esc(shown)}</p>`;
  }
  // Expandable: list views may clip; click reveals the rest.
  return `
    <details class="mem-summary-details">
      <summary class="mem-summary">${esc(shown)}</summary>
      <p class="mem-summary mem-summary-full">${esc(full)}</p>
    </details>`;
}

function memCard(mem, evidence, heading) {
  const conf = pct01(mem.confidence);
  const review = pct01(mem.review_priority);
  const when = fmtWhen(mem.created_at);
  return `
    <article class="mem-card">
      <div class="card-kicker">${esc(heading)}</div>
      ${when ? `<div class="card-when">${esc(when)}</div>` : ""}
      <h3>${esc(mem.title)}</h3>
      ${memTags(mem, { showAltitude: false, showSources: false, showFlags: true })}
      <div class="stats-line">
        <span>Altitude <strong>${esc(altitudeLabel(mem))}</strong></span>
        <span>Confidence <strong>${conf}%</strong></span>
        <span>Review <strong>${review}%</strong></span>
      </div>
      ${memBodyHtml(mem, { max: 0 })}
      ${evidenceAccordion(evidence)}
      ${sourcesAccordion(mem)}
      ${basedInAccordion(mem)}
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
  if (key === "m") {
    e.preventDefault();
    document.querySelector('#neighbor-tools [data-resolve="merge"]')?.click();
  }
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
          <select name="domain">${selectOptions("domain", PACK_DOMAIN_OPTIONS, "technical")}</select>
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
      // Relative relevance within this result page (top hit = 100%).
      const maxScore = Math.max(...data.hits.map((h) => Number(h.score) || 0), 1e-9);
      out.innerHTML = data.hits.map((h) => {
        const pct = Math.round(((Number(h.score) || 0) / maxScore) * 100);
        const why = String(h.why || "")
          .split(",")
          .map((p) => p.trim())
          .filter(Boolean)
          .map((p) => {
            const friendly = LABELS.why[p]
              || (p.startsWith("graph expansion") ? "Related via graph" : humanizeKey(p));
            return tag(friendly, "why");
          });
        return `<div class="hit">
          <div class="hit-score">
            <div class="score">${pct}%</div>
            <div class="bar"><i style="width:${pct}%"></i></div>
            ${why.length ? `<div class="tags why">${why.join("")}</div>` : ""}
          </div>
          <div>
            <strong>${esc(h.title)}</strong>
            ${memTags(h)}
            ${memBodyHtml(h, { max: 0 })}
          </div>
        </div>`;
      }).join("") + (data.blocked?.length
        ? `<p class="meta" style="margin-top:1rem">${data.blocked.length} blocked by privacy firewall</p>`
        : "");
    } catch (err) {
      out.innerHTML = `<div class="empty"><strong>Search failed</strong>${esc(err.message)}</div>`;
    }
  });
}

/* —— Narratives —— */

async function narratives() {
  app.innerHTML = `
    <div class="panel">
      <h2>Narratives</h2>
      <p class="lede">Committed accounts with EpistemicState. Commit requires evidence + preview fingerprint.</p>
      <div class="row" style="gap:1rem;align-items:flex-start">
        <div style="flex:1">
          <h3>Open Reflections</h3>
          <div id="nar-reflections" class="empty"><span class="spinner"></span></div>
          <h3 style="margin-top:1.25rem">Narratives</h3>
          <div id="nar-list" class="empty"><span class="spinner"></span></div>
        </div>
        <div style="flex:1" class="panel" id="nar-commit-panel">
          <h3>Commit Narrative</h3>
          <form id="nar-commit-form">
            <div class="field"><label>Account</label>
              <textarea name="account" required rows="4" placeholder="What is true, in your words"></textarea></div>
            <div class="field"><label>Evidence ids (comma-separated)</label>
              <input name="evidence" required placeholder="pct_…, pct_…" /></div>
            <div class="field"><label>Actor</label>
              <input name="actor" required value="user" /></div>
            <div class="field"><label>Domain</label>
              <select name="domain">${selectOptions("domain", PACK_DOMAIN_OPTIONS, "technical")}</select></div>
            <div class="row" style="margin-top:.75rem;gap:.5rem">
              <button class="btn" type="button" id="nar-preview">Preview token</button>
              <button class="btn primary" type="submit">Commit</button>
            </div>
            <p class="meta" id="nar-token" style="margin-top:.5rem"></p>
          </form>
        </div>
      </div>
    </div>
  `;
  let previewToken = "";
  try {
    const [nars, refs] = await Promise.all([
      api("/api/narratives"),
      api("/api/reflections?status=open"),
    ]);
    const refEl = $("#nar-reflections");
    if (!refs?.length) {
      refEl.innerHTML = `<div class="empty">No open reflections</div>`;
    } else {
      refEl.innerHTML = refs.map((r) =>
        `<div class="hit"><strong>${esc(r.id)}</strong>
         <span class="tag">${esc(r.status || "open")}</span>
         <p>${esc(r.text || "")}</p></div>`
      ).join("");
    }
    const list = $("#nar-list");
    if (!nars?.length) {
      list.innerHTML = `<div class="empty">No narratives yet</div>`;
    } else {
      list.innerHTML = nars.map((n) => {
        const st = n.epistemic_status || "unknown";
        const badge = st === "stale"
          ? `<span class="tag" title="${esc(n.stale_reason || "")}">Epistemic: stale — ${esc(n.stale_reason || "new evidence")}</span>`
          : `<span class="tag">Epistemic: ${esc(st)}</span>`;
        return `<div class="hit">
          <strong>${esc(n.id)}</strong> ${badge}
          <span class="tag">${esc(n.sensitivity || "internal")}</span>
          <p>${esc(n.account || "")}</p>
        </div>`;
      }).join("");
    }
  } catch (err) {
    $("#nar-list").innerHTML = `<div class="empty"><strong>Load failed</strong>${esc(err.message)}</div>`;
  }

  $("#nar-preview").addEventListener("click", async () => {
    const fd = new FormData($("#nar-commit-form"));
    const evidence_ids = String(fd.get("evidence") || "").split(",").map((s) => s.trim()).filter(Boolean);
    try {
      const prev = await api("/api/narratives/commit-preview", {
        method: "POST",
        body: JSON.stringify({
          account: fd.get("account"),
          evidence_ids,
          actor: fd.get("actor"),
          domain: fd.get("domain"),
        }),
      });
      previewToken = prev.preview_token || "";
      $("#nar-token").textContent = previewToken
        ? `preview_token ${previewToken} — confirm to commit`
        : "no token";
      toast("Preview ready", "ok");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#nar-commit-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const evidence_ids = String(fd.get("evidence") || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (!evidence_ids.length) {
      toast("evidence required", "err");
      return;
    }
    if (!previewToken) {
      toast("run Preview token first", "err");
      return;
    }
    try {
      const out = await api("/api/narratives/commit", {
        method: "POST",
        body: JSON.stringify({
          account: fd.get("account"),
          evidence_ids,
          actor: fd.get("actor"),
          domain: fd.get("domain"),
          preview_token: previewToken,
        }),
      });
      toast(`Committed ${out.narrative_id}`, "ok");
      previewToken = "";
      narratives();
    } catch (err) {
      toast(err.message, "err");
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
            <select name="target_domain">${selectOptions("domain", PACK_DOMAIN_OPTIONS, "technical")}</select>
          </div>
          <div class="field"><label>Persona</label>
            <select name="persona">${selectOptions("persona", PERSONA_OPTIONS, "individual")}</select>
          </div>
          <div class="field"><label>Max tokens</label>
            <input name="max_tokens" type="number" value="1200" min="100" max="8000" /></div>
          <div class="field"><label>Include</label>
            <select name="include_candidates">
              <option value="false">Confirmed only</option>
              <option value="true">Also needs-review</option>
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
      const blocked = data.blocked_count ?? (data.blocked || []).length;
      meta.innerHTML = `<div class="tags">
        ${tag(`Confidence ${pct01(data.confidence)}%`, "ok")}
        ${tag(`${(data.sources || []).length} sources`)}
        ${tag(blocked ? `${blocked} blocked` : "Nothing blocked", blocked ? "warn" : "ok")}
        ${tag(label("mode", data.mode || "compact"))}
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

const MEM_TYPE_FILTER = ["", ...Object.keys(LABELS.type)];
const MEM_DOMAIN_FILTER = ["", ...DOMAIN_OPTIONS];
const MEM_SENS_FILTER = ["", ...SENSITIVITY_OPTIONS];
const MEM_ALTITUDE_FILTER = ["", "ground", "linked", "distilled", "stance"];
const MEM_FLAG_FILTER = ["", ...Object.keys(LABELS.flag)];
const MEM_SOURCE_FILTER = ["", "github", "slack", "git", "document", "meeting",
  "mail", "episode_reflect", "episode", "pattern"];

function memoriesMatchFilters(m, f) {
  if (f.status && m.status !== f.status) return false;
  if (f.type && m.type !== f.type) return false;
  if (f.domain && m.domain !== f.domain) return false;
  if (f.sensitivity && m.sensitivity !== f.sensitivity) return false;
  const alt = m.altitude || (m.payload && m.payload.altitude) || "ground";
  if (f.altitude && alt !== f.altitude) return false;
  const condensed = !!(m.condensed || (m.payload || {}).condensed
    || ((m.payload || {}).merged_from || []).length);
  if (f.condensed === "yes" && !condensed) return false;
  if (f.condensed === "no" && condensed) return false;
  if (f.flag && !(m.quality_flags || []).includes(f.flag)) return false;
  if (f.source) {
    const sensors = m.sources || [];
    const refs = (m.source_refs || []).map((r) => r.sensor);
    if (![...sensors, ...refs].includes(f.source)) return false;
  }
  if (f.q) {
    const blob = `${m.title || ""}\n${m.summary || ""}`.toLowerCase();
    if (!blob.includes(f.q)) return false;
  }
  return true;
}

function renderMemCardBrowse(m) {
  const when = (m.created_at || "").slice(0, 10);
  return `
    <article class="mem-card">
      <h3>${esc(m.title)}</h3>
      ${memTags(m, { showAltitude: false, showSources: false, showFlags: true })}
      <div class="stats-line">
        <span>Altitude <strong>${esc(altitudeLabel(m))}</strong></span>
        <span>Confidence <strong>${pct01(m.confidence)}%</strong></span>
        <span>Review <strong>${pct01(m.review_priority)}%</strong></span>
        ${when ? `<span>${esc(when)}</span>` : ""}
      </div>
      ${memBodyHtml(m, { max: 0 })}
      ${sourcesAccordion(m)}
      ${basedInAccordion(m)}
    </article>`;
}

async function memories() {
  app.innerHTML = `
    <div class="panel">
      <h2>Memories</h2>
      <p class="lede">Browse stored memory items.</p>
      <div class="mem-filters">
        <div class="field" style="flex:2"><label>Search</label>
          <input id="mem-q" type="search" placeholder="Title or summary…" /></div>
        <div class="field"><label>Status</label>
          <select id="mem-status">${selectOptions("status", STATUS_FILTER_OPTIONS, "")}</select></div>
        <div class="field"><label>Type</label>
          <select id="mem-type">${selectOptions("type", MEM_TYPE_FILTER, "")}</select></div>
        <div class="field"><label>Domain</label>
          <select id="mem-domain">${selectOptions("domain", MEM_DOMAIN_FILTER, "")}</select></div>
        <div class="field"><label>Sensitivity</label>
          <select id="mem-sens">${selectOptions("sensitivity", MEM_SENS_FILTER, "")}</select></div>
        <div class="field"><label>Altitude</label>
          <select id="mem-altitude">${selectOptions("altitude", MEM_ALTITUDE_FILTER, "")}</select></div>
        <div class="field"><label>Condensed</label>
          <select id="mem-condensed">
            <option value="">All</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select></div>
        <div class="field"><label>Source</label>
          <select id="mem-source">${selectOptions("sensor", MEM_SOURCE_FILTER, "")}</select></div>
        <div class="field"><label>Quality flag</label>
          <select id="mem-flag">${selectOptions("flag", MEM_FLAG_FILTER, "")}</select></div>
        <button class="btn" id="mem-reload">Refresh</button>
      </div>
      <p class="meta" id="mem-count" style="margin:.5rem 0 1rem"></p>
      <div id="mem-list"><span class="spinner"></span></div>
    </div>
  `;
  let cache = [];
  const filters = () => ({
    q: ($("#mem-q").value || "").trim().toLowerCase(),
    status: $("#mem-status").value,
    type: $("#mem-type").value,
    domain: $("#mem-domain").value,
    sensitivity: $("#mem-sens").value,
    altitude: $("#mem-altitude").value,
    condensed: $("#mem-condensed").value,
    source: $("#mem-source").value,
    flag: $("#mem-flag").value,
  });
  const render = () => {
    const list = $("#mem-list");
    const f = filters();
    const rows = cache.filter((m) => memoriesMatchFilters(m, f));
    $("#mem-count").textContent = rows.length
      ? `Showing ${rows.length} of ${cache.length}`
      : cache.length ? "No memories match these filters" : "";
    if (!cache.length) {
      list.innerHTML = `<div class="empty"><strong>No memories</strong></div>`;
      return;
    }
    if (!rows.length) {
      list.innerHTML = `<div class="empty"><strong>No matches</strong>Try clearing a filter.</div>`;
      return;
    }
    list.innerHTML = rows.slice(0, 200).map(renderMemCardBrowse).join("");
  };
  const load = async () => {
    const list = $("#mem-list");
    list.innerHTML = `<span class="spinner"></span>`;
    try {
      cache = await api("/api/memories?limit=1000");
      render();
    } catch (err) {
      list.innerHTML = `<div class="empty"><strong>Failed</strong>${esc(err.message)}</div>`;
    }
  };
  $("#mem-reload").addEventListener("click", load);
  for (const id of [
    "mem-status", "mem-type", "mem-domain", "mem-sens", "mem-altitude",
    "mem-condensed", "mem-source", "mem-flag",
  ]) {
    $(`#${id}`)?.addEventListener("change", render);
  }
  $("#mem-q")?.addEventListener("input", render);
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
