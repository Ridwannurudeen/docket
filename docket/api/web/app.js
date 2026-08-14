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

/** POST a JSON document to this origin, raising the API's own error.code.
    Same-origin only: Docket's CORS is GET-only and credential-free, so a cross-origin
    page cannot hire — which is deliberate, and is why this never takes an absolute URL. */
export async function postJSON(path, body) {
  let resp;
  try {
    resp = await fetch(path, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    const err = new Error(
      `Could not reach ${path}. Docket may not be running.`,
    );
    err.code = "network_error";
    throw err;
  }
  let payload = null;
  try {
    payload = await resp.json();
  } catch (cause) {
    payload = null;
  }
  /* A 402 carries the x402 challenge AND the error object in one body. Only the error
     is surfaced here: the allowance is what the reader can act on, and the challenge is
     for a paying client rather than for a page. */
  if (!resp.ok || (payload && payload.error)) {
    const api = payload && payload.error ? payload.error : {};
    const err = new Error(
      api.message || `POST ${path} failed with status ${resp.status}.`,
    );
    err.code = api.code || `http_${resp.status}`;
    err.status = resp.status;
    throw err;
  }
  return payload;
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

/* Which query the snapshot was swept from. A sweep that predated the field recorded
   none, and it is shown as unspecified rather than guessed at — reading a filtered
   slice as "all" is the exact overclaim this field exists to prevent. */
function populationLabel(coverage) {
  return coverage.population || "unspecified";
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
    <span><span class="status-key">dropped</span> <strong class="num">${escapeHTML(fmtInt(coverage.dropped))}</strong></span>
    <span><span class="status-key">population</span> <strong class="mono">${escapeHTML(populationLabel(coverage))}</strong></span>`;

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

/* -------------------------------------------------------------- marketplace */

/* A card is a decision, not the contract. The full description, the limits and the
   evidence live on the service page, so the card carries the opening of the
   description and says outright that it was cut — a summary that hid its own truncation
   is how a caveat disappears. */
function summarise(text, limit = 260) {
  const value = String(text || "").trim();
  if (value.length <= limit) return { text: value, cut: false };
  const cut = value.slice(0, limit);
  const boundary = cut.lastIndexOf(" ");
  return {
    text: `${(boundary > 0 ? cut.slice(0, boundary) : cut).trim()}…`,
    cut: true,
  };
}

function metricLines(metrics) {
  if (!metrics.length) return "";
  /* `display` is the figure with its denominator already inside the string. The page
     never touches the numerator on its own, so no template here can print a share
     stripped of the population it was measured against. */
  return `<ul class="facts">${metrics
    .map(
      (metric) =>
        `<li><span class="fact-key">${escapeHTML(metric.name)}</span>
           <span class="num">${escapeHTML(metric.display)}</span>
           <span class="dim">${escapeHTML(metric.window)}</span></li>`,
    )
    .join("")}</ul>`;
}

function serviceCard(card) {
  const href = `/service?${new URLSearchParams({ id: card.service_id }).toString()}`;
  const summary = summarise(card.what_you_get);
  const more = summary.cut
    ? ` <a href="${href}">Read the whole description</a>.`
    : "";
  /* A binding on chain is not an entry in Docket's index, and on a card the first reads
     as the second. The service page answers it in full — for the one identity Docket's
     own stock has, the answer is that the served snapshot does not hold it. */
  const identity = card.agent_id
    ? `${card.identity} Whether Docket's snapshot holds that agent is stated on the service page.`
    : card.identity;
  return `<div class="service">
      <h4><a href="${href}">${escapeHTML(card.name)}</a></h4>
      <p>${escapeHTML(summary.text)}${more}</p>
      <ul class="facts">
        <li><span class="fact-key">Price</span> <span class="num">${escapeHTML(card.price_display)}</span></li>
        <li><span class="fact-key">Typical run</span> <span class="num">${escapeHTML(fmtInt(card.typical_seconds))} seconds</span></li>
        <li><span class="fact-key">What activating does</span> ${escapeHTML(card.activation_means)}</li>
      </ul>
      ${metricLines(card.metrics)}
      <p class="dim">${escapeHTML(identity)}</p>
      <p class="btn-row"><a class="btn btn-primary" href="${href}">Open and run it</a></p>
    </div>`;
}

function jobPanel(category, cards) {
  const body = cards.length
    ? cards.map(serviceCard).join("")
    : `<p class="dim">${escapeHTML(category.empty)}</p>`;
  return `<section class="panel job" aria-labelledby="job-${escapeHTML(category.category)}">
      <h3 id="job-${escapeHTML(category.category)}">${escapeHTML(category.job)}</h3>
      <p class="dim">${escapeHTML(category.does)}</p>
      <p class="section-note">
        <span class="num">${escapeHTML(fmtInt(category.service_count))}</span>
        ${category.service_count === 1 ? "service" : "services"} here
      </p>
      ${body}
    </section>`;
}

/* The home is category-first, and the categories come from the API rather than from the
   markup: a job label typed into a page is a label that drifts from /categories the
   first time one is reworded. */
async function paintJobs() {
  const jobs = region("jobs");
  const other = region("uncategorised");
  if (!jobs) return;
  let categories;
  let listing;
  try {
    [categories, listing] = await Promise.all([
      fetchJSON("/categories"),
      fetchJSON("/services"),
    ]);
  } catch (err) {
    renderError(jobs, err);
    if (other) other.innerHTML = "";
    return;
  }
  fill("declaration", categories.declaration);
  const byCategory = new Map();
  for (const card of listing.services) {
    if (card.category === null) continue;
    if (!byCategory.has(card.category)) byCategory.set(card.category, []);
    byCategory.get(card.category).push(card);
  }
  jobs.innerHTML = `<div class="jobs">${categories.categories
    .map((category) =>
      jobPanel(category, byCategory.get(category.category) || []),
    )
    .join("")}</div>`;

  if (!other) return;
  const loose = listing.services.filter((card) => card.category === null);
  if (!loose.length) {
    other.innerHTML = "";
    return;
  }
  other.innerHTML = `<p class="section-note">
      These do work that is not one of the four jobs above. They are listed as themselves
      rather than filed under a category they do not belong to, and Docket declares no
      category for them.
    </p>
    <div class="jobs">${loose
      .map((card) => `<div class="panel">${serviceCard(card)}</div>`)
      .join("")}</div>`;
}

/* ---------------------------------------------------------- service detail */

/* The one declared string field that carries newlines is warden-scan's payload — the
   recorded payload in the advantage report is four paragraphs. A single-line input
   cannot hold one, so the reader would silently scan a different text than the one they
   pasted. */
const TEXTAREA_FIELDS = new Set(["payload"]);

function inputControl(name, field) {
  const id = `field-${name}`;
  const required = field.required ? " required" : "";
  const value =
    field.default === undefined || field.default === null
      ? ""
      : escapeHTML(field.default);
  if (TEXTAREA_FIELDS.has(name)) {
    return `<textarea id="${id}" name="${escapeHTML(name)}" rows="6"${required}></textarea>`;
  }
  const type = field.type === "integer" ? "number" : "text";
  return `<input id="${id}" name="${escapeHTML(name)}" type="${type}" value="${value}"${required} />`;
}

function activationForm(record) {
  const fields = Object.entries(record.input_schema);
  const controls = fields.length
    ? fields
        .map(
          ([name, field]) => `<div class="field">
            <label for="field-${escapeHTML(name)}">
              ${escapeHTML(name)}${field.required ? "" : " (optional)"}
            </label>
            ${inputControl(name, field)}
            <p class="dim">${escapeHTML(field.description || "")}</p>
          </div>`,
        )
        .join("")
    : `<p class="dim">This service takes no arguments: what arrives is whatever was last
         published, so there is nothing for you to supply.</p>`;
  return `<form class="activate" data-activate novalidate>
      ${controls}
      <p class="btn-row">
        <button type="submit" class="btn btn-primary" data-run>Run it now</button>
        <span class="dim">
          Typical run ${escapeHTML(fmtInt(record.typical_seconds))} seconds. One attempt, and the
          result is whatever it returns.
        </span>
      </p>
      <p class="dim">
        No account, key or wallet is needed. Docket verifies payment authorizations and does not
        settle them, so nothing here moves any funds; the receipt states which tier served the
        run. Where a payment recipient is configured, a caller has an allowance of 20 hires an
        hour and the response says so when it is spent.
      </p>
    </form>`;
}

function paintServiceRecord(record) {
  const category = record.category_job
    ? `<p><span class="badge">${escapeHTML(record.category_job)}</span>
         <span class="dim">— Docket's own declaration about a service Docket runs, not a
         property read from chain</span></p>`
    : `<p><span class="badge">Not one of the four job categories</span>
         <span class="dim">— this does work outside them, and Docket will not file it under
         a job it does not do</span></p>`;
  const identity = record.agent_path
    ? `<p>${escapeHTML(record.identity)} <a href="${escapeHTML(record.agent_path)}">Read what Docket observed of it</a>.</p>
       <p class="dim">${escapeHTML(record.identity_note)}</p>`
    : `<p>${escapeHTML(record.identity)}</p>
       <p class="dim">${escapeHTML(record.identity_note)}</p>`;
  const evidence = record.evidence.length
    ? `<ul class="facts">${record.evidence
        .map(
          (ref) =>
            `<li><a href="${escapeHTML(ref.url)}">${escapeHTML(ref.label)}</a></li>`,
        )
        .join("")}</ul>`
    : `<p class="dim">No recorded run is published for this service yet.</p>`;

  region("service").innerHTML = `<h1>${escapeHTML(record.name)}</h1>
    ${category}
    <p class="lede">${escapeHTML(record.what_you_get)}</p>
    <div class="panel">
      <dl class="deflist">
        <dt>Price</dt><dd class="num">${escapeHTML(record.price_display)} (${escapeHTML(record.price_atomic)} atomic units of <span class="mono">${escapeHTML(record.asset)}</span>)</dd>
        <dt>Typical run</dt><dd class="num">${escapeHTML(fmtInt(record.typical_seconds))} seconds</dd>
        <dt>What activating does</dt><dd>${escapeHTML(record.activation_means)}</dd>
        <dt>How an agent calls it</dt><dd class="mono">${escapeHTML(record.hire_method)} ${escapeHTML(record.hire_path)}</dd>
      </dl>
    </div>
    <section aria-labelledby="observed-heading">
      <h2 id="observed-heading">What has been observed of it</h2>
      <p class="section-note">
        Single observations from recorded runs, not averages. Each figure carries the population
        it was measured against and the record it came from.
      </p>
      <div class="panel">
        ${metricLines(record.metrics) || '<p class="dim">Nothing has been recorded for this service yet.</p>'}
        ${record.metrics
          .map(
            (metric) =>
              `<p class="dim"><strong>${escapeHTML(metric.name)}:</strong> ${escapeHTML(metric.method)}, observed ${escapeHTML(metric.observed_at)}.</p>`,
          )
          .join("")}
      </div>
    </section>
    <section aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">The record behind it</h2>
      <div class="panel">${evidence}</div>
    </section>
    <section aria-labelledby="limits-heading">
      <h2 id="limits-heading">What it cannot do</h2>
      <div class="notice notice-warn">
        <p>${escapeHTML(record.limitations)}</p>
      </div>
    </section>
    <section aria-labelledby="identity-heading">
      <h2 id="identity-heading">Its identity on chain</h2>
      <div class="panel">${identity}</div>
    </section>`;
}

/* A failure of the run itself, rendered where the result would have gone. Deliberately
   not `renderError`: that one offers a reload, and reloading would throw away what the
   reader typed into the form. */
function paintRunFailure(container, err) {
  container.innerHTML = `<div class="panel panel-error" role="alert">
      <p class="error-code">${escapeHTML(err && err.code ? err.code : "request_failed")}</p>
      <p>${escapeHTML(err && err.message ? err.message : "The run failed.")}</p>
      <p class="dim">Nothing was charged for a request Docket could not read. Your input is still
        in the form above.</p>
    </div>`;
}

function readForm(record, form) {
  const body = {};
  for (const [name, field] of Object.entries(record.input_schema)) {
    const control = form.elements.namedItem(name);
    if (!control) continue;
    const raw = control.value.trim();
    /* An omitted optional field is omitted, never sent as "" or 0: the service reads
       `limit` explicitly so that an explicit 0 stays 0, and a blank sent as one would
       turn "use the default" into "read nothing". */
    if (!raw && !field.required) continue;
    body[name] = field.type === "integer" ? Number.parseInt(raw, 10) : raw;
  }
  return body;
}

/* A buyer paid for an answer, not for a payload. Dumping the response into a <pre> made
   every service look identical and left the reader to do the interpreting they had just
   paid to have done — and it hid the one thing that matters most when a scan finds
   nothing, which is why it found nothing. A presenter states the finding first and keeps
   the raw JSON one click away, never instead of it: the evidence is still the point, it
   just stops being the only thing offered. Services with no presenter yet fall back to the
   payload, so an unpresented service reads as unpolished rather than broken. */
const PRESENTERS = { "range-doctor": presentRangeDoctor };

function presentResult(record, result) {
  const presenter = PRESENTERS[record.id];
  const raw = `<details class="raw">
      <summary>The full response, exactly as the service returned it</summary>
      <pre>${escapeHTML(JSON.stringify(result, null, 2))}</pre>
    </details>`;
  if (!presenter)
    return `<pre>${escapeHTML(JSON.stringify(result, null, 2))}</pre>`;
  return presenter(result) + raw;
}

function pct(value) {
  return value === null || value === undefined
    ? null
    : `${(value * 100).toFixed(2)}%`;
}

function presentRangeDoctor(result) {
  const positions = result.positions || [];
  /* The coverage sentence leads whatever else is here. When the list is empty it is the
     entire answer, and an empty list with nothing above it is the failure this presenter
     exists to prevent: a reader who sees no positions and no sentence concludes theirs are
     fine. */
  const coverage = result.coverage
    ? `<p class="lede">${escapeHTML(result.coverage)}</p>`
    : "";

  if (!positions.length) {
    return `<section aria-labelledby="result-heading">
        <h3 id="result-heading">What came back</h3>
        ${coverage}
        <p class="dim">Nothing was diagnosed because there was no open position to diagnose.
          That is an answer about this wallet, not a failure of the read — and it is not a
          statement that the wallet is healthy, only that it holds nothing in a pool at the
          moment it was read.${
            result.scan_complete === false
              ? " The read was also bounded, so the positions it did not reach are unknown rather than absent — raise the limit to look further."
              : ""
          }</p>
      </section>`;
  }

  const cards = positions
    .map((entry) => {
      const p = entry.position || {};
      const d = entry.diagnosis || {};
      const pool = entry.pool || {};
      const apr = pct(d.pool_net_apr);
      const where = pct(d.range_position_pct);
      const findings = (d.findings || [])
        .map((f) => `<li>${escapeHTML(f)}</li>`)
        .join("");
      const actions = (d.actions || [])
        .map(
          (a) =>
            `<li>${escapeHTML(a.text)}${
              a.link
                ? ` <a href="${escapeHTML(a.link)}" rel="noopener">open it on PancakeSwap</a>`
                : ""
            }</li>`,
        )
        .join("");
      return `<article class="panel">
          <h4>Position ${escapeHTML(String(p.token_id))} — ${escapeHTML(STATUS_WORDS[d.status] || d.status)}</h4>
          <dl class="deflist">
            <dt>Range</dt><dd class="mono">ticks ${escapeHTML(String(p.tick_lower))} to ${escapeHTML(String(p.tick_upper))}${
              pool.tick === null || pool.tick === undefined
                ? ""
                : `, pool now at ${escapeHTML(String(pool.tick))}`
            }${where ? ` (${escapeHTML(where)} through it)` : ""}</dd>
            <dt>Pool's net fee rate</dt><dd>${
              apr
                ? `${escapeHTML(apr)} — one day's fees after the protocol's cut, annualised. An observation, not a forecast.`
                : "not quoted for this position, for the reason given below"
            }</dd>
            <dt>Held</dt><dd>${p.staked ? "staked in a farm" : "directly in the wallet"}</dd>
            <dt>Read at block</dt><dd class="mono">${escapeHTML(String(d.as_of_block))}</dd>
          </dl>
          ${findings ? `<p class="status-key">What this means</p><ul>${findings}</ul>` : ""}
          ${actions ? `<p class="status-key">What you could do, and what it costs</p><ul>${actions}</ul>` : ""}
        </article>`;
    })
    .join("");

  return `<section aria-labelledby="result-heading">
      <h3 id="result-heading">What came back</h3>
      ${coverage}
      ${cards}
      <p class="dim">Every figure above was computed from numbers this response carries, so
        you can check it against the chain yourself. Nothing was signed, approved or moved.</p>
    </section>`;
}

const STATUS_WORDS = {
  in_range: "earning fees",
  out_of_range_above: "above its range, earning nothing",
  out_of_range_below: "below its range, earning nothing",
  closed: "closed, holding nothing",
  unknown_pool: "its pool could not be read",
};

function paintOutcome(record, answer) {
  const receipt = answer.receipt || {};
  const payment = receipt.payment || {};
  const rejected = payment.authorization_rejected
    ? `<dt>Authorization</dt><dd>not accepted: ${escapeHTML(payment.authorization_rejected)}</dd>`
    : "";
  region("outcome").innerHTML = `${presentResult(record, answer.result)}
    <section aria-labelledby="receipt-heading">
      <h3 id="receipt-heading">The receipt</h3>
      <div class="panel">
        <dl class="deflist">
          <dt>Service</dt><dd class="mono">${escapeHTML(receipt.service)}</dd>
          <dt>Delivered at</dt><dd>${escapeHTML(receipt.delivered_at)}</dd>
          <dt>Input hash</dt><dd class="mono">${escapeHTML(receipt.input_hash)}</dd>
          <dt>Output hash</dt><dd class="mono">${escapeHTML(receipt.output_hash)}</dd>
          <dt>Payment</dt><dd class="mono">${escapeHTML(payment.status)}</dd>
          ${rejected}
        </dl>
        <p class="dim">
          A receipt records delivery and nothing else. It does not assert the work is correct,
          and Docket does not sign it — it is a self-check for you. Both hashes are plain
          SHA-256 over canonical JSON and need none of Docket's code to recompute;
          <a href="/llms.txt">/llms.txt</a> carries the exact recipe. A payment status of
          <span class="mono">verified_unsettled</span> means a signature was checked and
          nothing was settled, broadcast or moved.
        </p>
      </div>
    </section>`;
}

function wireActivation(record) {
  const target = region("activate");
  if (!target) return;
  target.innerHTML = activationForm(record);
  const form = target.querySelector("[data-activate]");
  const button = form.querySelector("[data-run]");
  const outcome = region("outcome");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const missing = Object.entries(record.input_schema)
      .filter(([name, field]) => {
        const control = form.elements.namedItem(name);
        return field.required && control && !control.value.trim();
      })
      .map(([name]) => name);
    if (missing.length) {
      paintRunFailure(outcome, {
        code: "missing_field",
        message: `${record.service_id} needs ${missing.join(", ")}.`,
      });
      return;
    }
    button.disabled = true;
    outcome.innerHTML = `<div class="notice" role="status">
        <p>Running ${escapeHTML(record.name)}. It usually takes about
        ${escapeHTML(fmtInt(record.typical_seconds))} seconds, and this is one attempt.</p>
      </div>`;
    try {
      paintOutcome(
        record,
        await postJSON(record.hire_path, readForm(record, form)),
      );
    } catch (err) {
      paintRunFailure(outcome, err);
    } finally {
      button.disabled = false;
    }
  });
}

async function initService() {
  const id = new URLSearchParams(window.location.search).get("id");
  const target = region("service");
  const activate = region("activate");
  if (!id) {
    activate.innerHTML = "";
    target.innerHTML = `<div class="panel panel-error" role="alert">
        <p class="error-code">no_service_requested</p>
        <p>This page shows one service, named by an <code>id</code> in the address. None was
          given.</p>
        <p class="btn-row"><a class="btn" href="/">Pick one from the services</a></p>
      </div>`;
    return;
  }
  try {
    const record = await fetchJSON(`/services/${encodeURIComponent(id)}`);
    document.title = `${record.name} — Docket`;
    paintServiceRecord(record);
    wireActivation(record);
  } catch (err) {
    activate.innerHTML = "";
    renderError(target, err);
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

function paintNameFamilies(stats) {
  const target = region("families");
  if (!target) return;
  const rows = stats.top_name_families
    .map(
      (row) => `<tr>
        <td class="mono">${escapeHTML(row.name_family)}</td>
        <td class="num">${escapeHTML(fmtInt(row.count))}</td>
        <td class="num">${escapeHTML(fmtPct(row.share_pct))}</td>
      </tr>`,
    )
    .join("");
  target.innerHTML = `<div class="table-wrap">
      <table>
        <caption>The five largest name families in this snapshot, of ${escapeHTML(fmtInt(stats.distinct_name_families))} distinct keys. Share is of the ${escapeHTML(fmtInt(stats.coverage.sampled))} agents sampled. Grouped by the first word of a name each agent chose for itself, so it is not a record of who deployed them.</caption>
        <thead><tr><th scope="col">Name family</th><th scope="col" class="num">Agents</th><th scope="col" class="num">Share of snapshot</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

/* "sampled 506 of 506, complete" is true and reads as a census of the chain. It is
   completeness against the query the sweep ran, and that query left most of BNB Smart
   Chain out. Both halves of this sentence come from the API — the filter the snapshot
   recorded and the largest total any sweep measured — so neither can go stale in the
   markup. Where no wider sweep exists there is nothing to compare against, and the
   comparison is left unsaid rather than invented. */
function paintSlice(stats) {
  const target = region("slice");
  if (!target) return;
  const cov = stats.coverage;
  /* What was swept decides whether this is a slice at all. A sweep that recorded
     population "all" IS the registry as it found it, and telling it otherwise from an
     arithmetic accident would be this stage's own bug pointed the other way. */
  const census = cov.population === "all";
  const swept = census
    ? "the whole registry"
    : cov.population === null
      ? "a query it did not record"
      : `the query <code>${escapeHTML(populationLabel(cov))}</code>`;
  const unrecorded =
    cov.population === null
      ? ` Which query is not stored on that snapshot, and Docket does not backfill one a sweep
         never recorded — it shows as unspecified rather than as "all".`
      : "";
  /* Whether a scale FIGURE exists is a separate question from whether this is a slice, so
     registry_total gates the number and never the claim. */
  const wider =
    stats.registry_total !== null && stats.registry_total > cov.expected;
  let scale;
  if (census) {
    scale = ` That query was the whole registry, so "complete" above is completeness against
       this chain as that sweep found it, rather than against a slice of it.`;
  } else if (wider) {
    scale = ` That query is a filtered slice: at least
       <strong class="num">${escapeHTML(fmtInt(stats.registry_total))}</strong> agents were
       registered when a sweep here last measured this chain — a lower bound, not a count of
       it — so "complete" above means complete for the slice and is not a census.`;
  } else {
    scale = ` No wider sweep of this chain has been recorded here, so there is no measured
       figure to read this against — "complete" above is completeness against that query
       alone, and how much of the chain the query covered is not something Docket has
       measured.`;
  }
  target.innerHTML = `<div class="notice">
      <h3>${census ? "What this snapshot covers" : "What this snapshot is a slice of"}</h3>
      <p>
        Snapshot ${escapeHTML(cov.snapshot_id)} swept ${swept}, and stored
        <strong class="num">${escapeHTML(fmtInt(cov.sampled))}</strong> of the
        <strong class="num">${escapeHTML(fmtInt(cov.expected))}</strong> agents that query
        returned.${scale}${unrecorded}
      </p>
    </div>`;
}

function paintStats(stats) {
  const cov = stats.coverage;
  paintCoverage(cov);
  paintSlice(stats);

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
      `request was issued to; ${fmtPct(stats.responded_pct_of_evaluated, 3)} of all ` +
      `${fmtInt(stats.endpoints_evaluated)} evaluated`,
  );

  fill("families", fmtInt(stats.distinct_name_families));
  fill(
    "families-note",
    `distinct first-word name keys across ${fmtInt(cov.sampled)} agents`,
  );

  // Every attempt that was not an answer. Taken from `attempted` rather than from
  // `evaluated`, so the targets no request was issued to are not folded in as failures.
  const other = stats.endpoints_attempted - stats.endpoints_responded;
  fill("breakdown-evaluated", fmtInt(stats.endpoints_evaluated));
  fill("breakdown-attempted", fmtInt(stats.endpoints_attempted));
  fill("breakdown-responded", fmtInt(stats.endpoints_responded));
  fill("breakdown-blocked", fmtInt(stats.blocked_by_policy));
  fill("breakdown-unresolved", fmtInt(stats.unresolved));
  fill("breakdown-other", fmtInt(other));

  fill("probe-method", stats.probe_method);
  paintNameFamilies(stats);
}

async function initIndex() {
  paintVocabulary();
  /* The jobs first, and awaited separately: a /stats that cannot be read must not leave
     the shop front empty, and an empty shelf must not be hidden by a failing statistic. */
  await paintJobs();
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
  const state = { name_family: params.get("name_family") || "" };
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
  if (state.name_family) params.set("name_family", state.name_family);
  if (state.offset) params.set("offset", String(state.offset));
  return params;
}

function describeFilters(state) {
  const parts = [];
  if (state.has_feedback) parts.push("has at least one feedback record");
  if (state.declares_callable) parts.push("declares an A2A or MCP endpoint");
  if (state.responded) parts.push("had an endpoint answer in this snapshot");
  if (state.name_family)
    parts.push(`carries the name family ${state.name_family}`);
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
  const state = { offset: 0, name_family: "" };
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
      <td class="mono">${escapeHTML(item.name_family)}</td>
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
        A2A or MCP endpoint were ever probed — so combining the endpoint filters with a name
        family narrows the population fast.
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
              <th scope="col">Name family</th>
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
      name_family: "",
      offset: 0,
    },
    true,
  );
}

async function fillNameFamilyOptions(selected) {
  const select = document.querySelector('[data-filter="name_family"]');
  if (!select) return;
  let options = "";
  try {
    const stats = await fetchJSON("/stats");
    options = stats.top_name_families
      .map(
        (row) =>
          `<option value="${escapeHTML(row.name_family)}">${escapeHTML(row.name_family)} (${escapeHTML(fmtInt(row.count))})</option>`,
      )
      .join("");
  } catch (err) {
    // The listing does not depend on this, so say the list is missing rather than fail the page.
    options = `<option value="" disabled>Name family list unavailable: ${escapeHTML(err.code)}</option>`;
  }
  select.innerHTML = `<option value="">All name families</option>${options}`;
  // A shared link may name a family outside the top five; keep it selectable.
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
  await fillNameFamilyOptions(state.name_family);
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
          <dt>Name family</dt><dd class="mono">${escapeHTML(detail.name_family)}</dd>
          <dd class="dim">The first word of the name this agent declared. Not a record of who minted it.</dd>
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
          <dt>Population swept</dt><dd class="mono">${escapeHTML(populationLabel(cov))}</dd>
          <dt>Agents sampled</dt><dd class="num">${escapeHTML(fmtInt(cov.sampled))}</dd>
          <dt>Agents expected</dt><dd class="num">${escapeHTML(fmtInt(cov.expected))}</dd>
          <dt>Dropped</dt><dd class="num">${escapeHTML(fmtInt(cov.dropped))}</dd>
          <dt>Complete</dt><dd>${cov.complete ? "yes" : "no"} — against the population above, not the registry</dd>
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
        <p class="btn-row"><a class="btn" href="/research">Pick one from the listing</a></p>
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

/* The page key follows the route; the functions follow what they do. /research serves
   the registry browser that used to be at /browse, and browsing is still what it does. */
const PAGES = {
  index: initIndex,
  research: initBrowse,
  agent: initAgent,
  service: initService,
};

const page = document.body.dataset.page;
if (Object.prototype.hasOwnProperty.call(PAGES, page)) {
  PAGES[page]();
}
