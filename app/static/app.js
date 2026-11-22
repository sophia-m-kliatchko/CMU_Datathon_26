// Find the Right Care: front end. Talks to /api/* only. No build step, no dependencies.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const form = $("#search");
  const results = $("#results");
  const pinInput = $("#pincode");
  const pinStatus = $("#pin-status");
  const urgency = $("#urgency");
  const TIER_LABEL = { T1: "Current cert.", T2: "Expired cert.", T3: "Indirect", R: "Under review", U: "No evidence", X: "Contradicted" };
  const SERVICES = {};
  const TIER_COLOR = { T1: "var(--t1)", T2: "var(--t2)", T3: "var(--t3)", R: "var(--tr)", U: "var(--tu)", X: "var(--tx)" };

  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) n.append(k);
    return n;
  };

  async function api(path, opts) {
    const r = await fetch(path, opts);
    let body = null;
    try { body = await r.json(); } catch (_) { /* non-JSON */ }
    if (!r.ok) {
      const d = body && body.detail;
      throw new Error(typeof d === "string" ? d : (Array.isArray(d) ? d.map(x => x.msg).join("; ") : `Request failed (${r.status})`));
    }
    return body;
  }

  // ---- startup: services + health ----
  async function init() {
    try {
      const { services } = await api("/api/services");
      const sel = $("#service");
      services.forEach(s => { SERVICES[s.tag] = s; });
      sel.replaceChildren(el("option", { value: "", text: "Select a service…" }),
        ...services.map(s => el("option", { value: s.tag, text: s.label })));
      sel.addEventListener("change", () => {
        const s = SERVICES[sel.value];
        $("#service-hint").textContent = !s ? "Choose the service, e.g. dialysis." :
          s.best_tier === "T1" ? `Strongest possible evidence: T1, from ${s.best_source}.` :
          `Strongest evidence available for this service is T3 (${s.best_source}). No source certifies it directly.`;
      });
    } catch (e) {
      $("#service").replaceChildren(el("option", { value: "", text: "Couldn't load services" }));
    }
    try {
      const h = await api("/api/health");
      $("#status").textContent = `data: ${h.data_mode} · evidence: ${h.evidence_provider} · ranking: ${h.ranker}` +
        (h.explainer ? ` · explainer: ${h.explainer}` : " · explainer: off");
      if (h.provisional_note) $("#provisional-text").textContent = h.provisional_note;
      if (h.data_mode === "mock") {
        $("#provisional-text").textContent = "Demo mode: the facilities below are made up and only illustrate the layout.";
      }
      $("#provisional").hidden = !(h.provisional || h.data_mode === "mock");
    } catch (_) { /* leave defaults */ }
  }

  // ---- PIN check as you type ----
  let pinTimer;
  pinInput.addEventListener("input", () => {
    clearTimeout(pinTimer);
    const v = pinInput.value.replace(/[\s-]/g, "");
    pinStatus.className = "field__hint";
    if (v.length < 6) { pinStatus.textContent = "6-digit India Post PIN code."; return; }
    pinTimer = setTimeout(async () => {
      try {
        const p = await api(`/api/pin/${encodeURIComponent(v)}`);
        pinStatus.textContent = `${p.district}, ${p.state} · ${p.n_post_offices} post office${p.n_post_offices === 1 ? "" : "s"}`;
        pinStatus.classList.add("is-ok");
      } catch (e) {
        pinStatus.textContent = e.message;
        pinStatus.classList.add("is-bad");
      }
    }, 350);
  });

  urgency.addEventListener("change", () => { $("#emergency").hidden = urgency.value !== "emergency"; });

  // ---- search ----
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const service = $("#service").value;
    const pincode = pinInput.value.trim();
    if (!service) { $("#service").focus(); $("#service-hint").textContent = "Please choose a service."; return; }
    if (!pincode) { pinInput.focus(); pinStatus.textContent = "Please enter your PIN code."; pinStatus.className = "field__hint is-bad"; return; }

    const go = $("#go");
    go.disabled = true; go.setAttribute("aria-busy", "true");
    results.setAttribute("aria-busy", "true");
    results.replaceChildren(el("div", { class: "skeleton" }), el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
    try {
      const data = await api("/api/recommend", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ service, pincode, radius_km: Number($("#radius").value), urgency: urgency.value }),
      });
      render(data);
    } catch (e) {
      results.replaceChildren(el("div", { class: "error", role: "alert" }, el("strong", { text: "We couldn't run that search. " }), e.message));
    } finally {
      go.disabled = false; go.removeAttribute("aria-busy");
      results.setAttribute("aria-busy", "false");
      results.focus({ preventScroll: true });
    }
  });

  function render(d) {
    const q = d.query;
    const frag = document.createDocumentFragment();
    const head = el("div", { class: "results__head" },
      el("h2", { class: "results__title" }, `${q.service_label} `, el("em", { text: `near ${q.pincode}` })),
      el("p", { class: "results__meta", text: `${d.n_candidates} facilities within ${q.radius_km} km${d.candidates_capped ? " (nearest shown)" : ""}` }));
    frag.append(head);
    frag.append(el("p", { class: "origin" }, "Measured from the centre of ",
      el("code", { text: d.origin.pincode }), ` (${d.origin.district}, ${d.origin.state}).`));

    if (d.origin.warnings && d.origin.warnings.length) {
      frag.append(el("ul", { class: "notes" }, ...d.origin.warnings.map(w => el("li", { text: w }))));
    }

    // evidence distribution across ALL candidates (before truncation)
    const total = Object.values(d.tier_counts).reduce((a, b) => a + b, 0) || 1;
    const order = ["T1", "T2", "T3", "R", "U", "X"];
    const bar = el("div", { class: "tierbar", role: "img",
      "aria-label": "Evidence levels across all candidates: " + order.filter(t => d.tier_counts[t]).map(t => `${d.tier_counts[t]} ${TIER_LABEL[t]}`).join(", ") });
    for (const t of order) if (d.tier_counts[t]) {
      const s = el("span"); s.style.width = `${100 * d.tier_counts[t] / total}%`; s.style.background = TIER_COLOR[t]; bar.append(s);
    }
    frag.append(bar, el("p", { class: "tierbar__legend" },
      ...order.filter(t => d.tier_counts[t]).map(t => el("span", {}, el("span", { class: `tier tier--${t}`, text: t }), ` ${d.tier_counts[t]}`))));

    if (q.best_tier === "T3") {
      frag.append(el("p", { class: "notes notes--info", text:
        `For ${q.service_label.toLowerCase()}, the strongest evidence any source gives is T3 (${q.best_source}). ` +
        "No registry certifies this service directly, so T3 here is the best available, not a poor result." }));
    }
    const urgent = d.mode === "urgent";
    if (!d.recommendations.length && urgent) {
      frag.append(el("div", { class: "error", role: "status" },
        el("strong", { text: "No facility here has a confirmed emergency-capability record, so none is recommended for an emergency. " }),
        "No source provides that record yet. Facilities are listed by distance instead; confirm by phone before travelling."));
    } else if (!d.recommendations.some(r => ["T1", "T2", "T3"].includes(r.tier))) {
      frag.append(el("div", { class: "error", role: "status" },
        el("strong", { text: "No facility nearby has documentary evidence for this service. " }),
        "Try a larger radius. Facilities shown below only say so in their own listing; that isn't verified."));
    }
    d.recommendations.forEach((r, i) => frag.append(card(r, i, q.service)));
    if (!urgent && d.recommendations.length < 3) {
      frag.append(el("p", { class: "section-note", text: "No additional facilities found." }));
    }
    if (d.unconfirmed && d.unconfirmed.length) {
      frag.append(el("h3", { class: "section-title", text: "Nearest facilities, emergency capability not confirmed" }),
        el("p", { class: "section-note", text: "These have documentary evidence for this service, nearest first. Being listed doesn't mean they can take an emergency now." }));
      d.unconfirmed.forEach((r, i) => frag.append(card(r, i, q.service, true)));
    }
    if (d.alternatives.length) frag.append(alternatives(d.alternatives, urgent));
    results.replaceChildren(frag);
  }

  function card(r, i, service, listedOnly) {
    const node = $("#card-tpl").content.firstElementChild.cloneNode(true);
    if (listedOnly || !["T1", "T2", "T3"].includes(r.tier)) $(".why summary", node).textContent = "Why is this listed?";
    node.style.animationDelay = `${i * 70}ms`;
    $(".card__rank", node).textContent = String(i + 1);
    $(".card__name", node).textContent = r.facility_name;
    $(".card__place", node).textContent = [r.location, r.pincode].filter(Boolean).join(" · ");
    const stamp = $(".stamp", node);
    stamp.classList.add(`t-${r.tier}`);
    stamp.setAttribute("aria-label", `Evidence tier ${r.tier}: ${r.evidence_level}`);
    $(".stamp__tier", node).textContent = r.tier;
    $(".stamp__label", node).textContent = TIER_LABEL[r.tier] || r.evidence_level;
    $(".card__geo", node).classList.add(`geo-${r.geo_confidence}`);
    $(".card__dist", node).textContent = `${Number(r.distance_km).toFixed(1)} km`;
    $(".card__geolabel", node).textContent = `straight-line · ${r.geo_label}`;

    const ledger = $(".ledger", node);
    if (!r.evidence.length) ledger.append(el("li", {}, el("span", { class: "none", text: "No evidence found for this service." })));
    for (const e of r.evidence) {
      const src = el("span", { class: "src" }, e.source || "");
      if (e.url && /^https?:\/\//i.test(e.url)) { src.append(" · "); src.append(el("a", { href: e.url, target: "_blank", rel: "noopener noreferrer", text: "source" })); }
      if (e.status && e.status !== "counted") src.append(` · ${e.status}`);
      else if (!e.status && e.match && e.match.needs_review) src.append(" · match unconfirmed");
      ledger.append(el("li", {},
        el("span", { class: `kind ${e.kind === "self_reported" ? "kind--self" : ""}`, title: e.kind === "self_reported" ? "Facility's own listing" : "Independent registry",
          text: e.kind === "self_reported" ? "SELF" : "REG" }),
        el("span", {}, e.text, src)));
    }
    const warn = $(".warnings", node);
    for (const w of r.warnings) warn.append(el("li", { text: w }));
    $(".why__rank", node).textContent = r.ranking_explanation || "";

    const btn = $(".js-explain", node);
    const out = $(".why__text", node);
    const explainNow = async () => {
      btn.disabled = true; btn.textContent = "Writing explanation…";
      try {
        const x = await api("/api/explain", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ service, recommendation: r }) });
        out.replaceChildren(x.text, el("small", { text: x.generated_by === "template" ? (x.note || "Template explanation") :
          `Generated by ${x.generated_by} from the evidence above only. Check the sources.` }));
        btn.remove();
      } catch (e) {
        out.textContent = `Couldn't generate an explanation: ${e.message}`;
        btn.disabled = false; btn.textContent = "Try again";
      }
    };
    btn.addEventListener("click", explainNow);
    $(".why", node).open = true;
    explainNow();
    return node;
  }

  function alternatives(list, urgent) {
    const rows = list.map(a => el("tr", {},
      el("td", {}, el("span", { class: `tier tier--${a.tier}`, text: a.tier, title: a.evidence_level })),
      el("td", {}, el("strong", { text: a.facility_name }), el("br"), el("span", { text: a.location })),
      el("td", { class: "num", text: `${Number(a.distance_km).toFixed(1)} km` }),
      el("td", { text: a.geo_label })));
    return el("section", { class: "alts", "aria-labelledby": "alts-title" },
      el("h3", { id: "alts-title", text: urgent ? "Other nearby facilities" : "Nearby alternatives" }),
      el("table", {},
        el("thead", {}, el("tr", {}, el("th", { text: "Tier" }), el("th", { text: "Facility" }), el("th", { text: "Distance" }), el("th", { text: "Location" }))),
        el("tbody", {}, ...rows)));
  }

  init();
})();
