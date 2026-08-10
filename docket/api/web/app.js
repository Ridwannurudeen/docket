/* Docket web UI. One authored ES module, no build step, no third-party code.
   Every figure on every page is read from the live API at runtime; nothing here
   ships a number of its own. */

const ENTITIES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/* Names, descriptions and endpoint URLs are whatever a publisher wrote on
   chain, so every one of them is escaped before it reaches innerHTML. */
function escapeHTML(value) {
  return String(value === null || value === undefined ? "" : value).replace(
    /[&<>"']/g,
    (ch) => ENTITIES[ch],
  );
}

const DASH = "—";

const OUTCOMES = {
  responded: {
    label: "Answered",
    className: "outcome-responded",
    means:
      "A host replied at that URL, at any HTTP status. It proves something is listening there. " +
      "It does not prove the agent behind the URL does anything, or that the reply had anything " +
      "to do with ERC-8004.",
  },
  timeout: {
    label: "Timed out",
    className: "outcome-timeout",
    means:
      "Nothing came back inside the timeout budget, on one attempt at one moment.",
  },
  refused: {
    label: "Refused connection",
    className: "outcome-refused",
    means: "The host refused the connection, on one attempt at one moment.",
  },
  blocked: {
    label: "Not probed (policy)",
    className: "outcome-blocked",
    means:
      "Docket declined to open the connection: a non-HTTP scheme, or a private, loopback or " +
      "CGNAT address. Docket therefore knows nothing about that target. It is not a finding " +
      "against the agent.",
  },
  unresolved: {
    label: "DNS failed",
    className: "outcome-unresolved",
    means:
      "The hostname did not resolve from Docket's network at that moment. It is a fact about " +
      "one lookup, not about whether the agent is reachable for everyone.",
  },
  error: {
    label: "Probe error",
    className: "outcome-error",
    means:
      "The request failed for some other reason; the detail names the exception type.",
  },
};

const RELATIVE_UNITS = [
  ["year", 31536000],
  ["month", 2592000],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/* ------------------------------------------------------------- API access */

/** GET a JSON document from this origin, raising the API's own error.code. */
export async function fetchJSON(path) {
  let resp;
  try {
    resp = await fetch(path, { headers: { accept: "application/json" } });
  } catch (cause) {
    const err = new Error(
      `Could not reach ${path}. Docket may not be running.`,
    );
    err.code = "network_error";
    throw err;
  }
  let body = null;
  try {
    body = await resp.json();
  } catch (cause) {
    body = null;
  }
  if (!resp.ok) {
    const api = body && body.error ? body.error : {};
    const err = new Error(
      api.message || `GET ${path} failed with status ${resp.status}.`,
    );
    err.code = api.code || `http_${resp.status}`;
    err.status = resp.status;
    throw err;
  }
  return body;
}

/* -------------------------------------------------------------- formatting */

export function fmtInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value)))
    return DASH;
  return Number(value).toLocaleString("en-US");
}

export function fmtPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value)))
    return DASH;
  return `${Number(value).toFixed(digits)}%`;
}

export function relativeTime(iso) {
  if (!iso) return "never";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "an unknown time";
  let seconds = Math.round((Date.now() - then) / 1000);
  const ahead = seconds < 0;
  seconds = Math.abs(seconds);
  if (seconds < 45) return "just now";
  for (const [unit, size] of RELATIVE_UNITS) {
    if (seconds >= size) {
      const count = Math.floor(seconds / size);
      const plural = count === 1 ? "" : "s";
      return `${count} ${unit}${plural} ${ahead ? "from now" : "ago"}`;
    }
  }
  return `${seconds} seconds ${ahead ? "from now" : "ago"}`;
}

/** Map the closed outcome vocabulary to what happened, never to what it implies. */
export function outcomeLabel(outcome) {
  if (outcome && Object.prototype.hasOwnProperty.call(OUTCOMES, outcome)) {
    return OUTCOMES[outcome];
  }
  return {
    label: outcome ? String(outcome) : "Not probed",
    className: "outcome-unknown",
    means: "Not one of the six outcomes Docket records.",
  };
}

/* ------------------------------------------------------------------ states */

/** Replace a region with the failure, its code, and a way out. Never a blank page. */
export function renderError(container, err) {
  if (!container) return;
  container.innerHTML = `<div class="panel panel-error" role="alert">
      <p class="error-code">${escapeHTML(err && err.code ? err.code : "request_failed")}</p>
      <p>${escapeHTML(err && err.message ? err.message : "The request failed.")}</p>
      <p class="btn-row"><button type="button" class="btn" data-retry>Try again</button></p>
    </div>`;
  container.querySelector("[data-retry]").addEventListener("click", () => {
    window.location.reload();
  });
}

function fill(name, text, root = document) {
  for (const node of root.querySelectorAll(`[data-field="${name}"]`)) {
    node.textContent = text;
  }
}

function region(name) {
  return document.querySelector(`[data-region="${name}"]`);
}

/* 26 of the 506 agents in snapshot 3 carry a name that is present but is a single
   space. Rendered as-is it becomes an invisible link with no accessible name, so
   the row cannot be reached at all. Docket's own stand-in is said in Docket's own
   words: "Agent #197" would read as a name the publisher chose. */
function displayName(agent) {
  const name = (agent.name || "").trim();
  return name ? name : "(no name)";
}

/* Coverage is the same shape on /stats, /agents and /agents/{id}, so one
   painter serves every page and no page can quote a figure without it. */
function paintCoverage(coverage) {
  const target = region("snapshot");
  if (!target) return;
  const partial = coverage.complete !== true || coverage.dropped > 0;
  const captured = coverage.captured_at;
  target.innerHTML = `<span class="status-dot" data-state="${partial ? "partial" : "complete"}" aria-hidden="true"></span>
    <span>${partial ? "Partial snapshot" : "Complete snapshot"}</span>
    <span><span class="status-key">id</span> <strong class="num">${escapeHTML(coverage.snapshot_id)}</strong></span>
    <span><span class="status-key">captured</span> <strong title="${escapeHTML(captured || "")}">${escapeHTML(relativeTime(captured))}</strong></span>
    <span><span class="status-key">sampled</span> <strong class="num">${escapeHTML(fmtInt(coverage.sampled))} of ${escapeHTML(fmtInt(coverage.expected))}</strong></span>
    <span><span class="status-key">dropped</span> <strong class="num">${escapeHTML(fmtInt(coverage.dropped))}</strong></span>`;

  const banner = region("partial");
  if (!banner) return;
  if (partial) {
    banner.innerHTML = `<div class="notice notice-warn">
        <h3>This snapshot is partial</h3>
        <p>${escapeHTML(fmtInt(coverage.sampled))} of ${escapeHTML(fmtInt(coverage.expected))} expected agents were stored and ${escapeHTML(fmtInt(coverage.dropped))} were dropped. Every count on this page therefore understates its population.</p>
      </div>`;
    banner.hidden = false;
  } else {
    banner.innerHTML = "";
    banner.hidden = true;
  }
}

/* -------------------------------------------------------------------- index */

function paintVocabulary() {
  const target = region("vocabulary");
  if (!target) return;
  target.innerHTML = Object.keys(OUTCOMES)
    .map((key) => {
      const entry = OUTCOMES[key];
      return `<div class="vocab-row">
          <dt><span class="outcome ${entry.className}">${escapeHTML(entry.label)}</span><br><code class="dim">${escapeHTML(key)}</code></dt>
          <dd><p>${escapeHTML(entry.means)}</p></dd>
        </div>`;
    })
    .join("");
}

function paintPublishers(stats) {
  const target = region("publishers");
  if (!target) return;
  const rows = stats.top_publishers
    .map(
      (row) => `<tr>
        <td class="mono">${escapeHTML(row.publisher)}</td>
        <td class="num">${escapeHTML(fmtInt(row.count))}</td>
        <td class="num">${escapeHTML(fmtPct(row.share_pct))}</td>
      </tr>`,
    )
    .join("");
  target.innerHTML = `<div class="table-wrap">
      <table>
        <caption>The five largest publishers in this snapshot, of ${escapeHTML(fmtInt(stats.distinct_publishers))} distinct keys. Share is of the ${escapeHTML(fmtInt(stats.coverage.sampled))} agents sampled.</caption>
        <thead><tr><th scope="col">Publisher key</th><th scope="col" class="num">Agents</th><th scope="col" class="num">Share of snapshot</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function paintStats(stats) {
  const cov = stats.coverage;
  paintCoverage(cov);

  fill("sampled", fmtInt(cov.sampled));
  fill(
    "sampled-note",
    `of ${fmtInt(cov.expected)} the registry said to expect, ${fmtInt(cov.dropped)} dropped`,
  );

  fill("with-feedback", fmtInt(stats.with_feedback));
  fill(
    "with-feedback-note",
    `of ${fmtInt(cov.sampled)} agents in this snapshot`,
  );

  fill("callable", fmtInt(stats.callable_declared));
  fill(
    "callable-note",
    `of ${fmtInt(cov.sampled)} agents. A claim they made, not a probe result`,
  );

  fill("evaluated", fmtInt(stats.endpoints_evaluated));
  fill(
    "evaluated-note",
    `of ${fmtInt(stats.endpoints_resolved)} endpoint rows resolved. Only A2A and MCP are probed, ` +
      `and only ${fmtInt(stats.endpoints_attempted)} had a request issued`,
  );

  fill("responded", fmtInt(stats.endpoints_responded));
  fill(
    "responded-note",
    `${fmtPct(stats.responded_pct_of_attempted, 3)} of the ${fmtInt(stats.endpoints_attempted)} a ` +
      `request reached; ${fmtPct(stats.responded_pct_of_evaluated, 3)} of all ` +
      `${fmtInt(stats.endpoints_evaluated)} evaluated`,
  );

  fill("publishers", fmtInt(stats.distinct_publishers));
  fill(
    "publishers-note",
    `distinct publisher keys across ${fmtInt(cov.sampled)} agents`,
  );

  // Every attempt that was not an answer. Taken from `attempted` rather than from
  // `evaluated`, so the targets no request reached are not folded in as failures.
  const other = stats.endpoints_attempted - stats.endpoints_responded;
  fill("breakdown-evaluated", fmtInt(stats.endpoints_evaluated));
  fill("breakdown-attempted", fmtInt(stats.endpoints_attempted));
  fill("breakdown-responded", fmtInt(stats.endpoints_responded));
  fill("breakdown-blocked", fmtInt(stats.blocked_by_policy));
  fill("breakdown-unresolved", fmtInt(stats.unresolved));
  fill("breakdown-other", fmtInt(other));

  fill("probe-method", stats.probe_method);
  paintPublishers(stats);
}

async function initIndex() {
  paintVocabulary();
  try {
    paintStats(await fetchJSON("/stats"));
  } catch (err) {
    const line = region("snapshot");
    if (line) line.textContent = "Snapshot status unavailable.";
    fill("probe-method", "unavailable while /stats cannot be read.");
    renderError(region("stats"), err);
  }
}

/* ------------------------------------------------------------------ browse */

const BROWSE_LIMIT = 50;
const BOOLEAN_FILTERS = ["has_feedback", "declares_callable", "responded"];
/* Every filter lives in the query string, so a narrowed view is a link someone
   can send and the back button walks the reader's own history. */
let browseState = null;
let browseRequest = 0;

function readFilters() {
  const params = new URLSearchParams(window.location.search);
  const state = { publisher: params.get("publisher") || "" };
  for (const key of BOOLEAN_FILTERS) state[key] = params.get(key) === "true";
  const offset = Number.parseInt(params.get("offset") || "0", 10);
  state.offset = Number.isFinite(offset) && offset > 0 ? offset : 0;
  return state;
}

function filtersToQuery(state) {
  const params = new URLSearchParams();
  for (const key of BOOLEAN_FILTERS) {
    if (state[key]) params.set(key, "true");
  }
  if (state.publisher) params.set("publisher", state.publisher);
  if (state.offset) params.set("offset", String(state.offset));
  return params;
}

function describeFilters(state) {
  const parts = [];
  if (state.has_feedback) parts.push("has at least one feedback record");
  if (state.declares_callable) parts.push("declares an A2A or MCP endpoint");
  if (state.responded) parts.push("had an endpoint answer in this snapshot");
  if (state.publisher) parts.push(`was minted by ${state.publisher}`);
  return parts;
}

function syncControls(state) {
  for (const control of document.querySelectorAll("[data-filter]")) {
    const key = control.dataset.filter;
    if (control.type === "checkbox") control.checked = Boolean(state[key]);
    else control.value = state[key] || "";
  }
}

function stateFromControls() {
  const state = { offset: 0, publisher: "" };
  for (const control of document.querySelectorAll("[data-filter]")) {
    const key = control.dataset.filter;
    state[key] = control.type === "checkbox" ? control.checked : control.value;
  }
  return state;
}

/* The listing carries no observations, so the set of agents whose endpoint
   answered is read from the API's own `responded` filter and joined here. It is
   small by construction — only probed endpoints can be in it. */
async function respondingIds() {
  const ids = new Set();
  let offset = 0;
  for (;;) {
    const page = await fetchJSON(
      `/agents?responded=true&limit=100&offset=${offset}`,
    );
    for (const item of page.items) ids.add(item.agent_id);
    offset += page.items.length;
    if (page.items.length === 0 || offset >= page.total) break;
  }
  return ids;
}

function browseRow(item, responders) {
  const href = `/agent?${new URLSearchParams({ id: item.agent_id }).toString()}`;
  const name = displayName(item);
  const placeholder = item.placeholder_name
    ? ' <span class="badge">name generated by the registry</span>'
    : "";
  const protocols = item.protocols.length
    ? item.protocols
        .map((p) => `<span class="badge">${escapeHTML(p)}</span>`)
        .join("")
    : '<span class="dim">none declared</span>';
  let endpoint;
  if (responders.has(item.agent_id)) {
    endpoint = '<span class="outcome outcome-responded">Answered</span>';
  } else if (item.declares_callable) {
    endpoint =
      '<span class="outcome outcome-unknown">No answer recorded</span>';
  } else {
    endpoint = '<span class="dim">None declared</span>';
  }
  return `<tr>
      <td><a href="${href}">${escapeHTML(name)}</a>${placeholder}</td>
      <td class="num mono">${escapeHTML(item.token_id)}</td>
      <td class="num">${escapeHTML(fmtInt(item.feedback_count))}</td>
      <td>${protocols}</td>
      <td>${endpoint}</td>
      <td class="mono">${escapeHTML(item.publisher)}</td>
    </tr>`;
}

function emptyState(listing, state) {
  const asked = describeFilters(state);
  const because = asked.length
    ? `You asked for agents where every one of these holds: ${asked.join("; ")}.`
    : "";
  return `<div class="panel">
      <h3>Nothing in this snapshot matches</h3>
      <p>${escapeHTML(because)}</p>
      <p>
        Snapshot ${escapeHTML(listing.coverage.snapshot_id)} holds
        ${escapeHTML(fmtInt(listing.coverage.sampled))} agents, and only the few that declare an
        A2A or MCP endpoint were ever probed — so combining the endpoint filters with a publisher
        narrows the population fast.
      </p>
      <p class="btn-row"><button type="button" class="btn" data-action="clear">Clear all filters</button></p>
    </div>`;
}

function paintResults(listing, responders, state) {
  const target = region("results");
  const cov = listing.coverage;
  const shownTo = Math.min(
    listing.offset + listing.items.length,
    listing.total,
  );
  const filterLabel = cov.filter
    ? `Filter <code>${escapeHTML(cov.filter)}</code>.`
    : "No filter: the whole snapshot.";
  const shown = listing.total
    ? `Showing <span class="num">${escapeHTML(fmtInt(listing.offset + 1))}</span> to
       <span class="num">${escapeHTML(fmtInt(shownTo))}</span> of
       <span class="num">${escapeHTML(fmtInt(listing.total))}</span> matching agents`
    : "No agents match";
  const summary = `<p class="section-note">
      ${shown}, inside
      snapshot ${escapeHTML(cov.snapshot_id)} which sampled
      <span class="num">${escapeHTML(fmtInt(cov.sampled))}</span> of
      <span class="num">${escapeHTML(fmtInt(cov.expected))}</span> expected.
      ${filterLabel}
    </p>`;

  if (listing.total === 0) {
    target.innerHTML = summary + emptyState(listing, state);
  } else {
    const prevOff = Math.max(0, listing.offset - BROWSE_LIMIT);
    const nextOff = listing.offset + BROWSE_LIMIT;
    target.innerHTML = `${summary}
      <div class="table-wrap">
        <table>
          <caption>
            "Answered" means a host replied to one GET at that agent's declared endpoint during
            this snapshot. Open an agent for the URL, the status code and the time it was observed.
          </caption>
          <thead>
            <tr>
              <th scope="col">Agent</th>
              <th scope="col" class="num">Token</th>
              <th scope="col" class="num">Feedback</th>
              <th scope="col">Declared protocols</th>
              <th scope="col">Endpoint</th>
              <th scope="col">Publisher</th>
            </tr>
          </thead>
          <tbody>${listing.items.map((item) => browseRow(item, responders)).join("")}</tbody>
        </table>
      </div>
      <p class="btn-row">
        <button type="button" class="btn" data-offset="${prevOff}" ${listing.offset === 0 ? "disabled" : ""}>Previous</button>
        <button type="button" class="btn" data-offset="${nextOff}" ${nextOff >= listing.total ? "disabled" : ""}>Next</button>
      </p>`;
  }

  for (const button of target.querySelectorAll("[data-offset]")) {
    button.addEventListener("click", () => {
      goToBrowse({ ...state, offset: Number(button.dataset.offset) }, true);
    });
  }
  const clear = target.querySelector('[data-action="clear"]');
  if (clear) clear.addEventListener("click", clearFilters);
}

async function loadBrowse(state) {
  const token = ++browseRequest;
  const params = filtersToQuery(state);
  params.set("limit", String(BROWSE_LIMIT));
  try {
    const [listing, responders] = await Promise.all([
      fetchJSON(`/agents?${params.toString()}`),
      respondingIds(),
    ]);
    // A slower earlier request must never repaint over a newer one.
    if (token !== browseRequest) return;
    paintCoverage(listing.coverage);
    paintResults(listing, responders, state);
  } catch (err) {
    if (token !== browseRequest) return;
    const line = region("snapshot");
    if (line) line.textContent = "Snapshot status unavailable.";
    renderError(region("results"), err);
  }
}

function goToBrowse(state, push) {
  browseState = state;
  const query = filtersToQuery(state).toString();
  if (push) {
    window.history.pushState(
      state,
      "",
      query ? `?${query}` : window.location.pathname,
    );
  }
  syncControls(state);
  loadBrowse(state);
}

function clearFilters() {
  goToBrowse(
    {
      has_feedback: false,
      declares_callable: false,
      responded: false,
      publisher: "",
      offset: 0,
    },
    true,
  );
}

async function fillPublisherOptions(selected) {
  const select = document.querySelector('[data-filter="publisher"]');
  if (!select) return;
  let options = "";
  try {
    const stats = await fetchJSON("/stats");
    options = stats.top_publishers
      .map(
        (row) =>
          `<option value="${escapeHTML(row.publisher)}">${escapeHTML(row.publisher)} (${escapeHTML(fmtInt(row.count))})</option>`,
      )
      .join("");
  } catch (err) {
    // The listing does not depend on this, so say the list is missing rather than fail the page.
    options = `<option value="" disabled>Publisher list unavailable: ${escapeHTML(err.code)}</option>`;
  }
  select.innerHTML = `<option value="">All publishers</option>${options}`;
  // A shared link may name a publisher outside the top five; keep it selectable.
  if (
    selected &&
    !Array.from(select.options).some((option) => option.value === selected)
  ) {
    select.insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHTML(selected)}">${escapeHTML(selected)}</option>`,
    );
  }
  select.value = selected || "";
}

async function initBrowse() {
  const state = readFilters();
  browseState = state;
  for (const control of document.querySelectorAll("[data-filter]")) {
    control.addEventListener("change", () =>
      goToBrowse(stateFromControls(), true),
    );
  }
  const clear = document.querySelector('[data-action="clear"]');
  if (clear) clear.addEventListener("click", clearFilters);
  window.addEventListener("popstate", () => goToBrowse(readFilters(), false));
  await fillPublisherOptions(state.publisher);
  goToBrowse(state, false);
}

/* ------------------------------------------------------------ agent detail */

/* A pointer to one agent, not a figure: every number in the note below is read
   from the response. If this agent is not in the served snapshot the note is
   simply not shown. */
const WORKED_EXAMPLE_ID = "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:129";

async function workedExample(currentId) {
  let detail;
  try {
    detail = await fetchJSON(`/agents/${WORKED_EXAMPLE_ID}`);
  } catch (err) {
    // Expected whenever the snapshot does not hold it. Silence is the honest state here.
    return "";
  }
  const answered = detail.observations.find(
    (obs) => obs.outcome === "responded",
  );
  if (!answered) return "";
  const name = displayName(detail);
  const isExplorer = answered.url.includes("8004scan");
  const what = isExplorer
    ? "That URL is the block explorer's own agent-creation page. It is a web page for humans, not an agent endpoint."
    : "Read the URL itself before reading the outcome.";
  const link =
    currentId === WORKED_EXAMPLE_ID
      ? "You are looking at it."
      : `<a href="/agent?${new URLSearchParams({ id: WORKED_EXAMPLE_ID }).toString()}">See the record</a>.`;
  return `<p>
      <strong>Worked example from this snapshot.</strong>
      ${escapeHTML(name)} (token ${escapeHTML(detail.token_id)}) declares
      <code>${escapeHTML(answered.url)}</code> as an endpoint. ${escapeHTML(what)}
      It replied with status ${escapeHTML(answered.status_code)}, so Docket records the outcome as
      "Answered" — which is exactly as much as that word ever claims. ${link}
    </p>`;
}

function observationRows(detail) {
  return detail.observations
    .map((obs) => {
      const outcome = outcomeLabel(obs.outcome);
      return `<tr>
          <td class="url mono">${escapeHTML(obs.url)}</td>
          <td>${escapeHTML(obs.kind)}</td>
          <td><span class="outcome ${outcome.className}">${escapeHTML(outcome.label)}</span></td>
          <td class="num">${obs.status_code === null ? `<span class="dim">${DASH}</span>` : escapeHTML(obs.status_code)}</td>
          <td class="num">${obs.elapsed_ms === null ? `<span class="dim">${DASH}</span>` : escapeHTML(fmtInt(obs.elapsed_ms))}</td>
          <td title="${escapeHTML(obs.observed_at || "")}">${escapeHTML(relativeTime(obs.observed_at))}</td>
          <td>${obs.detail ? escapeHTML(obs.detail) : `<span class="dim">${DASH}</span>`}</td>
        </tr>`;
    })
    .join("");
}

function observationSection(detail) {
  if (detail.observations.length) {
    return `<div class="table-wrap">
        <table>
          <caption>
            Every probe Docket made of this agent's endpoints in snapshot
            ${escapeHTML(detail.coverage.snapshot_id)}. One GET each, one attempt, at the moment
            of the sweep.
          </caption>
          <thead>
            <tr>
              <th scope="col">Endpoint</th>
              <th scope="col">Kind</th>
              <th scope="col">Outcome</th>
              <th scope="col" class="num">Status</th>
              <th scope="col" class="num">Elapsed ms</th>
              <th scope="col">Observed</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>${observationRows(detail)}</tbody>
        </table>
      </div>`;
  }
  let why;
  if (!detail.declares_callable) {
    why =
      "This agent declares no A2A or MCP protocol, and Docket probes nothing else. Nothing was measured here, so there is nothing to report.";
  } else if (!detail.endpoints.length) {
    why =
      "This agent declares a callable protocol, but no endpoint URL could be resolved from its card. There was nothing to send a request to.";
  } else {
    why =
      "This agent's endpoints were not probed in this snapshot. That is a statement about Docket's coverage, not about the agent.";
  }
  return `<div class="panel"><h3>No observations</h3><p class="dim">${escapeHTML(why)}</p></div>`;
}

function paintAgent(detail, example) {
  const name = displayName(detail);
  const placeholder = detail.placeholder_name
    ? '<p><span class="badge">This name was generated by the registry, not chosen by a publisher</span></p>'
    : "";
  const protocols = detail.protocols.length
    ? detail.protocols
        .map((p) => `<span class="badge">${escapeHTML(p)}</span>`)
        .join("")
    : `<span class="dim">none declared</span>`;
  const endpoints = detail.endpoints.length
    ? `<ul>${detail.endpoints.map((url) => `<li class="mono">${escapeHTML(url)}</li>`).join("")}</ul>`
    : `<p class="dim">No endpoint URL resolved from this agent's card.</p>`;
  const cov = detail.coverage;

  region("agent").innerHTML = `<h1>${escapeHTML(name)}</h1>
    ${placeholder}
    <section aria-labelledby="declared-heading">
      <h2 id="declared-heading">What it declares about itself</h2>
      <p class="section-note">Read from the registry and the agent's own card. None of it is a measurement.</p>
      <div class="panel">
        <p>${detail.description ? escapeHTML(detail.description) : '<span class="dim">No description on its card.</span>'}</p>
        <dl class="deflist">
          <dt>Token id</dt><dd class="mono">${escapeHTML(detail.token_id)}</dd>
          <dt>Agent id</dt><dd class="mono">${escapeHTML(detail.agent_id)}</dd>
          <dt>Owner</dt><dd class="mono">${detail.owner_address ? escapeHTML(detail.owner_address) : DASH}</dd>
          <dt>Publisher key</dt><dd class="mono">${escapeHTML(detail.publisher)}</dd>
          <dt>Feedback records</dt><dd class="num">${escapeHTML(fmtInt(detail.feedback_count))}</dd>
          <dt>Declared protocols</dt><dd>${protocols}</dd>
          <dt>Declares x402 payments</dt><dd>${detail.x402 ? "yes" : "no"}</dd>
          <dt>Declared endpoints</dt><dd>${endpoints}</dd>
        </dl>
      </div>
    </section>
    <section aria-labelledby="observed-heading">
      <h2 id="observed-heading">What Docket observed</h2>
      <div class="notice">
        <h3>What an answer does and does not prove</h3>
        <p>
          An endpoint answering proves a host is reachable at that URL and replied. It does not
          prove the agent behind it works, does what its card says, or is the agent it claims to
          be. A 404 counts as an answer, because a 404 still proves the host is up.
        </p>
        ${example}
      </div>
      ${observationSection(detail)}
    </section>
    <section aria-labelledby="coverage-heading">
      <h2 id="coverage-heading">Where this evidence came from</h2>
      <div class="panel">
        <dl class="deflist">
          <dt>Snapshot</dt><dd class="num">${escapeHTML(cov.snapshot_id)}</dd>
          <dt>Captured</dt><dd title="${escapeHTML(cov.captured_at || "")}">${escapeHTML(relativeTime(cov.captured_at))}</dd>
          <dt>Agents sampled</dt><dd class="num">${escapeHTML(fmtInt(cov.sampled))}</dd>
          <dt>Agents expected</dt><dd class="num">${escapeHTML(fmtInt(cov.expected))}</dd>
          <dt>Dropped</dt><dd class="num">${escapeHTML(fmtInt(cov.dropped))}</dd>
          <dt>Complete</dt><dd>${cov.complete ? "yes" : "no"}</dd>
        </dl>
      </div>
    </section>`;
}

async function initAgent() {
  const id = new URLSearchParams(window.location.search).get("id");
  const target = region("agent");
  if (!id) {
    region("snapshot").hidden = true;
    target.innerHTML = `<div class="panel panel-error" role="alert">
        <p class="error-code">no_agent_requested</p>
        <p>This page shows one agent, named by an <code>id</code> in the address. None was given.</p>
        <p class="btn-row"><a class="btn" href="/browse">Pick one from the listing</a></p>
      </div>`;
    return;
  }
  try {
    const detail = await fetchJSON(`/agents/${id}`);
    document.title = `${displayName(detail)} — Docket`;
    paintCoverage(detail.coverage);
    paintAgent(detail, await workedExample(id));
  } catch (err) {
    const line = region("snapshot");
    if (line) line.textContent = "Snapshot status unavailable.";
    renderError(target, err);
  }
}

/* --------------------------------------------------------------- dispatch */

const PAGES = { index: initIndex, browse: initBrowse, agent: initAgent };

const page = document.body.dataset.page;
if (Object.prototype.hasOwnProperty.call(PAGES, page)) {
  PAGES[page]();
}
