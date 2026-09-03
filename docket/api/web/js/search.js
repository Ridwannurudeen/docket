/* Find agents: one search over Docket's own stock and the registry it observes, filtered by
   job and by how far Docket has actually got with each one.

   The verification level is the whole point of this page. A registry entry that nothing has
   ever called is still shown, because hiding it would misrepresent what is out there — but
   it is shown as `registered`, and the page says in as many words that Docket cannot run it.
   The badge is a statement about Docket's evidence, never a rating of the agent. */

import * as api from "./api.js?v=13";
import {
  VERIFICATION_LEVELS,
  escapeHTML,
  isHireable,
  region,
  renderFailure,
  timeAgo,
  verificationBadge,
} from "./ui.js?v=13";

const CATEGORIES = [
  ["rebalancing", "Manages LP ranges"],
  ["grid_trading", "Places and manages grid orders"],
  ["yield_optimisation", "Routes liquidity to the highest APR"],
  ["health_factor", "Protects lending positions"],
];

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
      )} or better</option>`,
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
        <label for="search-level">Verification, at least</label>
        <select id="search-level" name="level">
          <option value="">Any level, including untested</option>
          ${levels}
        </select>
      </div>
      <p class="btn-row">
        <button type="submit" class="btn btn-primary">Search</button>
        <button type="button" class="btn" data-clear>Clear filters</button>
      </p>
    </form>`;
}

/* Docket-verified supply is activated here; a registry entry is read here and hired
   somewhere else, if at all. Sending a reader to /activate for an agent Docket has never
   run would be a purchase button over an unknown, which is the exact failure this whole
   verification vocabulary exists to prevent. */
function destination(agent) {
  if (
    agent.service_id &&
    isHireable(agent.verification && agent.verification.level)
  ) {
    return {
      href: `/activate?service=${encodeURIComponent(agent.service_id)}`,
      label: "Activate",
      hireable: true,
    };
  }
  return {
    href: `/agent?id=${encodeURIComponent(agent.agent_id)}`,
    label: "Read what Docket observed",
    hireable: false,
  };
}

function resultRow(agent) {
  const verification = agent.verification || {};
  const target = destination(agent);
  const evidence = (verification.evidence || [])
    .map((ref) =>
      typeof ref === "string"
        ? `<li>${escapeHTML(ref)}</li>`
        : `<li><a href="${escapeHTML(ref.url || "#")}">${escapeHTML(ref.label || ref.kind || "record")}</a></li>`,
    )
    .join("");
  return `<li class="result-row" data-agent="${escapeHTML(agent.agent_id)}">
      <div class="result-head">
        <h3><a href="${escapeHTML(target.href)}">${escapeHTML(agent.name || "(no name)")}</a></h3>
        ${verificationBadge(verification.level)}
      </div>
      <p class="dim">${escapeHTML(agent.description || agent.endpoint || "")}</p>
      <dl class="deflist">
        <dt>Agent</dt><dd class="mono">${escapeHTML(agent.agent_id)}</dd>
        <dt>Job</dt><dd>${escapeHTML(agent.category || "not one of the four jobs")}</dd>
        <dt>Verified</dt><dd>${escapeHTML(timeAgo(verification.verified_at))}</dd>
      </dl>
      ${evidence ? `<ul class="facts">${evidence}</ul>` : ""}
      <p class="btn-row">
        <a class="btn${target.hireable ? " btn-primary" : ""}" href="${escapeHTML(target.href)}">${escapeHTML(target.label)}</a>
        ${
          target.hireable
            ? ""
            : '<span class="dim">Docket has not run this agent, so it cannot be activated here.</span>'
        }
      </p>
    </li>`;
}

function paintResults(listing, filters) {
  const agents = listing.agents || [];
  const target = region("results");
  if (!agents.length) {
    target.innerHTML = `<div class="panel">
        <h2>No agent matched</h2>
        <p>Nothing in Docket's stock or in the registry slice it has swept matches
          ${escapeHTML(describe(filters))}. A zero here is the answer, not a gap.</p>
        <p class="btn-row"><button type="button" class="btn" data-clear>Clear filters</button></p>
      </div>`;
    return;
  }
  const untested = agents.filter(
    (agent) => !isHireable((agent.verification || {}).level),
  ).length;
  target.innerHTML = `<p class="section-note" data-field="result-count">
      ${agents.length} of ${escapeHTML(String(listing.total === undefined ? agents.length : listing.total))}
      matched ${escapeHTML(describe(filters))}.
    </p>
    ${
      untested
        ? `<div class="notice notice-warn">
             <p class="notice-heading">${untested} of these are registry entries Docket has not run</p>
             <p>An entry below <span class="mono">docket_tested</span> is a record somebody
               published on chain. Docket has not executed it, has not settled a payment with
               it, and has no result to show for it — so it is not hireable from this site, and
               nothing here should be read as a recommendation to hire it elsewhere.</p>
           </div>`
        : ""
    }
    <ul class="result-list">${agents.map(resultRow).join("")}</ul>`;
}

function describe(filters) {
  const parts = [];
  if (filters.q) parts.push(`"${filters.q}"`);
  if (filters.category)
    parts.push(`the ${filters.category.replaceAll("_", " ")} job`);
  if (filters.level)
    parts.push(`${filters.level.replaceAll("_", " ")} or better`);
  return parts.length ? parts.join(", ") : "an unfiltered search";
}

async function load(filters, { push }) {
  const target = region("results");
  target.setAttribute("aria-busy", "true");
  const url = `/search${toQuery(filters)}`;
  if (push) window.history.pushState(filters, "", url);
  try {
    paintResults(await api.searchAgents(filters), filters);
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
