// Find the Right Care: front end. Talks to /api/* only. No build step, no dependencies.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const form = $("#search");
  const results = $("#results");
  const pinInput = $("#pincode");
  const pinStatus = $("#pin-status");
  const urgency = $("#urgency");
  const TIER_LABEL = { T1: "Strong", T2: "Moderate", T3: "Self-reported", R: "Registry only", U: "No evidence", X: "Contradicted" };
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
      sel.replaceChildren(el("option", { value: "", text: "Select a service…" }),
        ...services.map(s => el("option", { value: s.tag, text: s.label })));
    } catch (e) {
      $("#service").replaceChildren(el("option", { value: "", text: "Couldn't load services" }));
    }
    try {
      const h = await api("/api/health");
      $("#status").textContent = `data: ${h.data_mode} · evidence: ${h.evidence_provider} · ranking: ${h.ranker}` +
        (h.explainer ? ` · explainer: ${h.explainer}` : " · explainer: off");
      const placeholder = h.evidence_provider !== "table" || h.ranker === "placeholder";
      if (h.data_mode === "mock") {
        $("#provisional-text").textContent = "Demo mode: the facilities below are made up and only illustrate the layout.";
      }
      $("#provisional").hidden = !(placeholder || h.data_mode === "mock");
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

    if (!d.recommendations.length) {
      frag.append(el("div", { class: "error", role: "status" },
        el("strong", { text: "No facility nearby has evidence for this service. " }),
        "Try a larger radius. The nearest facilities are listed below, but nothing indicates they offer it."));
    }
    d.recommendations.forEach((r, i) => frag.append(card(r, i, q.service)));
    if (d.alternatives.length) frag.append(alternatives(d.alternatives));
    results.replaceChildren(frag);
  }

  function card(r, i, service) {
    const node = $("#card-tpl").content.firstElementChild.cloneNode(true);
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
      if (e.match && e.match.needs_review) src.append(" · match unconfirmed");
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
    btn.addEventListener("click", async () => {
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
    });
    return node;
  }

  function alternatives(list) {
    const rows = list.map(a => el("tr", {},
      el("td", {}, el("span", { class: `tier tier--${a.tier}`, text: a.tier, title: a.evidence_level })),
      el("td", {}, el("strong", { text: a.facility_name }), el("br"), el("span", { text: a.location })),
      el("td", { class: "num", text: `${Number(a.distance_km).toFixed(1)} km` }),
      el("td", { text: a.geo_label })));
    return el("section", { class: "alts", "aria-labelledby": "alts-title" },
      el("h3", { id: "alts-title", text: "Nearby alternatives" }),
      el("table", {},
        el("thead", {}, el("tr", {}, el("th", { text: "Tier" }), el("th", { text: "Facility" }), el("th", { text: "Distance" }), el("th", { text: "Location" }))),
        el("tbody", {}, ...rows)));
  }

  init();
})();
