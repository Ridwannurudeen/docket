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

  fill("probed", fmtInt(stats.endpoints_probed));
  fill(
    "probed-note",
    `of ${fmtInt(stats.endpoints_resolved)} endpoint rows resolved. Only A2A and MCP are probed`,
  );

  fill("responded", fmtInt(stats.endpoints_responded));
  fill(
    "responded-note",
    `${fmtPct(stats.responded_pct_of_probed, 3)} of the ${fmtInt(stats.endpoints_probed)} probed`,
  );

  fill("publishers", fmtInt(stats.distinct_publishers));
  fill(
    "publishers-note",
    `distinct publisher keys across ${fmtInt(cov.sampled)} agents`,
  );

  const other =
    stats.endpoints_probed -
    stats.endpoints_responded -
    stats.blocked_by_policy -
    stats.unresolved;
  fill("breakdown-probed", fmtInt(stats.endpoints_probed));
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

/* --------------------------------------------------------------- dispatch */

const PAGES = { index: initIndex };

const page = document.body.dataset.page;
if (Object.prototype.hasOwnProperty.call(PAGES, page)) {
  PAGES[page]();
}
