/* Docket web UI. One authored ES module, no build step, no third-party code.
   Every figure rendered by this module is read from the live API at runtime;
   nothing here ships a number of its own. */

const ENTITIES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/* Names, descriptions and endpoint URLs are whatever a publisher wrote on
   chain, so every one of them is escaped before it reaches innerHTML. */
export function escapeHTML(value) {
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
    Browser calls stay same-origin: mutation routes require application/json and Docket's
    GET-only CORS denies their preflight. CLI and server callers remain supported. */
export async function postJSON(path, body) {
  let resp;
  try {
    resp = await fetch(path, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
      },
      body: encodeJSON(body),
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

/** Encode request bodies without routing integers through JavaScript's lossy Number type. */
export function encodeJSON(value) {
  if (typeof value === "bigint") return value.toString();
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value))
      throw new TypeError("JSON numbers must be finite.");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => encodeJSON(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const fields = Object.entries(value)
      .filter(([, item]) => item !== undefined)
      .map(([key, item]) => `${JSON.stringify(key)}:${encodeJSON(item)}`);
    return `{${fields.join(",")}}`;
  }
  throw new TypeError(`Cannot encode ${typeof value} as JSON.`);
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

export function displayTimestamp(value) {
  if (!value) return DASH;
  if (!String(value).includes("T")) return String(value);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed
    .toISOString()
    .replace("T", " ")
    .replace(/\.\d{3}Z$/, " UTC");
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
export function renderError(container, err, heading = "") {
  if (!container) return;
  container.innerHTML = `<div class="panel panel-error" role="alert">
      ${heading ? `<h1>${escapeHTML(heading)}</h1>` : ""}
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
  const incomplete = coverage.complete !== true || coverage.dropped > 0;
  const ageSeconds = Number(coverage.snapshot_age_seconds);
  const ageUnavailable =
    coverage.snapshot_age_seconds === null || !Number.isFinite(ageSeconds);
  const ageDays = ageUnavailable ? null : ageSeconds / 86400;
  const stale = ageDays !== null && ageDays >= 7;
  const status = incomplete
    ? "Partial snapshot"
    : ageUnavailable
      ? "Snapshot freshness unavailable"
      : stale
        ? "Stale snapshot"
        : "Complete snapshot";
  const age = ageDays === null ? "unavailable" : `${ageDays.toFixed(1)} days`;
  const captured = coverage.captured_at;
  target.innerHTML = `<span class="status-dot" data-state="${incomplete || stale || ageUnavailable ? "partial" : "complete"}" aria-hidden="true"></span>
    <span>${status}</span>
    <span><span class="status-key">id</span> <strong class="num">${escapeHTML(coverage.snapshot_id)}</strong></span>
    <span><span class="status-key">captured</span> <strong title="${escapeHTML(captured || "")}">${escapeHTML(relativeTime(captured))}</strong></span>
    <span><span class="status-key">age</span> <strong class="num">${escapeHTML(age)}</strong></span>
    <span><span class="status-key">sampled</span> <strong class="num">${escapeHTML(fmtInt(coverage.sampled))} of ${escapeHTML(fmtInt(coverage.expected))}</strong></span>
    <span><span class="status-key">dropped</span> <strong class="num">${escapeHTML(fmtInt(coverage.dropped))}</strong></span>
    <span><span class="status-key">population</span> <strong class="mono">${escapeHTML(populationLabel(coverage))}</strong></span>`;

  const banner = region("partial");
  if (!banner) return;
  if (incomplete || stale || ageUnavailable) {
    const completeness = incomplete
      ? `${escapeHTML(fmtInt(coverage.sampled))} of ${escapeHTML(fmtInt(coverage.expected))} expected agents were stored and ${escapeHTML(fmtInt(coverage.dropped))} were dropped. Every count on this page therefore understates its population.`
      : "All agents returned by this snapshot's query were stored.";
    const freshness = ageUnavailable
      ? "Its age is unavailable, so this page does not present it as current."
      : stale
        ? `This snapshot is ${escapeHTML(age)} old, at or beyond the seven-day freshness boundary.`
        : `Its age is ${escapeHTML(age)}.`;
    const heading = incomplete
      ? stale || ageUnavailable
        ? "This snapshot is partial and its freshness needs attention"
        : "This snapshot is partial"
      : ageUnavailable
        ? "This snapshot's freshness is unavailable"
        : "This snapshot is stale";
    banner.innerHTML = `<div class="notice notice-warn">
        <p class="notice-heading">${heading}</p>
        <p>${completeness} ${freshness}</p>
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
  if (!metrics.length) return `<p class="metric-note">No run recorded yet.</p>`;
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
     as the second. The service page answers it in full, including whether the served
     snapshot holds the identity. */
  const identity = card.agent_id
    ? `${card.identity} Whether Docket's snapshot holds that agent is stated on the service page.`
    : card.identity;
  const action = card.paid_stock
    ? `Pay ${escapeHTML(card.price_display)} and hire`
    : "Run it free";
  const admission = card.paid_stock
    ? ""
    : `<details class="admission">
        <summary>Why this isn't for sale yet</summary>
        <ul class="facts">
          <li><span class="fact-key">Price after admission</span> <span class="num">${escapeHTML(card.price_display)}</span></li>
          <li><span class="fact-key">Paid-stock status</span> ${escapeHTML(card.stock_status)}</li>
        </ul>
      </details>`;
  return `<div class="service">
      <h4><a href="${href}">${escapeHTML(card.name)}</a></h4>
      <p>${escapeHTML(summary.text)}${more}</p>
      <ul class="facts">
        ${card.paid_stock ? `<li><span class="fact-key">Price</span> <span class="num">${escapeHTML(card.price_display)}</span></li>` : ""}
        <li><span class="fact-key">Typical run, declared</span> <span class="num">${escapeHTML(fmtInt(card.typical_seconds))} seconds</span></li>
        <li><span class="fact-key">Evidence modality</span> ${escapeHTML(card.evidence_modality.replaceAll("_", " "))}</li>
        <li><span class="fact-key">What activating does</span> ${escapeHTML(card.activation_means)}</li>
      </ul>
      ${metricLines(card.metrics)}
      <p class="dim">${escapeHTML(identity)}</p>
      <p class="btn-row"><a class="btn btn-primary" href="${href}">${action}</a></p>
      ${admission}
    </div>`;
}

/* ---------------------------------------------------------- service detail */

/* The one declared string field that carries newlines is warden-scan's payload — the
   recorded payload in the advantage report is four paragraphs. A single-line input
   cannot hold one, so the reader would silently scan a different text than the one they
   pasted. */
const TEXTAREA_FIELDS = new Set(["payload"]);

function arrayItemControl(name, value, index) {
  return `<div data-array-item>
      <input id="field-${escapeHTML(name)}${index === 0 ? "" : `-${index}`}" name="${escapeHTML(name)}" type="number"
        step="1" value="${escapeHTML(value)}" aria-label="${escapeHTML(name)} item ${index + 1}" />
      <button type="button" class="btn" data-array-remove>Remove</button>
    </div>`;
}

export function inputControl(name, field) {
  const id = `field-${name}`;
  const required = field.required ? " required" : "";
  const value =
    field.default === undefined || field.default === null
      ? ""
      : escapeHTML(field.default);
  if (TEXTAREA_FIELDS.has(name)) {
    return `<textarea id="${id}" name="${escapeHTML(name)}" rows="6"${required}></textarea>`;
  }
  if (field.type === "array") {
    const values =
      Array.isArray(field.default) && field.default.length
        ? field.default
        : [""];
    return `<div id="${id}-array" data-array-control="${escapeHTML(name)}" data-next-index="${values.length}">
        <div data-array-items>
          ${values.map((item, index) => arrayItemControl(name, item, index)).join("")}
        </div>
        <button type="button" class="btn" data-array-add>Add ${escapeHTML(name)} item</button>
      </div>`;
  }
  const numeric = field.type === "integer" || field.type === "number";
  const type = numeric ? "number" : "text";
  const step =
    field.type === "number" ? ' step="any"' : numeric ? ' step="1"' : "";
  return `<input id="${id}" name="${escapeHTML(name)}" type="${type}" value="${value}"${step}${required} />`;
}

function activationForm(record) {
  const fields = Object.entries(record.input_schema);
  const fieldMarkup = ([name, field]) => `<div class="field">
            <label for="field-${escapeHTML(name)}">
              ${escapeHTML(name)}${field.required ? "" : " (optional)"}
            </label>
            ${inputControl(name, field)}
            <p class="dim">${escapeHTML(field.description || "")}</p>
            ${field.example_note ? `<p class="example-note">${escapeHTML(field.example_note)}</p>` : ""}
          </div>`;
  const regular = fields.filter(([, field]) => field.advanced !== true);
  const advanced = fields.filter(([, field]) => field.advanced === true);
  const controls = regular.length
    ? regular.map(fieldMarkup).join("")
    : `<p class="dim">This service takes no arguments: what arrives is whatever was last
         published, so there is nothing for you to supply.</p>`;
  const reproducibility = advanced.length
    ? `<details class="advanced">
        <summary>Advanced — reproducibility</summary>
        <div class="advanced-fields">${advanced.map(fieldMarkup).join("")}</div>
      </details>`
    : "";
  const hasWorkedExample = fields.some(([, field]) =>
    Boolean(field.example_note),
  );
  const runLabel = record.paid_stock ? "Run a free preview" : "Run it free";
  const availability = record.paid_stock
    ? `<p class="section-note">This service has passed all four paid-stock gates. Agents can submit its exact x402
       authorization to <span class="mono">${escapeHTML(record.hire_path)}</span>; this page
       runs only the free preview because it holds no signing key.</p>`
    : `<section class="admission-info" aria-labelledby="admission-heading">
        <h3 id="admission-heading">Why this isn't for sale yet</h3>
        <p>This service is <strong>not admitted to paid stock</strong>. Its status is
          <span class="mono">${escapeHTML(record.stock_status)}</span>, so this form runs it
          free and does not use a payment authorization.</p>
        <dl class="deflist">
          <dt>Price after admission</dt><dd class="num">${escapeHTML(record.price_display)}</dd>
          <dt>Paid-stock status</dt><dd>${escapeHTML(record.stock_status)}</dd>
        </dl>
      </section>`;
  return `<form class="activate" data-activate novalidate>
      ${controls}
      ${reproducibility}
      <p class="btn-row">
        <button type="submit" class="btn btn-primary" data-run>${runLabel}</button>
        ${hasWorkedExample ? '<button type="submit" class="btn" data-example>Try the worked example</button>' : ""}
        <span class="dim">
          Typical run ${escapeHTML(fmtInt(record.typical_seconds))} seconds. One attempt, and the
          result is whatever it returns.
        </span>
      </p>
    </form>
    ${availability}`;
}

function paintServiceRecord(record) {
  const primaryMetric = record.metrics[0];
  const finding = primaryMetric
    ? `<strong class="num">${escapeHTML(primaryMetric.display)}</strong> — ${escapeHTML(primaryMetric.name.toLowerCase())}, bounded to ${escapeHTML(primaryMetric.window)}.`
    : "<strong>0 recorded measurements.</strong> No run is represented on this page.";
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
    <p class="lede">${finding}</p>
    ${category}
    <section aria-labelledby="service-offer-heading">
      <h2 id="service-offer-heading">What arrives</h2>
      <p>${escapeHTML(record.what_you_get)}</p>
    </section>
    <div class="panel">
      <dl class="deflist">
        ${record.paid_stock ? `<dt>Price</dt><dd class="num">${escapeHTML(record.price_display)} (${escapeHTML(record.price_atomic)} atomic units of <span class="mono">${escapeHTML(record.asset)}</span>)</dd>` : ""}
        <dt>Typical run, declared</dt><dd class="num">${escapeHTML(fmtInt(record.typical_seconds))} seconds</dd>
        <dt>Evidence modality</dt><dd>${escapeHTML(record.evidence_modality.replaceAll("_", " "))}</dd>
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
        ${metricLines(record.metrics)}
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

export function wireArrayControls(form) {
  for (const control of form.querySelectorAll("[data-array-control]")) {
    control.addEventListener("click", (event) => {
      if (event.target.matches("[data-array-add]")) {
        const items = control.querySelector("[data-array-items]");
        const index = Number(control.dataset.nextIndex);
        items.insertAdjacentHTML(
          "beforeend",
          arrayItemControl(control.dataset.arrayControl, "", index),
        );
        control.dataset.nextIndex = String(index + 1);
      }
      if (event.target.matches("[data-array-remove]")) {
        const item = event.target.closest("[data-array-item]");
        const items = control.querySelector("[data-array-items]");
        if (items.children.length === 1) item.querySelector("input").value = "";
        else {
          item.remove();
          Array.from(items.children).forEach((row, index) => {
            const input = row.querySelector("input");
            input.id = `field-${control.dataset.arrayControl}${index === 0 ? "" : `-${index}`}`;
            input.setAttribute(
              "aria-label",
              `${control.dataset.arrayControl} item ${index + 1}`,
            );
          });
        }
      }
    });
  }
}

function integerValue(raw, name) {
  if (!/^-?\d+$/.test(raw)) {
    const err = new Error(`${name} must be an integer written in base 10.`);
    err.code = "invalid_field";
    throw err;
  }
  return BigInt(raw);
}

function typedFieldValue(raw, name, field) {
  if (field.type === "integer") return integerValue(raw, name);
  if (field.type === "number") {
    const number = Number(raw);
    if (!Number.isFinite(number)) {
      const err = new Error(`${name} must be a finite number.`);
      err.code = "invalid_field";
      throw err;
    }
    return number;
  }
  return raw;
}

export function readForm(record, form) {
  const body = {};
  for (const [name, field] of Object.entries(record.input_schema)) {
    if (field.type === "array") {
      const container = form.querySelector(`[data-array-control="${name}"]`);
      const values = container
        ? Array.from(container.querySelectorAll("input"), (input) =>
            input.value.trim(),
          ).filter(Boolean)
        : [];
      if (!values.length && !field.required) continue;
      body[name] = values.map((raw) =>
        typedFieldValue(raw, name, field.items || {}),
      );
      continue;
    }
    const control = form.elements.namedItem(name);
    if (!control) continue;
    const raw = control.value.trim();
    /* An omitted optional field is omitted, never sent as "" or 0: the service reads
       `limit` explicitly so that an explicit 0 stays 0, and a blank sent as one would
       turn "use the default" into "read nothing". */
    if (!raw && !field.required) continue;
    body[name] = typedFieldValue(raw, name, field);
  }
  return body;
}

export function exampleBody(record) {
  const body = {};
  for (const [name, field] of Object.entries(record.input_schema)) {
    if (field.type === "array") {
      const values = Array.isArray(field.default) ? field.default : [];
      if (!values.length) continue;
      body[name] = values.map((value) =>
        typedFieldValue(String(value), name, field.items || {}),
      );
      continue;
    }
    if (
      field.default === undefined ||
      field.default === null ||
      field.default === ""
    ) {
      continue;
    }
    body[name] = typedFieldValue(String(field.default), name, field);
  }
  return body;
}

function resetFormToExample(record, form) {
  for (const [name, field] of Object.entries(record.input_schema)) {
    if (field.type === "array") {
      const control = form.querySelector(`[data-array-control="${name}"]`);
      const values =
        Array.isArray(field.default) && field.default.length
          ? field.default
          : [""];
      control.querySelector("[data-array-items]").innerHTML = values
        .map((value, index) => arrayItemControl(name, value, index))
        .join("");
      control.dataset.nextIndex = String(values.length);
      continue;
    }
    form.elements.namedItem(name).value =
      field.default === undefined || field.default === null
        ? ""
        : String(field.default);
  }
}

export function submissionBody(record, form, submitter) {
  if (!submitter || !submitter.matches("[data-example]")) {
    return readForm(record, form);
  }
  resetFormToExample(record, form);
  return exampleBody(record);
}

/* A buyer paid for an answer, not for a payload. Dumping the response into a <pre> made
   every service look identical and left the reader to do the interpreting they had just
   paid to have done — and it hid the one thing that matters most when a scan finds
   nothing, which is why it found nothing. A presenter states the finding first and keeps
   the raw JSON one click away, never instead of it: the evidence is still the point, it
   just stops being the only thing offered. Services with no presenter yet fall back to the
   payload, so an unpresented service reads as unpolished rather than broken. */
const VERDICT_WORDS = {
  ALLOW: "nothing was detected in this payload",
  SANITIZE: "this payload carries something that must be removed before use",
  BLOCK: "this payload should not be passed downstream",
};

function presentWardenScan(result, _receipt, _record) {
  const verdict = result.verdict;
  const classes = result.threat_classes || [];
  const detections = result.detections || [];
  const rows = detections
    .map(
      (d) => `<tr>
        <td class="mono">${escapeHTML(String(d.class))}</td>
        <td class="mono">${escapeHTML(String(d.match))}</td>
        <td>${escapeHTML(String(d.source))}</td>
        <td class="mono">${escapeHTML(String(d.confidence))}</td>
      </tr>`,
    )
    .join("");

  /* The sanitized payload is the part a buyer actually acts on, and the part most likely to
     be accepted without a second look. It is shown as the text it is, never rendered, and it
     is labelled as the scanner's output rather than as a safe string — a classifier that
     removed what it recognised has not established that nothing else is there. */
  const sanitized =
    result.sanitized_payload === undefined || result.sanitized_payload === null
      ? ""
      : `<h4>What the scanner would pass downstream</h4>
         <pre>${escapeHTML(String(result.sanitized_payload))}</pre>
         <p class="dim">This is what the scanner returned after removing what it matched. It
           is not a statement that the remaining text is safe: a classifier establishes what it
           recognised, never the absence of everything it did not.</p>`;

  return `<section aria-labelledby="result-heading">
      <h3 id="result-heading">What came back</h3>
      <p class="lede">${escapeHTML(verdict || "no verdict")} — ${escapeHTML(
        VERDICT_WORDS[verdict] ||
          "the scanner returned a verdict this page does not recognise",
      )}.</p>
      <dl class="deflist">
        <dt>Risk level</dt><dd class="mono">${escapeHTML(String(result.risk_level))}</dd>
        <dt>Threat classes</dt><dd class="mono">${
          classes.length ? escapeHTML(classes.join(", ")) : "none returned"
        }</dd>
        <dt>Recommendation</dt><dd>${escapeHTML(String(result.recommendation ?? "none given"))}</dd>
        <dt>Scan time</dt><dd class="mono">${escapeHTML(String(result.latency_ms))} ms</dd>
      </dl>
      ${
        rows
          ? `<p class="status-key">What it matched, and where</p>
             <div class="table-wrap"><table><caption>Recorded scanner detections for this run.</caption><thead><tr><th scope="col">Class</th><th scope="col">Match</th><th scope="col">Source</th><th scope="col">Confidence</th></tr></thead>
             <tbody>${rows}</tbody></table></div>`
          : `<p class="dim">No individual detection was returned. An empty detection list with
               an ALLOW verdict means nothing matched — it does not mean the payload is safe.</p>`
      }
      ${sanitized}
      <p class="dim">A scan reports what this scanner recognised in this text. It is not a
        guarantee about the payload, and a clean result is the weaker of the two answers it can
        give: a miss and an absence look identical from here.</p>
    </section>`;
}

function presentYieldRouter(result, _receipt, _record) {
  const current = result.current || {};
  const universe = result.universe || {};
  const decision = result.decision;
  const candidates = (result.candidates || []).slice(0, 5);
  const rows = candidates
    .map(
      (c) => `<tr>
        <td>${escapeHTML(String(c.pair))}</td>
        <td class="mono">${escapeHTML(String(c.fee_tier))}</td>
        <td class="mono">${pct(c.net_fee_apr) ?? "—"}</td>
        <td class="mono">${pct(c.gross_fee_apr) ?? "—"}</td>
      </tr>`,
    )
    .join("");

  /* The decision is the product. A reader who has to derive MOVE from a table of rates has
     been handed the raw material for an answer rather than the answer, which is the thing
     they paid to avoid — and the destination is meaningless without the pool it is measured
     against, so the baseline travels beside it. */
  return `<section aria-labelledby="result-heading">
      <h3 id="result-heading">What came back</h3>
      <p class="lede">${escapeHTML(String(decision))} — ${
        decision === "MOVE"
          ? "a pool in the eligible set earns more than the one this compares against, by enough to clear the switching cost over the stated horizon"
          : "no pool in the eligible set beats the current one by enough to repay the switching cost over the stated horizon"
      }.</p>
      <dl class="deflist">
        <dt>Compared against</dt><dd>${escapeHTML(String(current.pair))} <span class="mono">${escapeHTML(String(current.pool_id))}</span></dd>
        <dt>Its net rate</dt><dd class="mono">${pct(current.net_fee_apr) ?? "—"} <span class="dim">(gross ${pct(current.gross_fee_apr) ?? "—"})</span></dd>
        ${
          result.destination_pool_id
            ? `<dt>Destination</dt><dd class="mono">${escapeHTML(String(result.destination_pool_id))}</dd>`
            : ""
        }
        <dt>Eligible universe</dt><dd>${escapeHTML(String(universe.size))} of ${escapeHTML(String(universe.considered))} pools considered; ${escapeHTML(String(universe.excluded_count))} excluded, each with its reason in the payload below</dd>
      </dl>
      ${
        rows
          ? `<p class="status-key">The eligible set, by the source's own order</p>
             <div class="table-wrap"><table><caption>Eligible pools returned for this run.</caption><thead><tr><th scope="col">Pair</th><th scope="col">Fee tier</th><th scope="col">Net APR</th><th scope="col">Gross APR</th></tr></thead>
             <tbody>${rows}</tbody></table></div>`
          : ""
      }
      <p class="dim">Net is the fee less the protocol's own reported cut — the part a liquidity
        provider keeps. Both rates annualise one 24-hour observation of the pool, so they
        describe today's figures and are not a forecast. Which pool your capital is in was not
        read from any wallet: ${escapeHTML(String(result.current_pool_chosen_by || "it was supplied by the caller"))}</p>
    </section>`;
}

function presentGridOperator(result, _receipt, _record) {
  const plan = result.plan || {};
  const levels = (plan.levels || []).slice(0, 8);
  const rows = levels
    .map(
      (l) => `<tr>
        <td class="mono">${escapeHTML(String(l.index))}</td>
        <td class="mono">${escapeHTML(String(l.price))}</td>
        <td>${escapeHTML(String(l.side ?? "—"))}</td>
      </tr>`,
    )
    .join("");

  /* Grid is a preview and the single most important thing on this page is that it stays one.
     A grid of prices reads like an order book, and a reader who skims could believe something
     is working on their behalf. Nothing is: the object that produced this holds no key, no
     signer and no submitter. */
  return `<section aria-labelledby="result-heading">
      <h3 id="result-heading">What came back</h3>
      <p class="lede">A plan, and only a plan. ${escapeHTML(String(plan.requested_levels ?? levels.length))}
        levels drawn ${escapeHTML(String(plan.side_rule || "around the observed price"))}.
        Nothing was signed, submitted or held.</p>
      <dl class="deflist">
        <dt>Band</dt><dd class="mono">${escapeHTML(String(plan.lower))} to ${escapeHTML(String(plan.upper))}</dd>
        <dt>Reference price</dt><dd class="mono">${escapeHTML(String(plan.reference))}</dd>
        <dt>Size per level</dt><dd class="mono">${escapeHTML(String(plan.size_per_level))}</dd>
        <dt>Submitted</dt><dd>${result.submitted ? "yes" : "no"} — ${escapeHTML(String(result.why_not_submitted || "no submitter exists on this path"))}</dd>
      </dl>
      ${
        rows
          ? `<p class="status-key">The levels this plan would place, if something could place them</p>
             <div class="table-wrap"><table><caption>Grid levels returned for this preview.</caption><thead><tr><th scope="col">#</th><th scope="col">Price</th><th scope="col">Side</th></tr></thead><tbody>${rows}</tbody></table></div>`
          : ""
      }
      <p class="dim">Prices are integers in the pair's own base units, not decimals — they are
        shown as returned so they can be checked against the router's quote without a
        conversion this page invented. Acting on any level requires a session the wallet's
        owner grants on chain, with a spend cap and an expiry.</p>
    </section>`;
}

function presentHealthGuard(result, _receipt, _record) {
  const account = result.account || {};
  const assessment = result.assessment || {};
  const entered = Number(account.markets_entered ?? 0);

  /* The empty case is the one that matters, and it is the common one: most wallets a judge
     tries have no Venus borrow at all. "No shortfall" on an account with nothing in it is not
     a health report, and saying so is the difference between an answer and a reassurance. */
  if (!entered) {
    return `<section aria-labelledby="result-heading">
        <h3 id="result-heading">What came back</h3>
        <p class="lede">This account has entered no Venus markets, so there is no lending
          position here to protect.</p>
        <dl class="deflist">
          <dt>Markets listed</dt><dd class="mono">${escapeHTML(String(account.markets_listed))}</dd>
          <dt>Markets entered</dt><dd class="mono">0</dd>
          <dt>Read at block</dt><dd class="mono">${escapeHTML(String(account.as_of_block))}</dd>
        </dl>
        <p class="dim">A zero shortfall on an account holding nothing is not a statement that
          the account is healthy — there is simply nothing borrowed to be liquidated. This is a
          fact about the address, not a diagnosis of a position.</p>
      </section>`;
  }

  return `<section aria-labelledby="result-heading">
      <h3 id="result-heading">What came back</h3>
      <p class="lede">${escapeHTML(String(assessment.summary || "The account's Venus position, as the comptroller reports it."))}</p>
      <dl class="deflist">
        <dt>Liquidity</dt><dd class="mono">${escapeHTML(String(account.liquidity_usd))} <span class="dim">(${escapeHTML(String(account.scale))})</span></dd>
        <dt>Shortfall</dt><dd class="mono">${escapeHTML(String(account.shortfall_usd))}</dd>
        <dt>Markets entered</dt><dd class="mono">${escapeHTML(String(account.markets_entered))} of ${escapeHTML(String(account.markets_listed))}</dd>
        <dt>Read at block</dt><dd class="mono">${escapeHTML(String(account.as_of_block))}</dd>
        <dt>Submitted</dt><dd>${result.submitted ? "yes" : "no"} — ${escapeHTML(String(result.why_not_submitted || "no submitter exists on this path"))}</dd>
      </dl>
      <p class="dim">Both figures are the comptroller's own, at the block named above, and a
        shortfall is what makes an account liquidatable rather than a prediction that it will
        be. Nothing here was signed or submitted.</p>
    </section>`;
}

const PRESENTERS = {
  "range-doctor": presentRangeDoctor,
  "warden-scan": presentWardenScan,
  "yield-router": presentYieldRouter,
  "grid-operator": presentGridOperator,
  "health-guard": presentHealthGuard,
};

function presentResult(record, answer) {
  const result = answer.result;
  const presenter = PRESENTERS[record.service_id];
  const raw = `<details class="raw">
      <summary>The full response, exactly as the service returned it</summary>
      <pre>${escapeHTML(JSON.stringify(answer, null, 2))}</pre>
    </details>`;
  if (!presenter)
    return `<section aria-labelledby="result-heading">
        <h3 id="result-heading">What came back</h3>
        <pre>${escapeHTML(JSON.stringify(result, null, 2))}</pre>
      </section>`;
  return presenter(result, answer.receipt || {}, record) + raw;
}

function pct(value) {
  return value === null || value === undefined
    ? null
    : `${(value * 100).toFixed(2)}%`;
}

function usd(value) {
  if (value === null || value === undefined) return null;
  return `$${Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function presentRangeDoctor(result, receipt, record) {
  const positions = result.positions || [];
  const payment = receipt.payment || {};
  const incomplete =
    result.scan_complete === false
      ? `<p class="notice notice-warn">This scan is incomplete: unread positions are unknown, not absent.</p>`
      : "";
  const decisions = positions.length
    ? `<ul>${positions
        .map(
          (entry) =>
            `<li><strong>${escapeHTML((entry.diagnosis || {}).decision || "No decision was returned for this position.")}</strong></li>`,
        )
        .join("")}</ul>`
    : `<p class="lede">${escapeHTML(result.decision || "No position decision was returned.")}</p>${incomplete}`;

  const facts = positions.length
    ? positions
        .map((entry) => {
          const d = entry.diagnosis || {};
          const f = d.verifiable_facts || {};
          return `<article class="panel">
              <h4>Position ${escapeHTML(f.position_id ?? DASH)} — ${escapeHTML(STATUS_WORDS[d.status] || d.status || "status unavailable")}</h4>
              <dl class="deflist">
                <dt>Pair</dt><dd>${escapeHTML(f.pair || DASH)}</dd>
                <dt>Position ID</dt><dd class="mono">${escapeHTML(f.position_id ?? DASH)}</dd>
                <dt>Token 0</dt><dd class="mono">${escapeHTML(f.token0 || DASH)}</dd>
                <dt>Token 1</dt><dd class="mono">${escapeHTML(f.token1 || DASH)}</dd>
                <dt>Current tick</dt><dd class="mono">${escapeHTML(f.current_tick ?? DASH)}</dd>
                <dt>Range bounds</dt><dd class="mono">[${escapeHTML(f.lower_tick ?? DASH)}, ${escapeHTML(f.upper_tick ?? DASH)})</dd>
                <dt>BSC block</dt><dd class="mono">${escapeHTML(f.bsc_block ?? DASH)}</dd>
                <dt>Observation time</dt><dd>${escapeHTML(f.observation_time || DASH)}</dd>
              </dl>
            </article>`;
        })
        .join("")
    : `<div class="panel">
        <p>No position-specific facts are available because no active position was diagnosed.</p>
        <dl class="deflist">
          <dt>Wallet read at BSC block</dt><dd class="mono">${escapeHTML((result.observation || {}).bsc_block ?? DASH)}</dd>
          <dt>Observation time</dt><dd>${escapeHTML((result.observation || {}).observation_time || DASH)}</dd>
        </dl>
      </div>`;

  const economics = positions.length
    ? positions
        .map((entry) => {
          const d = entry.diagnosis || {};
          const e = d.economic_consequence || {};
          const rates =
            e.gross_apr === null || e.gross_apr === undefined
              ? `<p>Rate figures are unavailable: ${escapeHTML(e.unavailable_reason || "the required pool evidence is missing")}</p>`
              : `<dl class="deflist">
                  <dt>Gross APR</dt><dd class="num">${escapeHTML(pct(e.gross_apr))}</dd>
                  <dt>Protocol-adjusted net APR</dt><dd class="num">${escapeHTML(pct(e.net_apr))}</dd>
                  <dt>Gross overstatement</dt><dd><span class="num">${escapeHTML(e.overstatement_relative === null ? "not defined because net APR is zero" : pct(e.overstatement_relative))}</span> relative; <span class="num">${escapeHTML(e.overstatement_percentage_points === null ? DASH : `${Number(e.overstatement_percentage_points).toFixed(2)} percentage points`)}</span></dd>
                  <dt>Pool net rate while in range</dt><dd class="num">${escapeHTML(pct(e.pool_net_apr_if_in_range))}</dd>
                  <dt>Raw 24h inputs</dt><dd>${escapeHTML(usd(e.fee_usd_24h) || DASH)} fees − ${escapeHTML(usd(e.protocol_fee_usd_24h) || DASH)} protocol cut, over ${escapeHTML(usd(e.tvl_usd) || DASH)} TVL</dd>
                </dl>`;
          const dollars =
            e.annual_overstatement_usd === null ||
            e.annual_overstatement_usd === undefined
              ? `<p class="dim">Dollar effect is unavailable: ${escapeHTML(e.unavailable_reason || "declared position value is missing")}</p>`
              : `<dl class="deflist">
                  <dt>Declared position value</dt><dd class="num">${escapeHTML(usd(e.declared_position_value_usd))} — caller-declared, not derived</dd>
                  <dt>Annualised gross dollars</dt><dd class="num">${escapeHTML(usd(e.annual_gross_usd))}</dd>
                  <dt>Annualised net dollars</dt><dd class="num">${escapeHTML(usd(e.annual_net_usd))}</dd>
                  <dt>Annual overstatement</dt><dd class="num">${escapeHTML(usd(e.annual_overstatement_usd))}</dd>
                  <dt>Pool rate at your declared value</dt><dd class="num">${escapeHTML(usd(e.pool_rate_at_declared_value_usd))}</dd>
                </dl>`;
          return `<article class="panel">
              <h4>Position ${escapeHTML((d.verifiable_facts || {}).position_id ?? DASH)}</h4>
              ${rates}
              ${dollars}
              <p class="dim">An observation, not a forecast. ${escapeHTML(e.limitation || "The response supplied no further rate limitation.")}</p>
            </article>`;
        })
        .join("")
    : `<div class="panel"><p>No position-level economic consequence is available because no position was diagnosed.</p></div>`;

  const actions = positions.length
    ? positions
        .map((entry) => {
          const d = entry.diagnosis || {};
          const conditional = d.conditional_actions || {};
          const alternatives = (conditional.actions || [])
            .map(
              (action) =>
                `<li><strong>${escapeHTML(action.kind || "conditional")}</strong>: ${escapeHTML(action.text)}${
                  action.link
                    ? ` <a href="${escapeHTML(action.link)}" rel="noopener">open it on PancakeSwap</a>`
                    : ""
                }</li>`,
            )
            .join("");
          const switching =
            conditional.estimated_recenter_cost_usd === null ||
            conditional.estimated_recenter_cost_usd === undefined
              ? `<p class="dim">Numeric switching cost and break-even are unavailable: ${escapeHTML(conditional.unavailable_reason || "the required declared inputs are missing")}</p>`
              : `<dl class="deflist">
                  <dt>Estimated recenter cost</dt><dd class="num">${escapeHTML(usd(conditional.estimated_recenter_cost_usd))} — caller-declared</dd>
                  <dt>Cost-only break-even</dt><dd class="num">${
                    conditional.cost_only_break_even_days === null ||
                    conditional.cost_only_break_even_days === undefined
                      ? `unavailable — ${escapeHTML(conditional.unavailable_reason || "the required rate or value is missing")}`
                      : `${escapeHTML(Number(conditional.cost_only_break_even_days).toFixed(2))} days`
                  }</dd>
                </dl>`;
          return `<article class="panel">
              <h4>Position ${escapeHTML((d.verifiable_facts || {}).position_id ?? DASH)}</h4>
              ${alternatives ? `<ul>${alternatives}</ul>` : `<p>No wait-versus-recenter alternatives apply to this position.</p>`}
              ${switching}
              <p class="dim">${escapeHTML(conditional.limitation || "Costs and future rates remain uncertain.")}</p>
            </article>`;
        })
        .join("")
    : `<div class="panel"><p>No position-specific action is available because no position was diagnosed.</p></div>`;

  const measured = result.measured_value || {};
  const benchmarkReason =
    measured.benchmark_unavailable_reason ||
    "The preregistered v3 paired report has not run, so paired manual time, quality, and its report link are unavailable.";
  const pairedTime =
    measured.paired_manual_seconds === null ||
    measured.paired_manual_seconds === undefined
      ? `unavailable — ${escapeHTML(benchmarkReason)}`
      : `${escapeHTML(Number(measured.paired_manual_seconds).toFixed(3))} seconds`;
  const quality =
    measured.quality_result === null || measured.quality_result === undefined
      ? `unavailable — ${escapeHTML(benchmarkReason)}`
      : escapeHTML(
          typeof measured.quality_result === "string"
            ? measured.quality_result
            : JSON.stringify(measured.quality_result),
        );
  const reportLink = measured.report_url
    ? `<a href="${escapeHTML(measured.report_url)}">Open the v3 paired report</a>`
    : `unavailable — ${escapeHTML(benchmarkReason)}`;
  const proofId =
    receipt.transaction_id ||
    receipt.payment_id ||
    payment.transaction_id ||
    payment.payment_id;
  const proofNonce = receipt.nonce || payment.nonce;
  const settled = payment.status === "settled";
  const proofMissing = record.paid_stock
    ? "This preview used no payment authorization, so it has no settlement record."
    : `This ${record.stock_status} is not admitted to paid stock, so no payment occurred.`;
  const settlementNote = settled
    ? "The configured facilitator reported this settlement and transaction binding. The receipt does not prove chain finality or result correctness."
    : "No payment authorization was used for this preview. The input/output hashes bind delivery, not correctness.";

  return `<section aria-labelledby="range-decision-heading">
      <h3 id="range-decision-heading">1. Decision</h3>
      ${decisions}
    </section>
    <section aria-labelledby="range-facts-heading">
      <h3 id="range-facts-heading">2. Verifiable facts</h3>
      ${facts}
    </section>
    <section aria-labelledby="range-economics-heading">
      <h3 id="range-economics-heading">3. Economic consequence</h3>
      ${economics}
    </section>
    <section aria-labelledby="range-actions-heading">
      <h3 id="range-actions-heading">4. Conditional actions</h3>
      ${actions}
    </section>
    <section aria-labelledby="range-coverage-heading">
      <h3 id="range-coverage-heading">5. Coverage</h3>
      <div class="panel">
        <p class="lede">${escapeHTML(result.coverage || "Coverage sentence unavailable.")}</p>
        <dl class="deflist">
          <dt>Positions held</dt><dd class="num">${escapeHTML(fmtInt(result.positions_held))}</dd>
          <dt>Positions examined</dt><dd class="num">${escapeHTML(fmtInt(result.positions_examined))}</dd>
          <dt>Closed skipped</dt><dd class="num">${escapeHTML(fmtInt(result.closed_skipped))}</dd>
          <dt>Other open positions not selected</dt><dd class="num">${escapeHTML(fmtInt(result.open_skipped || 0))}</dd>
          <dt>Scan complete</dt><dd>${result.scan_complete === true ? "yes" : "no"}</dd>
          <dt>Stopped by</dt><dd>${escapeHTML(result.stopped_by || "nothing; the scan reached its end")}</dd>
        </dl>
        ${incomplete}
      </div>
    </section>
    <section aria-labelledby="range-value-heading">
      <h3 id="range-value-heading">6. Measured value</h3>
      <div class="panel">
        <dl class="deflist">
          <dt>${record.paid_stock ? "Current catalogue offer" : "Price after admission"}</dt><dd class="num">${escapeHTML(record.price_display)}</dd>
          <dt>This-run time</dt><dd class="num">${measured.this_run_seconds === null || measured.this_run_seconds === undefined ? "unavailable — the backend did not return a duration" : `${escapeHTML(Number(measured.this_run_seconds).toFixed(3))} seconds`}</dd>
          <dt>Paired manual time</dt><dd>${pairedTime}</dd>
          <dt>Quality result</dt><dd>${quality}</dd>
          <dt>V3 report</dt><dd>${reportLink}</dd>
          <dt>Payment state for this run</dt><dd class="mono">${escapeHTML(payment.status || "not recorded")}</dd>
        </dl>
        <p class="dim">${record.paid_stock ? "This service has passed the catalogue admission gate; this browser form still ran its free preview." : `This service is not admitted to paid stock: its current status is ${escapeHTML(record.stock_status)}. This response makes no $0.50 paid-value claim.`}</p>
      </div>
    </section>
    <section aria-labelledby="range-proof-heading">
      <h3 id="range-proof-heading">7. Proof</h3>
      <div class="panel">
        <dl class="deflist">
          <dt>Input hash</dt><dd class="mono">${escapeHTML(receipt.input_hash || DASH)}</dd>
          <dt>Output hash</dt><dd class="mono">${escapeHTML(receipt.output_hash || DASH)}</dd>
          <dt>Delivery time</dt><dd>${escapeHTML(receipt.delivered_at || DASH)}</dd>
          <dt>Payment status</dt><dd class="mono">${escapeHTML(payment.status || "not recorded")}</dd>
          <dt>Settlement transaction / payment ID</dt><dd class="mono">${proofId ? escapeHTML(proofId) : `unavailable — ${escapeHTML(proofMissing)}`}</dd>
          <dt>Unique settlement nonce</dt><dd class="mono">${proofNonce ? escapeHTML(proofNonce) : `unavailable — ${escapeHTML(proofMissing)}`}</dd>
        </dl>
        <p class="dim">${escapeHTML(settlementNote)}</p>
      </div>
    </section>
    <section aria-labelledby="range-limitation-heading">
      <h3 id="range-limitation-heading">8. Primary limitation</h3>
      <div class="notice notice-warn">
        <p><strong>${escapeHTML(result.primary_limitation || "The result did not supply a primary limitation.")}</strong></p>
      </div>
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
  const paymentProof =
    payment.status === "settled"
      ? `<dt>Payment ID</dt><dd class="mono">${escapeHTML(payment.payment_id || DASH)}</dd>
         <dt>Nonce</dt><dd class="mono">${escapeHTML(payment.nonce || DASH)}</dd>
         <dt>Settlement transaction</dt><dd class="mono">${escapeHTML(payment.transaction_id || DASH)}</dd>`
      : `<dt>Paid-stock status</dt><dd>${escapeHTML(record.stock_status)}</dd>`;
  const receiptSection =
    record.service_id === "range-doctor"
      ? ""
      : `<section aria-labelledby="receipt-heading">
      <h3 id="receipt-heading">The receipt</h3>
      <div class="panel">
        <dl class="deflist">
          <dt>Service</dt><dd class="mono">${escapeHTML(receipt.service)}</dd>
          <dt>Delivered at</dt><dd>${escapeHTML(receipt.delivered_at)}</dd>
          <dt>Input hash</dt><dd class="mono">${escapeHTML(receipt.input_hash)}</dd>
          <dt>Output hash</dt><dd class="mono">${escapeHTML(receipt.output_hash)}</dd>
          <dt>Payment</dt><dd class="mono">${escapeHTML(payment.status)}</dd>
          ${paymentProof}
        </dl>
        <p class="dim">
          A receipt records delivery and nothing else. It does not assert the work is correct,
          and Docket does not sign it — it is a self-check for you. Both hashes are plain
          SHA-256 over canonical JSON and need none of Docket's code to recompute;
          <a href="/llms.txt">/llms.txt</a> carries the exact recipe. A
          <span class="mono">settled</span> status records what the configured facilitator
          reported; it does not prove chain finality or that the result is correct.
        </p>
      </div>
    </section>`;
  const outcome = region("outcome");
  outcome.innerHTML = `${presentResult(record, answer)}${receiptSection}`;
  const heading = outcome.querySelector("h3");
  heading.setAttribute("tabindex", "-1");
  return heading;
}

function wireActivation(record) {
  const target = region("activate");
  if (!target) return;
  target.innerHTML = activationForm(record);
  const form = target.querySelector("[data-activate]");
  wireArrayControls(form);
  const buttons = form.querySelectorAll('button[type="submit"]');
  const outcome = region("outcome");
  const outcomeStatus = region("outcome-status");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    outcome.setAttribute("aria-busy", "false");
    outcomeStatus.textContent = "";
    let body;
    try {
      body = submissionBody(record, form, event.submitter);
    } catch (err) {
      paintRunFailure(outcome, err);
      return;
    }
    const missing = Object.entries(record.input_schema)
      .filter(([name, field]) => {
        if (field.type === "array") {
          const container = form.querySelector(
            `[data-array-control="${name}"]`,
          );
          return (
            field.required &&
            container &&
            !Array.from(container.querySelectorAll("input")).some((input) =>
              input.value.trim(),
            )
          );
        }
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
    buttons.forEach((button) => {
      button.disabled = true;
    });
    outcome.setAttribute("aria-busy", "true");
    outcomeStatus.textContent = `Running ${record.name}.`;
    outcome.innerHTML = `<div class="notice">
        <p>Running ${escapeHTML(record.name)}. It usually takes about
        ${escapeHTML(fmtInt(record.typical_seconds))} seconds, and this is one attempt.</p>
      </div>`;
    let completedHeading = null;
    try {
      completedHeading = paintOutcome(
        record,
        await postJSON(record.hire_path, body),
      );
      outcomeStatus.textContent = `${record.name} finished. The result is ready.`;
    } catch (err) {
      outcomeStatus.textContent = "";
      paintRunFailure(outcome, err);
    } finally {
      outcome.setAttribute("aria-busy", "false");
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
    if (completedHeading) completedHeading.focus();
  });
}

export async function initService() {
  const id = new URLSearchParams(window.location.search).get("id");
  const target = region("service");
  const activate = region("activate");
  const activationSection = region("activation-section");
  if (!id) {
    activate.innerHTML = "";
    activationSection.hidden = true;
    target.innerHTML = `<div class="panel panel-error" role="alert">
        <h1>No service selected</h1>
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
    activationSection.hidden = true;
    renderError(target, err, "Service unavailable");
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

function browsePresentation(item, responders) {
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
  return { href, name, placeholder, protocols, endpoint };
}

function browseRow(item, responders) {
  const { href, name, placeholder, protocols, endpoint } =
    browsePresentation(item, responders);
  return `<tr>
      <td><a href="${href}">${escapeHTML(name)}</a>${placeholder}</td>
      <td class="num mono">${escapeHTML(item.token_id)}</td>
      <td class="num">${escapeHTML(fmtInt(item.feedback_count))}</td>
      <td>${protocols}</td>
      <td>${endpoint}</td>
      <td class="mono">${escapeHTML(item.name_family)}</td>
    </tr>`;
}

function browseCard(item, responders) {
  const { href, name, placeholder, protocols, endpoint } =
    browsePresentation(item, responders);
  return `<article class="agent-card">
      <h3><a href="${href}">${escapeHTML(name)}</a></h3>
      ${placeholder}
      <dl class="deflist">
        <dt>Token</dt><dd class="num mono">${escapeHTML(item.token_id)}</dd>
        <dt>Feedback</dt><dd class="num">${escapeHTML(fmtInt(item.feedback_count))}</dd>
        <dt>Declared protocols</dt><dd>${protocols}</dd>
        <dt>Endpoint</dt><dd>${endpoint}</dd>
        <dt>Name family</dt><dd class="mono">${escapeHTML(item.name_family)}</dd>
      </dl>
    </article>`;
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
      <div class="browse-table table-wrap">
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
      <div class="agent-cards" aria-label="Agents">
        ${listing.items.map((item) => browseCard(item, responders)).join("")}
      </div>
      <p class="btn-row">
        <button type="button" class="btn" data-offset="${prevOff}" ${listing.offset === 0 ? "disabled" : ""}>Previous</button>
        <button type="button" class="btn" data-offset="${nextOff}" ${nextOff >= listing.total ? "disabled" : ""}>Next</button>
      </p>`;
  }

  for (const button of target.querySelectorAll("[data-offset]")) {
    button.addEventListener("click", () => {
      goToBrowse(
        { ...state, offset: Number(button.dataset.offset) },
        true,
        true,
      );
    });
  }
  const clear = target.querySelector('[data-action="clear"]');
  if (clear) clear.addEventListener("click", clearFilters);
}

async function loadBrowse(state, focusResults) {
  const token = ++browseRequest;
  const target = region("results");
  const status = region("results-status");
  target.setAttribute("aria-busy", "true");
  status.textContent = "Loading agents.";
  for (const button of target.querySelectorAll("[data-offset]")) {
    button.disabled = true;
  }
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
    target.setAttribute("aria-busy", "false");
    const shownTo = Math.min(
      listing.offset + listing.items.length,
      listing.total,
    );
    status.textContent = listing.total
      ? `Agents updated. Showing ${listing.offset + 1} to ${shownTo} of ${listing.total} matching agents.`
      : "Agents updated. No agents match.";
    if (focusResults) document.getElementById("results-heading").focus();
  } catch (err) {
    if (token !== browseRequest) return;
    const line = region("snapshot");
    if (line) line.textContent = "Snapshot status unavailable.";
    renderError(target, err);
    target.setAttribute("aria-busy", "false");
    status.textContent = "Agents could not be loaded.";
    if (focusResults) document.getElementById("results-heading").focus();
  }
}

function goToBrowse(state, push, focusResults = false) {
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
  loadBrowse(state, focusResults);
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
    true,
  );
}

function preserveNameFamilyOption(select, selected) {
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
  preserveNameFamilyOption(select, selected);
  select.value = selected || "";
}

export async function initBrowse() {
  const state = readFilters();
  browseState = state;
  const nameFamily = document.querySelector('[data-filter="name_family"]');
  if (nameFamily) preserveNameFamilyOption(nameFamily, state.name_family);
  for (const control of document.querySelectorAll("[data-filter]")) {
    control.addEventListener("change", () =>
      goToBrowse(stateFromControls(), true, true),
    );
  }
  const clear = document.querySelector('[data-action="clear"]');
  if (clear) clear.addEventListener("click", clearFilters);
  window.addEventListener("popstate", () =>
    goToBrowse(readFilters(), false, true),
  );
  goToBrowse(state, false);
  await fillNameFamilyOptions(state.name_family);
  syncControls(browseState);
}

/* ---------------------------------------------------------- Pancake record */

function rangeLabel(status) {
  return (
    {
      in_range: "in range",
      out_of_range_below: "below range",
      out_of_range_above: "above range",
      closed: "closed",
      unknown_pool: "range unavailable",
    }[status] || "range unavailable"
  );
}

function recordReference(line) {
  const references = [];
  if (line.prior_observation_sha256) {
    references.push(
      `prior observation <code>${escapeHTML(line.prior_observation_sha256)}</code>`,
    );
  }
  if (line.supersedes_decision_sha256) {
    references.push(
      `supersedes decision <code>${escapeHTML(line.supersedes_decision_sha256)}</code>`,
    );
  }
  if (line.answers_decision_sha256) {
    references.push(
      `answers decision <code>${escapeHTML(line.answers_decision_sha256)}</code>`,
    );
  }
  return references.length
    ? references.join("; ")
    : '<span class="dim">No digest reference on this row</span>';
}

function recordRow(line) {
  if (line.kind === "owner_decision") {
    const rationale = line.rationale ? ` — ${escapeHTML(line.rationale)}` : "";
    return `<tr class="owner-decision-row">
        <td>${escapeHTML(line.decided_at || DASH)}</td>
        <td class="num">${DASH}</td>
        <td><strong>Owner decision: ${escapeHTML(line.decision || DASH)}</strong>${rationale}</td>
        <td><span class="badge">owner decision</span></td>
        <td class="record-link">${recordReference(line)}</td>
      </tr>`;
  }
  const report = line.report || {};
  const entry = (report.positions || [])[0] || {};
  const diagnosis = entry.diagnosis || {};
  const facts = diagnosis.verifiable_facts || {};
  const decision =
    diagnosis.decision ||
    report.decision ||
    line.error ||
    "No position decision was recorded on this observation.";
  return `<tr>
      <td>${escapeHTML(displayTimestamp(line.observed_at))}</td>
      <td class="num mono">${escapeHTML(facts.bsc_block ?? (report.observation || {}).bsc_block ?? DASH)}</td>
      <td>${escapeHTML(decision)}</td>
      <td>${escapeHTML(rangeLabel(diagnosis.status))}</td>
      <td class="record-link">${recordReference(line)}</td>
    </tr>`;
}

export function paintPancakeRecord(history) {
  const target = region("pancake-record");
  const lines = Array.isArray(history.lines) ? history.lines : [];
  const dates = lines
    .map((line) => line.decided_at || line.observed_at)
    .filter(Boolean)
    .sort();
  const window = dates.length
    ? `${dates[0]} to ${dates[dates.length - 1]}`
    : "no stored observation dates";
  const completeness = history.truncated
    ? "The response was truncated; later stored rows may be absent."
    : "The response was not truncated.";
  const parseNote = history.skipped_unparsable
    ? `${fmtInt(history.skipped_unparsable)} stored lines could not be parsed and are not in the table.`
    : "No stored lines were skipped as unparsable.";
  const table = lines.length
    ? `<div class="table-wrap">
        <table class="record-table">
          <caption>
            ${escapeHTML(fmtInt(lines.length))} parsed rows returned by /lp-record for ${escapeHTML(window)}.
            ${escapeHTML(completeness)} ${escapeHTML(parseNote)}
          </caption>
          <thead><tr>
            <th scope="col">Date</th>
            <th scope="col" class="num">BSC block</th>
            <th scope="col">Decision sentence</th>
            <th scope="col">Range state</th>
            <th scope="col">Digest link</th>
          </tr></thead>
          <tbody>${lines.map((line) => recordRow(line)).join("")}</tbody>
        </table>
      </div>`
    : `<div class="panel"><p>No record lines are mounted on this host.</p></div>`;
  target.innerHTML = `${table}
    <div class="notice">
      <h3>What the digest chain anchors</h3>
      <p>
        A surviving digest reference can expose removal or editing of the observation or owner
        decision it names. The intended sequence is observation, owner decision, optional
        superseding decisions, then a later observation that answers the decision.
      </p>
      <p class="dim">
        This is not a running hash. It does not anchor an unreferenced observation or the final
        row, authenticate who typed a decision, supply an external timestamp, establish causality
        or returns, or stop the file's controller rewriting the entire chain. /lp-record publishes
        parsed rows; it does not run verify_history on this response.
      </p>
    </div>`;
}

export function paintPancakeLive(record, answer) {
  const result = answer.result || {};
  const entry = (result.positions || [])[0] || {};
  const diagnosis = entry.diagnosis || {};
  const facts = diagnosis.verifiable_facts || {};
  const economics = diagnosis.economic_consequence || {};
  const conditional = diagnosis.conditional_actions || {};
  const headline = result.pancake_headline || {};
  const decision =
    diagnosis.decision ||
    result.decision ||
    "No position decision was returned.";

  region("pancake-decision").innerHTML =
    `<p class="decision-sentence">${escapeHTML(decision)}</p>
    <dl class="decision-facts">
      <div><dt>Position</dt><dd class="mono">${escapeHTML(facts.position_id ?? DASH)}</dd></div>
      <div><dt>Range state</dt><dd>${escapeHTML(rangeLabel(diagnosis.status))}</dd></div>
      <div><dt>BSC block</dt><dd class="mono">${escapeHTML(facts.bsc_block ?? (result.observation || {}).bsc_block ?? DASH)}</dd></div>
      <div><dt>Observed</dt><dd>${escapeHTML(facts.observation_time || (result.observation || {}).observation_time || DASH)}</dd></div>
    </dl>`;

  const ratesAvailable =
    economics.gross_apr !== null && economics.gross_apr !== undefined;
  const rates = ratesAvailable
    ? `<dl class="deflist">
        <dt>Gross pool APR</dt><dd class="num">${escapeHTML(pct(economics.gross_apr))}</dd>
        <dt>Protocol-adjusted net pool APR</dt><dd class="num">${escapeHTML(pct(economics.net_apr))}</dd>
        <dt>Gross-to-net overstatement</dt><dd class="num">${escapeHTML(economics.overstatement_relative === null ? "not defined because net APR is zero" : pct(economics.overstatement_relative))}</dd>
        <dt>Declared fixed notional</dt><dd class="num">${escapeHTML(usd(economics.declared_position_value_usd) || DASH)} — caller-declared</dd>
        <dt>Annual gross dollars at that notional</dt><dd class="num">${escapeHTML(usd(economics.annual_gross_usd) || DASH)}</dd>
        <dt>Annual net dollars at that notional</dt><dd class="num">${escapeHTML(usd(economics.annual_net_usd) || DASH)}</dd>
        <dt>Annual overstatement at that notional</dt><dd class="num">${escapeHTML(usd(economics.annual_overstatement_usd) || DASH)}</dd>
        <dt>Cost-only recenter payback</dt><dd class="num">${conditional.cost_only_break_even_days === null || conditional.cost_only_break_even_days === undefined ? escapeHTML(conditional.unavailable_reason || DASH) : `${escapeHTML(Number(conditional.cost_only_break_even_days).toFixed(2))} days`}</dd>
        <dt>Post-hoc median payback delay</dt><dd class="num">${headline.median_payback_delay_days === null || headline.median_payback_delay_days === undefined ? DASH : `${escapeHTML(Number(headline.median_payback_delay_days).toFixed(2))} days across ${escapeHTML(fmtInt(headline.n_candidate_moves))} candidate moves`}</dd>
      </dl>`
    : `<p>Rate figures are unavailable: ${escapeHTML(economics.unavailable_reason || "the required pool evidence is missing")}</p>`;
  region("pancake-economics").innerHTML = `<div class="panel">${rates}
      <p class="dim">Fixed-notional proxy, not this position's earnings. ${escapeHTML(economics.limitation || "The live response supplied no further rate limitation.")}</p>
      <p class="dim">${escapeHTML(conditional.limitation || "Future rates and unmeasured costs remain outside this calculation.")}</p>
    </div>`;

  const actions = (conditional.actions || [])
    .map(
      (action) => `<article class="action-card">
        <p class="eyebrow">${escapeHTML(action.kind || "conditional")}</p>
        <p>${escapeHTML(action.text || "No action sentence was returned.")}</p>
        ${action.link ? `<p><a class="btn" href="${escapeHTML(action.link)}" rel="noopener">Open position in PancakeSwap</a></p>` : ""}
      </article>`,
    )
    .join("");
  region("pancake-actions").innerHTML = actions
    ? `<div class="action-grid">${actions}</div>`
    : `<div class="panel"><p>No position-specific wait-versus-recenter actions were returned.</p></div>`;
}

export function paintPancakeDecisionImpact(report) {
  const impact = report.decision_impact || {};
  const payback = impact.break_even_shift || {};
  const reversal = impact.ranking_reversals || {};
  const notionals = (impact.dollars_at_notionals || {}).notionals || [];
  const fixed =
    notionals.find((item) => item.notional_usd === payback.notional_usd) ||
    notionals[0] ||
    {};
  region("pancake-impact").innerHTML = `<div class="impact-grid">
      <article class="impact-stat">
        <p class="metric-label">Annual overstatement</p>
        <p class="metric-value">${escapeHTML(usd(fixed.median_annual_overstatement_usd) || DASH)}</p>
        <p class="metric-note">Median at ${escapeHTML(usd(fixed.notional_usd) || DASH)} fixed notional across ${escapeHTML(fmtInt(fixed.n_pools))} eligible pools.</p>
      </article>
      <article class="impact-stat">
        <p class="metric-label">Payback delay</p>
        <p class="metric-value">${payback.median_days_later_than_gross_implies === null || payback.median_days_later_than_gross_implies === undefined ? DASH : `${escapeHTML(Number(payback.median_days_later_than_gross_implies).toFixed(2))} days`}</p>
        <p class="metric-note">Median across ${escapeHTML(fmtInt(payback.n_moves))} candidate moves; net rather than gross pool rates.</p>
      </article>
      <article class="impact-stat">
        <p class="metric-label">Ranking reversals</p>
        <p class="metric-value">${escapeHTML(fmtInt(reversal.numerator))}/${escapeHTML(fmtInt(reversal.denominator))}</p>
        <p class="metric-note">Ordered eligible-pool pairs in the frozen corpus.</p>
      </article>
    </div>
    <div class="notice">
      <p><strong>${escapeHTML((impact.registration_state || "registration state unavailable").replaceAll("_", "-"))}</strong> — ${escapeHTML(impact.registration_note || "No registration note was returned.")}</p>
      <p class="dim">${escapeHTML(reversal.what_this_measures || "The response supplied no further reversal method.")}</p>
      <p class="dim">${escapeHTML(payback.what_it_does_not_measure || "The response supplied no further payback limitation.")}</p>
    </div>`;
}

function paintPancakeContext(orientation) {
  const context = orientation.pancake_context || {};
  const meta = context.subgraph_meta || {};
  region("pancake-context").innerHTML =
    `<p>${escapeHTML(context.first_party_skills || "First-party skill context is unavailable.")}</p>
    <p>
      On ${escapeHTML(displayTimestamp(meta.query_observed_at))}, the read-only PancakeSwap BSC V3
      subgraph query returned an indexed time of ${escapeHTML(meta.indexed_at || DASH)} and
      <code>hasIndexingErrors: ${escapeHTML(String(meta.has_indexing_errors))}</code>.
    </p>
    <p class="dim">${escapeHTML(meta.method || "The source method is unavailable.")}</p>`;
}

export async function initPancake() {
  const [recordResult, historyResult, advantageResult, orientationResult] =
    await Promise.allSettled([
      fetchJSON("/services/range-doctor"),
      fetchJSON("/lp-record"),
      fetchJSON("/advantage/v2.json"),
      fetchJSON("/pancake"),
    ]);

  if (historyResult.status === "fulfilled") {
    paintPancakeRecord(historyResult.value);
  } else {
    renderError(region("pancake-record"), historyResult.reason);
  }
  if (advantageResult.status === "fulfilled") {
    paintPancakeDecisionImpact(advantageResult.value);
  } else {
    renderError(region("pancake-impact"), advantageResult.reason);
  }
  if (orientationResult.status === "fulfilled") {
    paintPancakeContext(orientationResult.value);
  } else {
    renderError(region("pancake-context"), orientationResult.reason);
  }

  if (recordResult.status !== "fulfilled") {
    for (const name of [
      "pancake-decision",
      "pancake-economics",
      "pancake-actions",
    ]) {
      renderError(region(name), recordResult.reason);
    }
    return;
  }
  const record = recordResult.value;
  const target = region("pancake-decision");
  target.innerHTML = `<div class="panel">
      <p><strong>No fresh position decision has run.</strong> The evidence below remains available
        without spending a hire allowance. Run one read when you want current position data.</p>
      <p class="btn-row">
        <button type="button" class="btn btn-primary" data-pancake-run
          aria-describedby="pancake-run-note">Run fresh decision</button>
      </p>
      <p class="dim" id="pancake-run-note" aria-live="polite">One explicit run uses one free-tier
        hire attempt and performs the read-only Range Doctor request.</p>
    </div>`;
  const button = target.querySelector("[data-pancake-run]");
  const note = target.querySelector("#pancake-run-note");
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Running fresh decision…";
    note.textContent = `Running ${record.name}; this is one attempt.`;
    try {
      const answer = await postJSON(record.hire_path, exampleBody(record));
      paintPancakeLive(record, answer);
    } catch (err) {
      for (const name of [
        "pancake-decision",
        "pancake-economics",
        "pancake-actions",
      ]) {
        renderError(region(name), err);
      }
    }
  });
}

/* ------------------------------------------------------------ agent detail */

/* A pointer to one agent, not a figure: every number in the note below is read
   from the response. If this agent is not in the served snapshot the note is
   simply not shown. */
const WORKED_EXAMPLE_ID = "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:129";

function workedExample(detail) {
  const answered = detail.observations.find(
    (obs) => obs.outcome === "responded",
  );
  if (!answered) return "";
  const name = displayName(detail);
  const isExplorer = answered.url.includes("8004scan");
  const what = isExplorer
    ? "That URL is the block explorer's own agent-creation page. It is a web page for humans, not an agent endpoint."
    : "Read the URL itself before reading the outcome.";
  return `<p>
      <strong>Worked example from this snapshot.</strong>
      ${escapeHTML(name)} (token ${escapeHTML(detail.token_id)}) declares
      <code>${escapeHTML(answered.url)}</code> as an endpoint. ${escapeHTML(what)}
      It replied with status ${escapeHTML(answered.status_code)}, so Docket records the outcome as
      "Answered" — which is exactly as much as that word ever claims. You are looking at it.
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

export function observationSection(detail) {
  if (detail.observations.length) {
    return `<div class="table-wrap">
        <table>
          <caption>
            Latest sweep observation for each probed URL in snapshot
            ${escapeHTML(detail.coverage.snapshot_id)}. One GET each, one attempt, at the moment
            of that sweep.
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

function lastAgentProbe(detail) {
  if (detail.latest_on_demand_observation) {
    return detail.latest_on_demand_observation;
  }
  return detail.observations
    .filter(
      (observation) => observation.kind === "a2a" || observation.kind === "mcp",
    )
    .reduce((latest, observation) => {
      if (!latest) return observation;
      return String(observation.observed_at || "") >=
        String(latest.observed_at || "")
        ? observation
        : latest;
    }, null);
}

export function agentActionBlock(detail, associatedServices) {
  const latest = lastAgentProbe(detail);
  const canReprobe =
    detail.declares_callable && latest && latest.outcome === "responded";
  const observedProbeable = new Set(
    detail.observations
      .filter((row) => row.kind === "a2a" || row.kind === "mcp")
      .map((row) => row.url),
  );
  const actionEndpoints = detail.endpoints.filter((url) =>
    observedProbeable.has(url),
  );
  const endpoints = actionEndpoints.length
    ? actionEndpoints
        .map((url) => {
          const observation = detail.observations.find(
            (row) => row.url === url,
          );
          const outcome = outcomeLabel(observation && observation.outcome);
          const recorded = observation
            ? `<p>
                <span class="outcome ${outcome.className}">${escapeHTML(outcome.label)}</span>
                ${observation.status_code === null ? "No HTTP status was returned." : `HTTP status ${escapeHTML(observation.status_code)}.`}
                Observed <time datetime="${escapeHTML(observation.observed_at || "")}">${escapeHTML(displayTimestamp(observation.observed_at))}</time>.
              </p>
              <p class="dim">${escapeHTML(outcome.means)}</p>`
            : `<p class="dim">Docket has no probe outcome for this declared URL in the served snapshot.</p>`;
          return `<li class="endpoint-action">
              <div class="endpoint-copy">
                <code>${escapeHTML(url)}</code>
                <button type="button" class="btn" data-copy-endpoint="${escapeHTML(url)}">Copy endpoint</button>
              </div>
              ${recorded}
            </li>`;
        })
        .join("")
    : `<li><p class="dim">No A2A or MCP endpoint has a recorded probe outcome in the served snapshot.</p></li>`;
  const onDemand = detail.latest_on_demand_observation;
  const onDemandResult = onDemand ? outcomeLabel(onDemand.outcome) : null;
  const onDemandSection = onDemand
    ? `<section aria-labelledby="on-demand-probe-heading">
        <h3 id="on-demand-probe-heading">Latest on-demand re-probe</h3>
        <p>
          <span class="outcome ${onDemandResult.className}">${escapeHTML(onDemandResult.label)}</span>
          ${onDemand.status_code === null ? "No HTTP status was returned." : `HTTP status ${escapeHTML(onDemand.status_code)}.`}
          ${onDemand.elapsed_ms === null ? "" : `Elapsed ${escapeHTML(fmtInt(onDemand.elapsed_ms))} ms.`}
        </p>
        <p>
          Re-probed on request at <time datetime="${escapeHTML(onDemand.observed_at || "")}">${escapeHTML(displayTimestamp(onDemand.observed_at))}</time>;
          not part of the snapshot's coverage figures.
        </p>
        <p class="dim">${escapeHTML(onDemandResult.means)}${onDemand.detail ? ` Detail: ${escapeHTML(onDemand.detail)}.` : ""}</p>
      </section>`
    : `<section aria-labelledby="on-demand-probe-heading">
        <h3 id="on-demand-probe-heading">Latest on-demand re-probe</h3>
        <p class="dim">No on-demand re-probe has been requested for this agent in the served snapshot.</p>
      </section>`;
  const control = canReprobe
    ? `<p class="btn-row">
        <button type="button" class="btn btn-primary" data-reprobe>Re-probe now</button>
        <span class="dim">Repeats one pinned GET to the endpoint in the latest probe observation that answered. Any HTTP status counts as an answer; it does not show what the agent does behind it.</span>
      </p>`
    : `<p class="dim">Re-probe is available only when this agent declares a callable protocol and its latest sweep or on-demand probe observation answered.</p>`;
  return `<section aria-labelledby="agent-actions-heading">
      <h2 id="agent-actions-heading">What you can do with this agent</h2>
      <p class="section-note">
        Copy the endpoints the publisher declared, inspect Docket's sweep and on-demand probe
        outcomes separately, and see whether Docket binds a service action to this identity. A
        probe reads reachability only.
      </p>
      <div class="panel">
        <dl class="deflist">
          <dt>Declares x402 payments</dt><dd>${detail.x402 ? "yes" : "no"}</dd>
        </dl>
        <ul class="endpoint-actions">${endpoints}</ul>
        ${onDemandSection}
        ${control}
        <div data-region="agent-probe-result" aria-live="polite"></div>
      </div>
      <div class="panel agent-services">
        <h3>Docket-run services associated with this identity</h3>
        <p class="dim">These are Docket's own bindings. The ERC-8004 registration does not declare them.</p>
        ${associatedServices}
      </div>
    </section>`;
}

function bindAgentActions(detail) {
  for (const button of document.querySelectorAll("[data-copy-endpoint]")) {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copyEndpoint);
        button.textContent = "Copied";
      } catch (err) {
        button.textContent = "Select the endpoint text to copy";
      }
    });
  }
  const reprobe = document.querySelector("[data-reprobe]");
  if (!reprobe) return;
  reprobe.addEventListener("click", async () => {
    reprobe.disabled = true;
    reprobe.textContent = "Re-probing…";
    const target = region("agent-probe-result");
    try {
      const response = await postJSON(`/agents/${detail.agent_id}/probe`, {});
      const observation = response.observation || {};
      const outcome = outcomeLabel(observation.outcome);
      target.innerHTML = `<div class="notice">
          <p><strong>Latest on-demand re-probe:</strong>
            <span class="outcome ${outcome.className}">${escapeHTML(outcome.label)}</span>
            ${observation.status_code === null || observation.status_code === undefined ? "No HTTP status was returned." : `HTTP status ${escapeHTML(observation.status_code)}.`}
            Recorded <time datetime="${escapeHTML(observation.observed_at || "")}">${escapeHTML(displayTimestamp(observation.observed_at))}</time>.
          </p>
          <p>${escapeHTML(response.coverage_note || "This requested probe is not part of the snapshot's coverage figures.")}</p>
          <p class="dim">${escapeHTML(outcome.means)}</p>
        </div>`;
      if (observation.outcome === "responded") {
        reprobe.disabled = false;
        reprobe.textContent = "Re-probe now";
      } else {
        reprobe.textContent = "Re-probe recorded";
      }
    } catch (err) {
      renderError(target, err);
      reprobe.disabled = false;
      reprobe.textContent = "Re-probe now";
    }
  });
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
  const associatedServices = detail.associated_services.length
    ? detail.associated_services.map((service) => serviceCard(service)).join("")
    : `<p class="dim">Docket binds no service in its own marketplace to this identity.</p>`;
  const actions = agentActionBlock(detail, associatedServices);

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
    ${actions}
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
          <dt>Snapshot age</dt><dd class="num">${escapeHTML(fmtInt(cov.snapshot_age_seconds))} seconds</dd>
          <dt>Population swept</dt><dd class="mono">${escapeHTML(populationLabel(cov))}</dd>
          <dt>Agents sampled</dt><dd class="num">${escapeHTML(fmtInt(cov.sampled))}</dd>
          <dt>Agents expected</dt><dd class="num">${escapeHTML(fmtInt(cov.expected))}</dd>
          <dt>Dropped</dt><dd class="num">${escapeHTML(fmtInt(cov.dropped))}</dd>
          <dt>Complete</dt><dd>${cov.complete ? "yes" : "no"} — against the population above, not the registry</dd>
        </dl>
      </div>
    </section>`;
  bindAgentActions(detail);
}

async function initAgent() {
  const id = new URLSearchParams(window.location.search).get("id");
  const target = region("agent");
  if (!id) {
    region("snapshot").hidden = true;
    target.innerHTML = `<div class="panel panel-error" role="alert">
        <h1>No agent selected</h1>
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
    paintAgent(detail, id === WORKED_EXAMPLE_ID ? workedExample(detail) : "");
  } catch (err) {
    const line = region("snapshot");
    if (line) line.textContent = "Snapshot status unavailable.";
    renderError(target, err, "Agent unavailable");
  }
}

/* --------------------------------------------------------------- dispatch */

/* The page key follows the route; the functions follow what they do. /research serves
   the registry browser that used to be at /browse, and browsing is still what it does. */
const PAGES = {
  research: initBrowse,
  agent: initAgent,
  service: initService,
  pancake: initPancake,
};

const page = document.body.dataset.page;
if (Object.prototype.hasOwnProperty.call(PAGES, page)) {
  PAGES[page]();
}
