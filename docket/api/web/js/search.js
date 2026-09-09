/* Find agents: BSC marketplace services and separately labelled research records.

   Docket's own services are work Docket runs. It holds the code, publishes a recorded run
   behind each one. Only BSC-bound category services get activation controls here;
   historical and unregistered utilities keep their records in the research section.
   Everything at `/api/agents` is a third-party agent Docket observed in the ERC-8004
   registry. Docket did not write those, its category for one carries the
   `capability_source` that produced it, and being in a registry is not an offer.

   Two facts travel with every third-party listing and neither is derived from the other.
   The level says what Docket's evidence supports. `payment_tested` says whether a payment
   challenge was ever read — `docket_tested` hangs off `live`, not off a payment, so
   the level alone can never stand in for it. Registry listings remain research records
   here, regardless of their verification level. */

import * as api from "./api.js?v=13";
import {
  VERIFICATION_LEVELS,
  escapeHTML,
  region,
  renderFailure,
  timeAgo,
  verificationBadge,
} from "./ui.js?v=15";

const CATEGORIES = [
  ["rebalancing", "Manages LP ranges"],
  ["grid_trading", "Places and manages grid orders"],
  ["yield_optimisation", "Routes liquidity to the highest APR"],
  ["health_factor", "Protects lending positions"],
];

/* Where a third-party listing's category came from. A category Docket's own rule table
   read out of capability text is a different claim from one the owner declared, and a page
   that printed both the same way would be inventing agreement between them. */
const CAPABILITY_SOURCES = {
  provider_declared: "the owner declared this category",
  registration_metadata: "read from its on-chain registration",
  docket_classified:
    "Docket's printed rule table read this out of its capability text",
};

function readFilters() {
  const params = new URLSearchParams(window.location.search);
  return {
    q: params.get("q") || "",
    category: params.get("category") || "",
    level: params.get("level") || "",
  };
}

function toQuery(filters) {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) {
    if (value) params.set(name, value);
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

function paintControls(filters) {
  const categories = CATEGORIES.map(
    ([value, label]) =>
      `<option value="${escapeHTML(value)}"${filters.category === value ? " selected" : ""}>${escapeHTML(label)}</option>`,
  ).join("");
  const levels = VERIFICATION_LEVELS.map(
    ([value, means]) =>
      `<option value="${escapeHTML(value)}" title="${escapeHTML(means)}"${filters.level === value ? " selected" : ""}>${escapeHTML(
        value.replaceAll("_", " "),
      )} only</option>`,
  ).join("");
  region("controls").innerHTML =
    `<form class="search-form" data-search-form novalidate>
      <div class="field">
        <label for="search-q">Search</label>
        <input id="search-q" name="q" type="search" value="${escapeHTML(filters.q)}"
          placeholder="name, capability, address" />
      </div>
      <div class="field">
        <label for="search-category">Job</label>
        <select id="search-category" name="category">
          <option value="">Any of the four jobs</option>
          ${categories}
        </select>
      </div>
      <div class="field">
        <label for="search-level">Registry verification, exact level</label>
        <select id="search-level" name="level">
          <option value="">Any level, including never observed</option>
          ${levels}
        </select>
      </div>
      <p class="btn-row">
        <button type="submit" class="btn btn-primary">Search</button>
        <button type="button" class="btn" data-clear>Clear filters</button>
      </p>
    </form>`;
}

/* ---------------------------------------------------------------- the layers */

function docketRow(card, research = false) {
  const href = research
    ? `/service?id=${encodeURIComponent(card.service_id)}`
    : `/activate?service=${encodeURIComponent(card.service_id)}`;
  return `<li class="result-row" data-service="${escapeHTML(card.service_id)}">
      <div class="result-head">
        <h3><a href="${escapeHTML(href)}">${escapeHTML(card.name)}</a></h3>
        <span class="verify-badge" data-level="docket_run"
          title="Docket runs this service itself and publishes the record behind it.">Docket runs this</span>
      </div>
      <p class="dim">${escapeHTML(card.what_you_get)}</p>
      <dl class="deflist">
        <dt>Job</dt><dd>${escapeHTML(card.category_job || "Outside the four job categories")}</dd>
        <dt>Price</dt><dd class="num">${escapeHTML(card.price_display)}</dd>
        <dt>Paid stock</dt><dd>${escapeHTML(card.paid_stock ? "admitted" : card.stock_status)}</dd>
      </dl>
      <p class="btn-row">
        <a class="btn${research ? "" : " btn-primary"}" href="${escapeHTML(href)}">${research ? "Read service record" : "Activate"}</a>
      </p>
    </li>`;
}

/* What a reader could actually reach, as the listing declares it. A `web` link is a
   homepage rather than an invocable endpoint, so its kind is printed beside it. */
function endpointLine(listing) {
  const rows = listing.endpoints || [];
  if (!rows.length) return "no endpoint declared";
  return rows
    .map((row) => `${row.kind || "endpoint"} ${row.url || ""}`.trim())
    .join(", ");
}

/* Every level that was attempted and what it observed, passes and failures alike. A run
   that only showed its passes would be a scoreboard rather than a record. */
function evidenceList(verification) {
  const rows = verification.evidence || [];
  if (!rows.length) return "";
  return `<ul class="facts">${rows
    .map(
      (row) =>
        `<li><strong>${escapeHTML(row.level || "level")}</strong> — ${
          row.ok ? "passed" : "did not pass"
        }${row.at ? `, ${escapeHTML(timeAgo(row.at))}` : ""}</li>`,
    )
    .join("")}</ul>`;
}

function capabilitySource(listing) {
  return (
    CAPABILITY_SOURCES[listing.capability_source] ||
    "Docket does not know where this category came from"
  );
}

function listingRow(listing) {
  const verification = listing.verification || {};
  const href = `/agent?id=${encodeURIComponent(listing.agent_id)}`;
  return `<li class="result-row" data-agent="${escapeHTML(listing.agent_id)}">
      <div class="result-head">
        <h3><a href="${escapeHTML(href)}">${escapeHTML(listing.name || "(no name)")}</a></h3>
        ${verificationBadge(verification)}
      </div>
      <p class="dim">${escapeHTML(listing.capabilities || endpointLine(listing))}</p>
      <dl class="deflist">
        <dt>Agent</dt><dd class="mono">${escapeHTML(listing.agent_id)}</dd>
        <dt>Job</dt><dd>${escapeHTML(listing.category || "not filed under one of the four jobs")}
          <span class="dim">— ${escapeHTML(capabilitySource(listing))}</span></dd>
        <dt>Price the provider states</dt><dd>${escapeHTML(listing.price || "none stated")}</dd>
        <dt>Endpoints</dt><dd class="wrap-anywhere">${escapeHTML(endpointLine(listing))}</dd>
        <dt>Observed</dt><dd>${escapeHTML(timeAgo(verification.verified_at))}</dd>
      </dl>
      ${evidenceList(verification)}
      <p class="btn-row">
        <a class="btn" href="${escapeHTML(href)}">Read what Docket observed</a>
        <span class="dim">Research record only, not hireable from this site. An HTTP
          response does not establish that the agent performs its advertised work.</span>
      </p>
    </li>`;
}

function describe(filters) {
  const parts = [];
  if (filters.q) parts.push(`"${filters.q}"`);
  if (filters.category)
    parts.push(`the ${filters.category.replaceAll("_", " ")} job`);
  if (filters.level)
    parts.push(`exactly ${filters.level.replaceAll("_", " ")}`);
  return parts.length ? parts.join(", ") : "an unfiltered search";
}

function paintResults(answer, services, filters) {
  const items = answer.items || [];
  const primary = services.filter(
    (card) =>
      CATEGORIES.some(([category]) => category === card.category) &&
      /^56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:\d+$/i.test(
        card.agent_id || "",
      ),
  );
  const research = services.filter((card) => !primary.includes(card));
  const target = region("results");
  const total = answer.total === undefined ? items.length : answer.total;
  if (!items.length && !services.length) {
    target.innerHTML = `<div class="panel">
        <h2>No agent matched</h2>
        <p>Nothing Docket runs, and nothing in the registry slice it has swept, matches
          ${escapeHTML(describe(filters))}. A zero here is the answer, not a gap.</p>
        <p class="btn-row"><button type="button" class="btn" data-clear>Clear filters</button></p>
      </div>`;
    return;
  }
  const lookup = answer.registry_lookup || {};
  target.innerHTML = `<p class="section-note" data-field="result-count">
      ${primary.length} BSC marketplace service${primary.length === 1 ? "" : "s"},
      ${research.length} research-only service${research.length === 1 ? "" : "s"}, and
      ${items.length} of ${escapeHTML(String(total))} registry research listings matched
      ${escapeHTML(describe(filters))}.
      ${filters.level ? "Docket services are not filtered by registry verification level." : ""}
    </p>
    ${
      lookup.reason
        ? `<div class="notice"><p>The registry was not swept for this query:
             ${escapeHTML(lookup.reason)}. What is below is what Docket already held.</p></div>`
        : ""
    }
    <section aria-labelledby="docket-layer-heading">
      <h3 id="docket-layer-heading">Services Docket runs</h3>
      <p class="section-note">BSC-bound services across the four marketplace categories.
        Each shows its own evidence and limits. Activation is available here.</p>
      ${
        primary.length
          ? `<ul class="result-list">${primary.map((card) => docketRow(card)).join("")}</ul>`
          : `<p class="dim">No BSC marketplace service matches ${escapeHTML(describe(filters))}.</p>`
      }
    </section>
    ${
      research.length
        ? `<section aria-labelledby="research-layer-heading">
      <h3 id="research-layer-heading">Research-only services</h3>
      <p class="section-note">Historical or unregistered utilities, not live BSC category
        listings. Their records remain available separately from the marketplace.</p>
      <ul class="result-list">${research.map((card) => docketRow(card, true)).join("")}</ul>
      <p><a href="/research#research-services">Read the research context</a></p>
    </section>`
        : ""
    }
    <section aria-labelledby="registry-layer-heading">
      <h3 id="registry-layer-heading">Third-party agents Docket observed</h3>
      <p class="section-note">Registry research, not marketplace inventory. Registered by
        somebody else on BSC; Docket does not sell or recommend these agents. Being in a
        registry is not an offer. Each record preserves what was observed, when, whether
        a payment challenge was read, and where its category came from. A reachable host
        is not proof of functional trading or current availability.</p>
      ${
        items.length
          ? `<ul class="result-list">${items.map(listingRow).join("")}</ul>`
          : `<p class="dim">No registry listing matches ${escapeHTML(describe(filters))}.</p>`
      }
    </section>`;
}

/* ------------------------------------------------------------------- loading */

/* The two layers are two requests, and one failing must not blank the other: a registry
   sweep that times out should still leave the reader able to see and activate what Docket
   runs. The Docket layer is filtered on `category` only — it has no verification level,
   because Docket running something itself is not an observation about somebody else. */
async function fetchLayers(filters) {
  const [listings, services] = await Promise.allSettled([
    api.searchAgents(filters),
    api.listServices(filters.category || null),
  ]);
  if (listings.status === "rejected" && services.status === "rejected") {
    throw listings.reason;
  }
  return {
    answer:
      listings.status === "fulfilled"
        ? listings.value
        : { items: [], total: 0 },
    services:
      services.status === "fulfilled"
        ? matching(services.value.services, filters)
        : [],
    partial:
      listings.status === "rejected"
        ? `The registry listings could not be read: ${listings.reason.message}`
        : services.status === "rejected"
          ? `Docket's own services could not be read: ${services.reason.message}`
          : null,
  };
}

/* `/services` has no text search, so the query is applied here over the fields a reader
   would have been searching: what Docket calls the service and what it says it does. */
function matching(services, filters) {
  const needle = filters.q.trim().toLowerCase();
  if (!needle) return services || [];
  return (services || []).filter((card) =>
    `${card.name} ${card.service_id} ${card.what_you_get}`
      .toLowerCase()
      .includes(needle),
  );
}

async function load(filters, { push }) {
  const target = region("results");
  target.setAttribute("aria-busy", "true");
  const url = `/search${toQuery(filters)}`;
  if (push) window.history.pushState(filters, "", url);
  try {
    const { answer, services, partial } = await fetchLayers(filters);
    paintResults(answer, services, filters);
    if (partial) {
      target.insertAdjacentHTML(
        "afterbegin",
        `<div class="notice notice-warn"><p>${escapeHTML(partial)} One layer of this page is
          missing, and it is not being shown as an empty one.</p></div>`,
      );
    }
    region("live-status").textContent = "Search finished.";
  } catch (err) {
    renderFailure(target, err, {
      heading: "The search could not run",
      actions: [{ label: "Clear filters", action: "clear" }],
    });
  } finally {
    target.setAttribute("aria-busy", "false");
  }
}

function currentFilters() {
  const form = document.querySelector("[data-search-form]");
  return {
    q: form.elements.namedItem("q").value.trim(),
    category: form.elements.namedItem("category").value,
    level: form.elements.namedItem("level").value,
  };
}

export async function init() {
  const filters = readFilters();
  paintControls(filters);
  document.addEventListener("click", async (event) => {
    if (!event.target.closest("[data-clear], [data-action='clear']")) return;
    const cleared = { q: "", category: "", level: "" };
    paintControls(cleared);
    await load(cleared, { push: true });
  });
  document.addEventListener("submit", async (event) => {
    if (!event.target.matches("[data-search-form]")) return;
    event.preventDefault();
    await load(currentFilters(), { push: true });
  });
  window.addEventListener("popstate", async () => {
    const restored = readFilters();
    paintControls(restored);
    await load(restored, { push: false });
  });
  await load(filters, { push: false });
}
