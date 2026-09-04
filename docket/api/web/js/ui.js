/* The render vocabulary the four pivot pages share: the stepper, the verification badges,
   the receipt block, and the one failure panel. Nothing here decides anything — it turns a
   state the server reported into markup, and it escapes everything on the way, because
   service names, agent names and error messages are all written by somebody else. */

import { escapeHTML, relativeTime } from "../app.js?v=13";

export { escapeHTML };

export const DASH = "—";

export function region(name, root = document) {
  return root.querySelector(`[data-region="${name}"]`);
}

/* ------------------------------------------------------------------- states */

/* The one-shot and persistent state machines from the pivot plan, in order. A state
   Docket has not declared is still rendered — as itself, marked unrecognised — because a
   page that silently drops a state it does not know tells the reader nothing went wrong. */
export const ONE_SHOT_STATES = [
  "quoted",
  "awaiting_wallet",
  "authorized",
  "paid_or_reserved",
  "queued",
  "running",
  "needs_approval",
  "completed",
];

export const PERSISTENT_STATES = [
  "quoted",
  "awaiting_wallet",
  "authorized",
  /* The server mints the session key on a background pass, so there is a state between
     "you signed for it" and "here is the address to fund". It is a step with a wait in
     it, not a gap, and the stepper says so. */
  "awaiting_session",
  "funded",
  "active",
  "paused",
];

export const TERMINAL_STATES = new Set([
  "completed",
  "failed",
  "refunded",
  "revoked",
  "expired",
]);

/* Requested and not finished. A revoke is only `revoked` once the sweep back to the owner
   has actually completed, so this state is the one the reader is on while their money is
   still moving — and it is neither active nor terminal. */
export const IN_FLIGHT_STATES = new Set(["revoking"]);

export const FAILED_STATES = new Set([
  "failed",
  "refunded",
  "revoked",
  "expired",
]);

const STATE_MEANS = {
  quoted: "Docket has priced the work. Nothing is committed.",
  awaiting_wallet: "Waiting for you to connect the wallet that will own this.",
  authorized: "You signed for it. Nothing has been paid yet.",
  paid_or_reserved:
    "The payment settled or was reserved against this activation.",
  funded: "The session address holds the funds you sent it.",
  queued: "Accepted and waiting for a runner.",
  running: "Running now.",
  needs_approval:
    "It stopped and needs a decision from you before it can go on.",
  active: "Running on its schedule, inside the limits you set.",
  awaiting_session:
    "Docket is minting the session key this will act through. Nothing can be funded until " +
    "it exists, and nothing is spent while you wait.",
  paused: "Held. It runs nothing until you resume it.",
  revoking:
    "Revoking. The session is stopped and the sweep back to your wallet has been started; " +
    "this becomes revoked once that sweep has completed.",
  completed: "Finished, with a result and a receipt.",
  failed: "It stopped without a result. The reason is recorded below.",
  refunded: "It did not deliver, and the payment was returned.",
  revoked: "You revoked it. The session was swept back to your wallet.",
  expired: "Its window closed before it finished.",
};

export function stateMeans(state) {
  return STATE_MEANS[state] || "Docket does not recognise this state.";
}

/** The state machine as a stepper: every state the activation can reach, which one it is
    on, and which it has already left. A terminal failure is shown where it happened
    rather than at the end, so the step it stopped on stays visible. */
export function stepper(activation) {
  const states =
    activation.kind === "persistent" ? PERSISTENT_STATES : ONE_SHOT_STATES;
  const current = String(activation.state || "");
  const failed = FAILED_STATES.has(current);
  const index = states.indexOf(current);
  const steps = states
    .map((state, position) => {
      const done = index >= 0 && position < index;
      const here = state === current;
      const status = here ? "current" : done ? "done" : "ahead";
      return `<li class="step" data-step="${escapeHTML(state)}" data-status="${status}"${
        here ? ' aria-current="step"' : ""
      }>
        <span class="step-name">${escapeHTML(state.replaceAll("_", " "))}</span>
      </li>`;
    })
    .join("");
  /* A state outside the declared run — a terminal failure, a sweep still in flight, or one
     this build has never heard of — is appended where it happened rather than dropped. A
     stepper that silently omits the state the reader is stuck on is worse than none: it
     shows a journey nobody is on. */
  const outcome =
    index >= 0
      ? ""
      : `<li class="step" data-step="${escapeHTML(current)}" data-status="${
          failed ? "failed" : "current"
        }" aria-current="step">
        <span class="step-name">${escapeHTML(current.replaceAll("_", " "))}</span>
      </li>`;
  return `<ol class="stepper" data-region="stepper" aria-label="Activation progress">
      ${steps}${outcome}
    </ol>
    <p class="dim" data-field="state-means">${escapeHTML(stateMeans(current))}</p>`;
}

/* ------------------------------------------------------------------- levels */

/* The six verification levels, weakest first. Each says what Docket did, not how good the
   agent is: `registered` means somebody wrote a record on chain and nothing more. */
export const VERIFICATION_LEVELS = [
  ["registered", "An identity exists on chain. Docket has not reached it."],
  ["endpoint_detected", "It declares an endpoint. Docket has not called it."],
  ["live", "A host answered at that endpoint, at some status."],
  ["payment_tested", "A payment challenge was exercised against it."],
  ["docket_tested", "Docket ran it and recorded the result."],
  [
    "docket_verified",
    "Docket ran it, settled a payment, and published the record.",
  ],
];

const LEVEL_MEANS = new Map(VERIFICATION_LEVELS);

/* The level a listing has to reach before Docket will offer it. The decision itself is
   the server's — every listing carries its own `hireable` — and this constant is here so
   the page can name that level when it explains why something is not offered. */
export const HIREABLE_FROM = "docket_tested";

/** Whether Docket offers this listing, read from the listing rather than derived from its
    level. The server owns that decision, and a page that recomputed it would eventually
    disagree with the server about what is for sale. */
export function isHireable(listing) {
  return Boolean(listing && listing.hireable === true);
}

/** The level badge, and beside it the one fact a level cannot state.

    `docket_tested` hangs off `live`, not off `payment_tested`, so a listing can stand at
    `docket_tested` with no payment challenge ever exercised against it. The level alone
    would read as though there had been one. The boolean is therefore rendered as its own
    badge from the listing's own `verification.payment_tested` and is never inferred from
    the level; a listing Docket has observed nothing about carries no level at all rather
    than the weakest one. */
export function verificationBadge(verification) {
  const record =
    verification && typeof verification === "object"
      ? verification
      : { level: verification };
  const name = record.level ? String(record.level) : "no level";
  const means = record.level
    ? LEVEL_MEANS.get(name) || "Docket does not recognise this level."
    : "Seen in the registry index. Docket has observed nothing about it.";
  const tested = record.payment_tested === true;
  const paymentMeans = tested
    ? "A payment challenge was exercised against it and answered."
    : "No payment challenge has been exercised against it. The level says nothing either way.";
  return `<span class="verify-badge" data-level="${escapeHTML(name)}" title="${escapeHTML(means)}">
      ${escapeHTML(name.replaceAll("_", " "))}
    </span>
    <span class="verify-badge" data-payment-tested="${tested ? "yes" : "no"}" title="${escapeHTML(paymentMeans)}">
      ${tested ? "payment tested" : "payment untested"}
    </span>`;
}

/* ------------------------------------------------------------------ failures */

/** A failure with a way out. Never a bare status, never a dead end: the code the server
    used, what it means for what the reader was doing, and the actions still open.

    `actions` are `{label, action}` pairs rendered as buttons the caller wires up, or
    `{label, href}` pairs rendered as links. A caller that passes none gets the panel with
    no controls, which is the right shape for a state the reader cannot act on.

    `level` is the heading level. It defaults to 3 because this panel usually replaces one
    region of a page that has its own `h1`; a failure that *is* the page passes 1, so the
    document is not served without a top-level heading. */
export function failurePanel(
  err,
  { heading = "", actions = [], note = "", level = 3 } = {},
) {
  const code =
    err && (err.code || err.error_code)
      ? err.code || err.error_code
      : "request_failed";
  const message = err && err.message ? err.message : "The request failed.";
  const controls = actions
    .map((action) =>
      action.href
        ? `<a class="btn" href="${escapeHTML(action.href)}">${escapeHTML(action.label)}</a>`
        : `<button type="button" class="btn" data-action="${escapeHTML(action.action)}">${escapeHTML(action.label)}</button>`,
    )
    .join("");
  return `<div class="panel panel-error" role="alert">
      ${heading ? `<h${level} tabindex="-1">${escapeHTML(heading)}</h${level}>` : ""}
      <p class="error-code">${escapeHTML(code)}</p>
      <p>${escapeHTML(message)}</p>
      ${note ? `<p class="dim">${escapeHTML(note)}</p>` : ""}
      ${controls ? `<p class="btn-row">${controls}</p>` : ""}
    </div>`;
}

export function renderFailure(container, err, options = {}) {
  if (!container) return;
  container.innerHTML = failurePanel(err, options);
}

/* ------------------------------------------------------------------ receipts */

/** A receipt as the reader can keep it: the JSON, a copy button, and a download.

    The download is built from a Blob rather than a data URI so a large receipt does not
    have to survive a URL-length limit. The object URL lives as long as the page does: it
    is a few hundred bytes, and revoking it after one click would break the second. */
export function receiptBlock(
  receipt,
  { filename = "docket-receipt.json" } = {},
) {
  const json = JSON.stringify(receipt, null, 2);
  return `<div class="receipt-block" data-receipt>
      <p class="btn-row">
        <button type="button" class="btn" data-copy-receipt>Copy receipt JSON</button>
        <a class="btn" data-download-receipt download="${escapeHTML(filename)}" href="#">Download receipt</a>
      </p>
      <pre class="receipt-json" data-receipt-json>${escapeHTML(json)}</pre>
      <p class="visually-hidden" role="status" aria-live="polite" data-copy-status></p>
    </div>`;
}

/** Wire every receipt block inside `root`. Safe to call again after a repaint. */
export function wireReceiptBlocks(root) {
  for (const block of root.querySelectorAll("[data-receipt]")) {
    const json = block.querySelector("[data-receipt-json]").textContent;
    const status = block.querySelector("[data-copy-status]");
    const link = block.querySelector("[data-download-receipt]");
    const blob = new Blob([json], { type: "application/json" });
    link.href = URL.createObjectURL(blob);
    block
      .querySelector("[data-copy-receipt]")
      .addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(json);
          status.textContent = "Receipt JSON copied to the clipboard.";
        } catch (err) {
          /* Clipboard access is refusable, and a silent no-op would read as a broken
           button. The JSON is on the page either way. */
          status.textContent =
            "This browser refused clipboard access. Select the JSON below and copy it.";
        }
      });
  }
}

/* -------------------------------------------------------------------- pieces */

export function definitionRows(rows) {
  return rows
    .filter(
      ([, value]) => value !== null && value !== undefined && value !== "",
    )
    .map(
      ([label, value]) =>
        `<dt>${escapeHTML(label)}</dt><dd>${escapeHTML(String(value))}</dd>`,
    )
    .join("");
}

export function timeAgo(iso) {
  return iso ? relativeTime(iso) : DASH;
}

/** Shorten an address for a table cell while keeping both ends readable. */
export function shortAddress(value) {
  const text = String(value || "");
  return text.length > 12
    ? `${text.slice(0, 6)}…${text.slice(-4)}`
    : text || DASH;
}
