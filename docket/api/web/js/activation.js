/* The activation page: one service, what it costs, what it is allowed to do, and the
   controls that start it.

   Two ways in. "Try free sample" runs the service on the free tier with no wallet at all,
   so a reader can see the shape of the answer before deciding anything. "Activate and pay"
   walks the x402 leg with the reader's own wallet and then binds the settled payment to an
   activation the reader owns. Nothing on this page holds a key, and nothing here decides
   whether the work is worth buying. */

import {
  exampleBody,
  fmtInt,
  inputControl,
  readForm,
  submissionBody,
  wireArrayControls,
} from "../app.js?v=13";
import * as api from "./api.js?v=13";
import * as payment from "./payment.js?v=13";
import * as wallet from "./wallet.js?v=13";
import {
  DASH,
  TERMINAL_STATES,
  definitionRows,
  escapeHTML,
  failurePanel,
  receiptBlock,
  region,
  renderFailure,
  stepper,
  timeAgo,
  wireReceiptBlocks,
} from "./ui.js?v=13";

/* Three seconds while something is plausibly about to happen, then ten once it clearly is
   not. A run that has been queued for a minute is waiting on a runner rather than on the
   next tick, and hammering the API twenty times a minute to learn that again is load
   Docket is paying for and the reader gains nothing from. */
const POLL_FAST_MS = 3000;
const POLL_SLOW_MS = 10000;
const POLL_SLOW_AFTER_MS = 60000;
/* Long enough for a queued run to reach a runner and finish, short enough that the page
   stops claiming to be watching something it has given up on. */
const POLL_BUDGET_MS = 600000;

const state = {
  record: null,
  kind: "one_shot",
  account: null,
  activation: null,
  poller: null,
  polling: false,
  pollingSince: 0,
  policyDefaults: null,
  pending: null,
  answer: null,
};

/* --------------------------------------------------------------- unit maths */

/* How many atomic units one whole token is, derived from the two figures the service
   publishes about its own price rather than from a decimals constant typed in here. A
   number written into this file would be a second source of truth for something the API
   already states, and it would go stale silently. */
function unitsPerToken(record) {
  const display = Number.parseFloat(String(record.price_display));
  const atomic = BigInt(String(record.price_atomic));
  if (!Number.isFinite(display) || display <= 0 || atomic <= 0n) return null;
  const hundredths = BigInt(Math.round(display * 100));
  if (hundredths <= 0n) return null;
  return (atomic * 100n) / hundredths;
}

/** A reader's decimal amount as atomic units of the service's asset, to six places. */
function toAtomic(record, amount) {
  const units = unitsPerToken(record);
  if (units === null) return null;
  const millionths = BigInt(Math.round(Number(amount) * 1e6));
  if (millionths < 0n) return null;
  return (millionths * units) / 1000000n;
}

function assetSymbol(record) {
  const parts = String(record.price_display).trim().split(/\s+/);
  return parts.length > 1 ? parts[parts.length - 1] : "tokens";
}

/* ------------------------------------------------------------------ listing */

/* What activating this service puts at risk, written from what the service record and the
   reader's own choices actually say. A one-shot hire has one money movement and no standing
   permission; that is worth stating plainly rather than leaving a reader to assume the
   worst or, worse, the best. */
function permissionsCopy(record, kind) {
  if (kind === "persistent") {
    return (
      "A session key Docket generates acts inside the limits you set below and nothing " +
      "outside them. It can call only the contracts and functions its category declares, " +
      "spend no more than the caps you set, and it stops at the expiry you choose. You can " +
      "pause or revoke it at any time from My agents."
    );
  }
  return (
    `At most two wallet actions: if your existing allowance is short, Docket requests ` +
    `exactly ${escapeHTML(record.price_display)} for the B402 relayer, then asks for one ` +
    "signed authorization for the same amount. Docket never requests more than the exact " +
    "price and never reduces or revokes an allowance you granted before."
  );
}

function custodyCopy(record, kind) {
  if (kind === "persistent") {
    return (
      "Docket generates a session address and holds its key on the server. It holds only " +
      "what you send it. Revoking sweeps every allowlisted token and the remaining BNB, " +
      "less gas, back to the wallet that owns the activation."
    );
  }
  return (
    `No custody. ${escapeHTML(record.price_display)} moves once, from your wallet to the ` +
    "recipient named in the payment challenge, and Docket never holds it."
  );
}

function evidenceList(record) {
  if (!record.evidence || !record.evidence.length) {
    return '<p class="dim">No recorded run is published for this service yet.</p>';
  }
  return `<ul class="facts">${record.evidence
    .map(
      (ref) =>
        `<li><a href="${escapeHTML(ref.url)}">${escapeHTML(ref.label)}</a></li>`,
    )
    .join("")}</ul>`;
}

function paintListing() {
  const record = state.record;
  const identity = record.agent_path
    ? `${escapeHTML(record.identity)} <a href="${escapeHTML(record.agent_path)}">Read what Docket observed of it</a>.`
    : escapeHTML(record.identity);
  region("listing").innerHTML = `<h1>${escapeHTML(record.name)}</h1>
    <p class="lede">${escapeHTML(record.what_you_get)}</p>
    <p>
      <span class="badge">${escapeHTML(record.category_job || "Outside the four job categories")}</span>
      <span class="badge" data-field="stock-badge">${escapeHTML(
        record.paid_stock ? "paid stock" : record.stock_status,
      )}</span>
    </p>
    <div class="panel">
      <dl class="deflist">
        <dt>Job</dt><dd>${escapeHTML(record.category_job || "Outside the four job categories")}</dd>
        <dt>Identity</dt><dd>${identity}</dd>
        <dt>Price</dt><dd class="num">${escapeHTML(record.price_display)}
          (<span class="mono">${escapeHTML(record.price_atomic)}</span> atomic units of
          <span class="mono">${escapeHTML(record.asset)}</span>)</dd>
        <dt>Permissions</dt><dd data-field="permissions">${permissionsCopy(record, state.kind)}</dd>
        <dt>Custody</dt><dd data-field="custody">${custodyCopy(record, state.kind)}</dd>
        <dt>Typical run, declared</dt><dd class="num">${escapeHTML(fmtInt(record.typical_seconds))} seconds</dd>
        <dt>What activating does</dt><dd>${escapeHTML(record.activation_means)}</dd>
      </dl>
    </div>
    <section aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">The record behind it</h2>
      <div class="panel">${evidenceList(record)}</div>
    </section>
    <section aria-labelledby="limits-of-service-heading">
      <h2 id="limits-of-service-heading">What it cannot do</h2>
      <div class="notice notice-warn"><p>${escapeHTML(record.limitations)}</p></div>
    </section>`;
  document.title = `Activate ${record.name} — Docket`;
}

function refreshPermissionCopy() {
  const permissions = document.querySelector('[data-field="permissions"]');
  const custody = document.querySelector('[data-field="custody"]');
  if (permissions)
    permissions.innerHTML = permissionsCopy(state.record, state.kind);
  if (custody) custody.innerHTML = custodyCopy(state.record, state.kind);
}

/* --------------------------------------------------------------------- form */

function sampleForm(record) {
  const fields = Object.entries(record.input_schema);
  const control = ([name, field]) => `<div class="field">
      <label for="field-${escapeHTML(name)}">${escapeHTML(name)}${field.required ? "" : " (optional)"}</label>
      ${inputControl(name, field)}
      <p class="dim">${escapeHTML(field.description || "")}</p>
      ${field.example_note ? `<p class="example-note">${escapeHTML(field.example_note)}</p>` : ""}
    </div>`;
  const plain = fields.filter(([, field]) => field.advanced !== true);
  const advanced = fields.filter(([, field]) => field.advanced === true);
  const body = plain.length
    ? plain.map(control).join("")
    : `<p class="dim">This service takes no arguments: what arrives is whatever was last
        published, so there is nothing for you to supply.</p>`;
  const reproducibility = advanced.length
    ? `<details class="advanced">
        <summary>Advanced — reproducibility</summary>
        <div class="advanced-fields">${advanced.map(control).join("")}</div>
      </details>`
    : "";
  const worked = fields.some(([, field]) => Boolean(field.example_note));
  return `<form class="activate" data-sample-form novalidate>
      ${body}
      ${reproducibility}
      <p class="btn-row">
        <button type="submit" class="btn" data-run-sample>Try free sample</button>
        ${worked ? '<button type="submit" class="btn" data-example>Use the worked example</button>' : ""}
      </p>
    </form>`;
}

/* The limits a persistent session runs inside, in the units a reader thinks in. Only the
   fields set here are sent: the contract and function allowlists belong to the executor
   for this category, and a browser that guessed at them would either forbid the work or
   permit more than the reader agreed to. */
/** A whole-token amount rendered from atomic units, for prefilling a cap the server
    proposed. Falls back to the supplied default when the units cannot be derived. */
function fromAtomic(record, atomic, fallback) {
  const units = unitsPerToken(record);
  if (units === null || atomic === undefined || atomic === null)
    return fallback;
  try {
    return String(Number((BigInt(String(atomic)) * 1000000n) / units) / 1e6);
  } catch (cause) {
    return fallback;
  }
}

/* The cap for the token this page priced in, which is the one the reader is being shown a
   figure for. The skeleton carries caps for every token its category allows; picking the
   first would prefill the box with a limit for some other token. */
function capFor(map, asset) {
  const caps = map || {};
  if (caps[asset] !== undefined) return caps[asset];
  const rows = Object.values(caps);
  return rows.length ? rows[0] : null;
}

/* What the session may touch, exactly as the server declared it and not editable here.

   These lists belong to the category's executor. The browser has no standing to widen them
   and no way to know what belongs in them, so it shows them and sends them back unchanged.
   Showing them is the point: a reader agreeing to a bounded session should be able to see
   what the bound actually is, rather than agreeing to the word "bounded". */
function allowlistPanel(defaults) {
  const rows = [
    ["Contracts it may call", defaults.contract_allowlist],
    ["Functions it may call", defaults.function_allowlist],
    ["Tokens it may move", defaults.token_allowlist],
  ];
  return `<div class="panel">
      <h4>What this session may touch</h4>
      <p class="dim">Set by the category this service stands in, not by you and not by this
        page. Anything outside these lists is refused before it is sent.</p>
      <dl class="deflist">
        ${rows
          .map(
            ([label, list]) =>
              `<dt>${escapeHTML(label)}</dt><dd class="mono wrap-anywhere">${
                (list || []).length
                  ? (list || []).map((item) => escapeHTML(item)).join(", ")
                  : "none declared"
              }</dd>`,
          )
          .join("")}
      </dl>
    </div>`;
}

function limitsForm(record, defaults) {
  const symbol = assetSymbol(record);
  const total = fromAtomic(
    record,
    capFor(defaults.total_cap_atomic, record.asset),
    "10",
  );
  const perAction = fromAtomic(
    record,
    capFor(defaults.per_action_limit_atomic, record.asset),
    "1",
  );
  const slippage =
    defaults.max_slippage_bps === undefined ||
    defaults.max_slippage_bps === null
      ? "50"
      : String(defaults.max_slippage_bps);
  const gasGwei = defaults.max_gas_price_wei
    ? String(
        Number(BigInt(String(defaults.max_gas_price_wei)) / 1000000n) / 1000,
      )
    : "5";
  return `${allowlistPanel(defaults)}
    <form class="activate limits-form" data-limits-form novalidate>
      <div class="field">
        <label for="limit-total">Total cap (${escapeHTML(symbol)})</label>
        <input id="limit-total" name="total_cap" type="number" step="any" min="0" value="${escapeHTML(total)}" required />
        <p class="dim">The most this session may spend in total before it stops.</p>
      </div>
      <div class="field">
        <label for="limit-action">Per-action limit (${escapeHTML(symbol)})</label>
        <input id="limit-action" name="per_action_limit" type="number" step="any" min="0" value="${escapeHTML(perAction)}" required />
        <p class="dim">The most any single transaction it sends may move.</p>
      </div>
      <div class="field">
        <label for="limit-slippage">Maximum slippage (basis points)</label>
        <input id="limit-slippage" name="max_slippage_bps" type="number" step="1" min="0" max="10000" value="${escapeHTML(slippage)}" required />
        <p class="dim">50 is 0.50%. A swap that would cost more than this is not sent.</p>
      </div>
      <div class="field">
        <label for="limit-gas">Maximum gas price (gwei)</label>
        <input id="limit-gas" name="max_gas_price_gwei" type="number" step="any" min="0" value="${escapeHTML(gasGwei)}" required />
        <p class="dim">Nothing is sent while the network costs more than this.</p>
      </div>
      <div class="field">
        <label for="limit-expiry">Expires in (days)</label>
        <input id="limit-expiry" name="expires_days" type="number" step="1" min="1" max="365" value="30" required />
        <p class="dim">The session stops permanently at that point, whether or not you revoke it.</p>
      </div>
    </form>`;
}

function readPolicy() {
  const form = document.querySelector("[data-limits-form]");
  if (!form || state.kind !== "persistent") return null;
  if (!state.policyDefaults) {
    throw new api.ApiError(
      "policy_defaults_missing",
      "Docket has not said what this session would be allowed to touch, so there is " +
        "nothing here to agree to yet.",
    );
  }
  const record = state.record;
  const number = (name) => Number(form.elements.namedItem(name).value);
  const total = toAtomic(record, number("total_cap"));
  const perAction = toAtomic(record, number("per_action_limit"));
  if (total === null || perAction === null || total <= 0n || perAction <= 0n) {
    throw new api.ApiError(
      "invalid_limits",
      "The caps must be positive amounts written in decimal.",
    );
  }
  if (perAction > total) {
    throw new api.ApiError(
      "invalid_limits",
      "The per-action limit cannot be larger than the total cap.",
    );
  }
  const days = Math.trunc(number("expires_days"));
  const expiresAt = new Date(Date.now() + days * 86400000)
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z");
  const defaults = state.policyDefaults;
  /* The skeleton goes back whole. The three allowlists are the category's and are not this
     page's to edit; the cap maps cover every token the category allows, and replacing them
     with a single entry for this service's asset would quietly drop the limits on all the
     others. Only the fields the form actually rendered are overwritten, and `expires_at` is
     added because it is the one bound the server deliberately leaves to the owner. */
  return {
    ...defaults,
    per_action_limit_atomic: {
      ...(defaults.per_action_limit_atomic || {}),
      [record.asset]: perAction.toString(),
    },
    total_cap_atomic: {
      ...(defaults.total_cap_atomic || {}),
      [record.asset]: total.toString(),
    },
    max_slippage_bps: Math.trunc(number("max_slippage_bps")),
    max_gas_price_wei: (
      BigInt(Math.round(number("max_gas_price_gwei") * 1e6)) * 1000n
    ).toString(),
    expires_at: expiresAt,
  };
}

function readInputs() {
  const form = document.querySelector("[data-sample-form]");
  const body = readForm(state.record, form);
  const missing = Object.entries(state.record.input_schema)
    .filter(([name, field]) => {
      if (!field.required) return false;
      if (field.type === "array") {
        /* The field name comes from the service record, so it is not this module's to
           assume selector-safe: one carrying a quote would break out of the attribute. */
        const container = form.querySelector(
          `[data-array-control="${CSS.escape(name)}"]`,
        );
        return (
          container &&
          !Array.from(container.querySelectorAll("input")).some((input) =>
            input.value.trim(),
          )
        );
      }
      const control = form.elements.namedItem(name);
      return control && !control.value.trim();
    })
    .map(([name]) => name);
  if (missing.length) {
    throw new api.ApiError(
      "missing_field",
      `${state.record.service_id} needs ${missing.join(", ")}.`,
    );
  }
  return body;
}

/* -------------------------------------------------------------- progress log */

function say(message) {
  const log = region("progress");
  const line = document.createElement("li");
  line.textContent = message;
  log.appendChild(line);
  region("live-status").textContent = message;
}

function resetProgress() {
  region("progress").innerHTML = "";
  region("live-status").textContent = "";
}

/* ----------------------------------------------------------------- outcomes */

function paintResult(answer, { free }) {
  const outcome = region("outcome");
  const receipt = answer.receipt || {};
  const heading = free ? "Free sample result" : "Result";
  const note = free
    ? "This ran on the free tier. Nothing was charged, no wallet was used, and no " +
      "activation was created — it is the shape of the answer, not a hired run."
    : "This result is bound to the receipt below by the input and output hashes it carries.";
  outcome.innerHTML = `<section aria-labelledby="outcome-heading">
      <h2 id="outcome-heading" tabindex="-1">${escapeHTML(heading)}</h2>
      <p class="section-note">${escapeHTML(note)}</p>
      <div class="panel">
        <pre class="result-json">${escapeHTML(JSON.stringify(answer.result, null, 2))}</pre>
      </div>
    </section>
    <section aria-labelledby="receipt-heading">
      <h2 id="receipt-heading">The receipt</h2>
      <div class="panel">
        <dl class="deflist">
          ${definitionRows([
            ["Service", receipt.service],
            ["Delivered at", receipt.delivered_at],
            ["Input hash", receipt.input_hash],
            ["Output hash", receipt.output_hash],
            ["Payment", (receipt.payment || {}).status],
            ["Payment ID", (receipt.payment || {}).payment_id],
            ["Authorization nonce", (receipt.payment || {}).nonce],
            ["Settlement transaction", (receipt.payment || {}).transaction_id],
          ])}
        </dl>
        ${receiptBlock(receipt, {
          filename: `docket-receipt-${state.record.service_id}.json`,
        })}
        <p class="dim">A receipt records delivery and nothing else. It does not assert the
          work is correct, and Docket does not sign it. Both hashes are plain SHA-256 over
          canonical JSON; <a href="/llms.txt">/llms.txt</a> carries the recipe.</p>
      </div>
    </section>`;
  wireReceiptBlocks(outcome);
  outcome.querySelector("#outcome-heading").focus();
}

/* Every failure this page can reach, with the action that is actually still open. A code
   with no way forward is a dead end, and a retry offered where the state machine forbids
   one is worse than none: it spends a second payment on work already bought. */
const RECOVERY = {
  user_rejected: {
    heading: "You dismissed the wallet prompt",
    note: "Nothing was signed, nothing was sent, and nothing was charged.",
    actions: [{ label: "Start the payment again", action: "retry-payment" }],
  },
  no_wallet: {
    heading: "No wallet is available",
    note:
      "Docket holds no key of yours, so a paid activation needs a wallet in this browser. " +
      "The free sample below still runs without one.",
    actions: [{ label: "Try the free sample instead", action: "run-sample" }],
  },
  request_pending: {
    heading: "A wallet prompt is already open",
    note: "Finish or dismiss the prompt your wallet is showing, then start again.",
    actions: [{ label: "Start the payment again", action: "retry-payment" }],
  },
  wrong_chain: {
    heading: "The wallet is not on BNB Smart Chain",
    note: "Docket settles on BSC only. Switch the network, then start again.",
    actions: [{ label: "Switch and start again", action: "retry-payment" }],
  },
  /* No fresh-payment button here, deliberately. A replay refusal means that authorization
     reached Docket and was already spent, so the work behind it is bought; offering to
     sign another from this panel is a second purchase of the same thing, one click from a
     reader who has just been told something went wrong. */
  authorization_replay: {
    heading: "That authorization was already used",
    note:
      "An authorization is spendable once, and this one has been spent — which means the " +
      "work it paid for was bought. It is on My agents, with its receipt. Do not sign a " +
      "second payment for it.",
    actions: [{ label: "Check My agents", href: "/my-agents" }],
  },
  payment_not_verified: {
    heading: "The facilitator rejected the payment",
    note:
      "No work ran and no charge was attempted. This is usually an allowance or a balance " +
      "that is short of the price.",
    actions: [
      { label: "Check the allowance and sign again", action: "retry-payment" },
    ],
  },
  payment_invalid: {
    heading: "Docket could not read the payment",
    note: "No work ran and no charge was attempted.",
    actions: [{ label: "Sign a fresh payment", action: "retry-payment" }],
  },
  /* The one case where resending is safe, and the only one. The same signed bytes are
     either already spent — in which case Docket answers 409 and nothing is bought twice —
     or they never arrived, in which case they settle once. Signing a *new* authorization
     here is what would double-purchase, so that is not offered; the resend is filled in at
     render time because it is only offered while the signature is still inside its own
     `validBefore`. */
  payment_outcome_unknown: {
    heading: "The connection dropped mid-payment",
    note:
      "Docket cannot tell from here whether that authorization reached it. Resending the " +
      "same signed authorization is safe: if it settled, Docket refuses it as a replay; " +
      "if it never arrived, it settles once. Signing a new one is not safe and is not " +
      "offered.",
    actions: [{ label: "Check My agents", href: "/my-agents" }],
  },
  settlement_pending_reconciliation: {
    heading: "A settlement was attempted and its outcome is unknown",
    note:
      "Docket will not retry it automatically, and neither should you. The activation " +
      "stays where it is until the payment is reconciled.",
    actions: [{ label: "Check My agents", href: "/my-agents" }],
  },
  service_failed: {
    heading: "The service could not complete the request",
    note: "No settlement ran, so nothing was charged for it.",
    actions: [{ label: "Run it again", action: "retry-payment" }],
  },
  not_for_sale: {
    heading: "This service is not admitted to paid stock",
    note: "There is nothing to pay for yet. It runs on the free tier instead.",
    actions: [{ label: "Try the free sample", action: "run-sample" }],
  },
  settlement_unavailable: {
    heading: "Live settlement is not enabled on this process",
    note:
      "The service passed its admission gate, but this Docket is not configured to settle " +
      "payments. No work ran and no charge was attempted.",
    actions: [{ label: "Try the free sample", action: "run-sample" }],
  },
  free_tier_exhausted: {
    heading: "The free allowance for this caller is spent",
    note: "It refills on its own. A paid activation is not rate limited.",
    actions: [{ label: "Activate and pay instead", action: "retry-payment" }],
  },
  hire_rate_limited: {
    heading: "The free allowance for this caller is spent",
    note: "It refills on its own.",
    actions: [],
  },
  receipt_timeout: {
    heading: "The approval transaction has not been mined",
    note:
      "It may still confirm. Check it in your wallet before sending another — a second " +
      "approval would be a second transaction, not a replacement.",
    actions: [{ label: "Check and start again", action: "retry-payment" }],
  },
  poll_timeout: {
    heading: "Docket stopped watching this activation",
    note:
      "It was still running when this page stopped polling. The work was not cancelled and " +
      "the activation is unchanged.",
    actions: [{ label: "Check it now", action: "poll-once" }],
  },
};

/* The one recovery that depends on the clock. Resending the same signature is safe only
   while the server would still accept it on time; once the window has closed the only
   honest thing left is the identifier the reader can quote to a person, because a fresh
   signature would risk paying twice for work that may already be bought. */
/* Whether the signed authorization could still be accepted, on the server's clock. The
   browser's own reading is not the one that decides: the server compares `validBefore`
   against its `now`, and the offset measured when the challenge arrived is the only thing
   here that knows the difference between the two. */
function pendingIsLive(pending) {
  const serverNow = Math.floor(Date.now() / 1000) + (pending.clockOffset || 0);
  return serverNow < pending.validBefore;
}

/* A payment that settled with an activation not yet bound to it. Everything that costs
   money has already happened, so the only thing on offer is binding it again — never the
   flow that would pay a second time. */
const BIND_ONLY_CODES = new Set([
  "bad_signature",
  "not_owner",
  "stale_nonce",
  "network_error",
  "account_changed",
  "no_account",
  "user_rejected",
  "unsafe_message",
  "illegal_transition",
]);

function bindOnlyRecovery(err) {
  return {
    heading: "The payment settled, and the activation is not bound to it yet",
    note:
      "The work is bought and its receipt is above. What failed was recording which " +
      `activation it belongs to (${err.code || err.error_code}). Binding again costs ` +
      "nothing and pays nothing.",
    actions: [
      { label: "Bind it again", action: "bind-only" },
      { label: "Check My agents", href: "/my-agents" },
    ],
  };
}

function lostResponseRecovery(recovery) {
  const pending = state.pending;
  if (!pending) return recovery;
  const expired = !pendingIsLive(pending);
  if (expired || pending.resent) {
    return {
      ...recovery,
      note:
        `That authorization's window has ${expired ? "closed" : "been used"}, so there is ` +
        "nothing safe left to send. Quote this authorization nonce to support and they " +
        `can say whether it settled: ${pending.nonce}. Do not sign a new payment for the ` +
        "same work first.",
      actions: [{ label: "Check My agents", href: "/my-agents" }],
    };
  }
  return {
    ...recovery,
    actions: [
      { label: "Resend the same authorization", action: "resend-payment" },
      ...recovery.actions,
    ],
  };
}

function paintFailure(err) {
  const code = err && (err.code || err.error_code);
  let recovery = RECOVERY[code] || {
    heading: "That step did not complete",
    note: "Nothing beyond what is listed above was done.",
    actions: [{ label: "Start again", action: "retry-payment" }],
  };
  if (code === "payment_outcome_unknown") {
    recovery = lostResponseRecovery(recovery);
  } else if (state.answer && BIND_ONLY_CODES.has(code)) {
    recovery = bindOnlyRecovery(err);
  }
  const outcome = region("outcome");
  outcome.innerHTML = failurePanel(err, recovery);
  const heading = outcome.querySelector("h3");
  if (heading) heading.focus();
  region("live-status").textContent = `${recovery.heading}.`;
}

/* --------------------------------------------------------------- activations */

/** What happened to this activation, in the server's own words.

    Every accepted change appends an event carrying the reason for it, which is the only
    place a reader can learn *why* a run failed rather than only that it did — the failure
    copy says "the reason is recorded below", and this is below.

    An event whose `from_state` equals its `to_state` is a note rather than a transition:
    something worth recording that moved nothing. Rendering it with an arrow would invent a
    change the server did not make, so it is rendered as the note it is. */
function activationLog(activation) {
  const events = activation.events || [];
  if (!events.length) return "";
  return `<section aria-labelledby="log-heading">
      <h3 id="log-heading">What happened</h3>
      <div class="panel">
        <ul class="facts" data-region="events">
          ${events
            .map((event) => {
              const note = event.from_state === event.to_state;
              const label = note
                ? escapeHTML(event.to_state || "note")
                : `${escapeHTML(event.from_state || "start")} → ${escapeHTML(event.to_state || "")}`;
              return `<li data-event="${note ? "note" : "transition"}">
                  <strong>${label}</strong>
                  ${event.reason ? `— ${escapeHTML(event.reason)}` : ""}
                  <span class="dim">${escapeHTML(event.actor || "docket")},
                    ${escapeHTML(timeAgo(event.at))}</span>
                </li>`;
            })
            .join("")}
        </ul>
      </div>
    </section>`;
}

function paintActivation() {
  const activation = state.activation;
  const target = region("activation");
  if (!activation) {
    target.innerHTML = "";
    target.hidden = true;
    return;
  }
  target.hidden = false;
  const session = activation.session || {};
  const spent = Object.entries(session.spent_atomic || {})
    .map(([token, amount]) => `${amount} of ${token}`)
    .join(", ");
  target.innerHTML = `<h2 id="activation-heading" tabindex="-1">Your activation</h2>
    ${stepper(activation)}
    <div class="panel">
      <dl class="deflist">
        ${definitionRows([
          ["Activation", activation.activation_id],
          ["Service", activation.service_id],
          ["Kind", activation.kind],
          ["Owner", activation.owner],
          ["State", activation.state],
          ["Opened", timeAgo(activation.created_at)],
          ["Last change", timeAgo(activation.updated_at)],
          ["Session address", session.address],
          ["Spent", spent],
        ])}
      </dl>
    </div>
    ${activationLog(activation)}
    <div data-region="next-action"></div>`;
  paintNextAction();
}

/* What the reader has to do next, as the server declared it. The page never invents a
   step: an activation whose `next_action` is `wait` or `none` gets no control, because
   offering one would ask for a signature the server has no use for. */
function paintNextAction() {
  const activation = state.activation;
  const target = region("next-action");
  if (!target || !activation) return;
  const next = activation.next_action || { kind: "none", detail: {} };
  const detail = next.detail || {};
  if (next.kind === "fund_session" || next.kind === "approve_nft") {
    /* Two kinds of requirement, and they are not the same request. `fund_session` asks for
       a token transfer and names an amount; `approve_nft` asks the owner to approve one
       position to the session and names a contract and a token id. Each carries whether it
       has been satisfied and, once it has, the transaction that satisfied it — rendering
       only the amounts would leave a reader who has already sent one of two unable to tell
       which is still owed. */
    const requirements = (detail.requirements || [])
      .map((row) => {
        const what =
          row.kind === "approve_nft"
            ? `position <span class="mono">${escapeHTML(row.token_id)}</span> on
               <span class="mono">${escapeHTML(row.contract)}</span>`
            : `<span class="mono">${escapeHTML(row.amount_atomic)}</span> atomic units of
               <span class="mono">${escapeHTML(row.token || "BNB")}</span>`;
        return `<li data-requirement="${escapeHTML(row.kind || "fund_session")}" data-satisfied="${row.satisfied ? "yes" : "no"}">
             ${what}
             — ${row.satisfied ? "received" : "still owed"}
             ${row.tx_hash ? `<span class="mono wrap-anywhere">${escapeHTML(row.tx_hash)}</span>` : ""}
           </li>`;
      })
      .join("");
    const outstanding = (detail.requirements || []).filter(
      (row) => !row.satisfied,
    );
    target.innerHTML = `<div class="panel">
        <h3>Fund the session</h3>
        <p>Send what is still owed to the session address from your own wallet, then paste
          the transaction hash so Docket can confirm the funding at a block.</p>
        <p class="mono wrap-anywhere">${escapeHTML(detail.session_address || (activation.session || {}).address || DASH)}</p>
        <ul class="facts">${requirements || "<li>No amount was named.</li>"}</ul>
        ${
          outstanding.length
            ? ""
            : '<p class="dim">Everything this session needs has been received.</p>'
        }
        ${detail.gas_allowance_wei ? `<p class="dim">Plus <span class="mono">${escapeHTML(detail.gas_allowance_wei)}</span> wei of BNB for gas.</p>` : ""}
        <form data-fund-form novalidate>
          <div class="field">
            <label for="fund-hash">Funding transaction hash</label>
            <input id="fund-hash" name="tx_hash" type="text" inputmode="latin"
              pattern="0x[0-9a-fA-F]{64}" placeholder="0x…" required />
            <p class="dim">Docket reads the balances at that transaction's block. It never
              asks for a key and cannot move the funds itself until the session is active.</p>
          </div>
          <p class="btn-row">
            <button type="submit" class="btn btn-primary" data-fund>Fund session</button>
          </p>
        </form>
      </div>`;
    target
      .querySelector("[data-fund-form]")
      .addEventListener("submit", onFundSession);
    return;
  }
  if (next.kind === "sign_transaction" || next.kind === "approve_nft") {
    target.innerHTML = `<div class="panel">
        <h3>This run needs your signature</h3>
        <p>${escapeHTML(detail.purpose || "Docket prepared a call it cannot send without you.")}</p>
        <p class="btn-row">
          <button type="button" class="btn btn-primary" data-sign-prepared>Review and sign</button>
        </p>
        <div data-region="prepared"></div>
      </div>`;
    target
      .querySelector("[data-sign-prepared]")
      .addEventListener("click", onSignPrepared);
    return;
  }
  /* Nothing for the reader to do. The stepper already carries what the state means, and
     printing the same sentence twice on one screen reads as two different claims. */
  if (next.kind === "wait" || next.kind === "none") {
    target.innerHTML = "";
    return;
  }
  target.innerHTML = `<p class="dim">Next: ${escapeHTML(next.kind.replaceAll("_", " "))}.</p>`;
}

function stopPolling() {
  if (state.poller !== null) {
    window.clearTimeout(state.poller);
    state.poller = null;
  }
  state.polling = false;
}

/* A chain of timeouts rather than an interval: an interval fires on a schedule regardless
   of whether the last request came back, so a slow API ends up with several reads in
   flight against one activation and the last one to land wins — which is not necessarily
   the newest. Each read is scheduled only once the previous one has finished. */
function startPolling() {
  stopPolling();
  state.pollingSince = Date.now();
  if (!state.activation || TERMINAL_STATES.has(state.activation.state)) return;
  schedulePoll();
}

function schedulePoll() {
  const elapsed = Date.now() - state.pollingSince;
  const wait = elapsed >= POLL_SLOW_AFTER_MS ? POLL_SLOW_MS : POLL_FAST_MS;
  state.poller = window.setTimeout(pollOnce, wait);
}

async function pollOnce() {
  /* The timeout that fired this has run; clearing the handle keeps `stopPolling` from
     cancelling a timer that no longer exists while a fresh one is being scheduled. */
  state.poller = null;
  if (!state.activation || state.polling) return;
  if (Date.now() - state.pollingSince > POLL_BUDGET_MS) {
    stopPolling();
    paintFailure(
      new api.ApiError(
        "poll_timeout",
        `This page watched activation ${state.activation.activation_id} for ` +
          `${Math.round(POLL_BUDGET_MS / 1000)} seconds and it has not reached a final state.`,
      ),
    );
    return;
  }
  state.polling = true;
  try {
    state.activation = await api.getActivation(state.activation.activation_id);
  } catch (err) {
    stopPolling();
    paintFailure(err);
    return;
  } finally {
    state.polling = false;
  }
  paintActivation();
  if (state.activation.result) {
    paintResult(
      {
        result: state.activation.result,
        receipt: (state.activation.receipts || [])[0],
      },
      { free: false },
    );
  }
  if (TERMINAL_STATES.has(state.activation.state)) stopPolling();
  else schedulePoll();
}

/* ------------------------------------------------------------------- actions */

function busy(on) {
  for (const button of document.querySelectorAll(
    "[data-run-sample], [data-pay], [data-example]",
  )) {
    button.disabled = on;
  }
  region("outcome").setAttribute("aria-busy", on ? "true" : "false");
}

async function runSample(useExample = false) {
  const form = document.querySelector("[data-sample-form]");
  const example = form.querySelector("[data-example]");
  let body;
  try {
    /* `submissionBody` resets the visible form to the worked example before returning it,
       so the reader sees the request that produced the answer rather than a result with
       no visible input. A service with no worked example has no such button, and the
       recorded defaults are all there is to send. */
    body =
      useExample && example
        ? submissionBody(state.record, form, example)
        : useExample
          ? exampleBody(state.record)
          : readInputs();
  } catch (err) {
    paintFailure(err);
    return;
  }
  busy(true);
  resetProgress();
  say(`Running ${state.record.name} on the free tier.`);
  try {
    paintResult(await api.runFreeSample(state.record.service_id, body), {
      free: true,
    });
    say("The free sample returned a result.");
  } catch (err) {
    paintFailure(err);
  } finally {
    busy(false);
  }
}

async function activateAndPay() {
  let inputs;
  let policy;
  try {
    inputs = readInputs();
    policy = readPolicy();
  } catch (err) {
    paintFailure(err);
    return;
  }
  busy(true);
  resetProgress();
  try {
    say("Connecting the wallet.");
    state.account = await wallet.connect();
    say(`Connected ${state.account}.`);
    await wallet.ensureBsc();
    say("Wallet is on BNB Smart Chain.");

    say("Opening the activation.");
    const opened = await api.activationNonce(
      state.account,
      state.record.service_id,
    );
    const createSignature = await wallet.personalSign(
      opened.message,
      state.account,
    );
    state.activation = await api.createActivation({
      service_id: state.record.service_id,
      kind: state.kind,
      owner: state.account,
      owner_signature: createSignature,
      nonce: opened.nonce,
      inputs,
      policy,
    });
    paintActivation();
    say(`Activation ${state.activation.activation_id} is open.`);

    /* A persistent session is funded from the reader's wallet, not bought with an x402
       authorization; the page stops here and the funding control takes over. */
    if (state.kind === "persistent") {
      say("Send the session its funding to start it.");
      startPolling();
      return;
    }

    /* The server quoted this activation, and the quote is what it costs — not the
       catalogue card. A service outside paid stock is quoted on the free tier; asking it
       for payment terms gets a 200 and a run the activation never hears about, and leaves
       the activation open behind a dead end. The free tier's contract is approve, and the
       service runs. */
    if (state.activation.quote && state.activation.quote.payment_scheme === "free_tier") {
      await approveFreeTier();
      return;
    }

    say("Asking for the exact payment terms.");
    let challenge = await payment.fetchChallenge(
      state.record.service_id,
      inputs,
    );
    let terms = assertTermsMatchTheQuote(payment.paymentTerms(challenge));
    say(
      `Terms: ${terms.amountAtomic} atomic units of ${terms.token} to ${terms.payTo}.`,
    );

    say("Checking the relayer's allowance.");
    const allowance = await payment.ensureAllowance(
      state.account,
      terms.token,
      terms.spender,
      terms.amountAtomic,
    );
    say(
      allowance.approved
        ? `Approved exactly ${terms.amountAtomic} in ${allowance.tx_hash}.`
        : "The existing allowance already covers the price; nothing was approved.",
    );

    /* An approval can take several blocks, and the offer is only good for so long. A
       signature against terms the server has since replaced is refused for a reason the
       reader has no way to see, so the offer is taken again rather than assumed. */
    if (payment.challengeIsStale(challenge)) {
      say(
        "The offer went stale while the approval was mined. Asking for it again.",
      );
      challenge = await payment.fetchChallenge(state.record.service_id, inputs);
      terms = assertTermsMatchTheQuote(payment.paymentTerms(challenge));
    }

    say("Signing the payment authorization.");
    const envelope = await payment.signPayment(state.account, challenge);
    const header = payment.encodePaymentHeader(envelope);
    /* Held so a dropped response can resend these exact bytes rather than sign new ones.
       The window is the authorization's own: past `validBefore` the server refuses it on
       time, so resending stops being a recovery and becomes a wasted round trip. */
    state.pending = {
      header,
      envelope,
      inputs,
      validBefore: Number(envelope.payload.authorization.validBefore),
      /* The offset the signature was built against, so the window is re-checked on the
         server's clock rather than on a browser one that may be minutes out. */
      clockOffset: Number(challenge.clock_offset_seconds || 0),
      nonce: envelope.payload.authorization.nonce,
      resent: false,
    };

    say("Submitting the signed authorization once.");
    const answer = await payment.hireWithPayment(
      state.record.service_id,
      inputs,
      header,
    );
    state.pending = null;
    say("The payment settled and the result arrived.");
    paintResult(answer, { free: false });

    await bindPayment(answer);
  } catch (err) {
    /* A replay refusal here means this authorization had already settled — the work is
       bought. The 409 carries no payment id, but the id is a hash of the envelope this
       page still holds, so the activation can be bound to a payment the reader has
       already made rather than left claiming a receipt nothing points at. */
    if (
      (err.code || err.error_code) === "authorization_replay" &&
      state.pending
    ) {
      await bindSettledReplay(state.pending);
    } else {
      paintFailure(err);
    }
  } finally {
    busy(false);
  }
}

/** Send the same signed authorization a second time, once, after a dropped response.

    Not a retry of the payment: it is a retry of the *delivery*. The bytes are identical, so
    Docket either recognises the nonce and refuses it as a replay — proving the first
    attempt landed — or has never seen it and settles it once. Either outcome is correct and
    neither can buy the work twice, which is the whole reason this is offered and signing
    again is not. */
/** Refuse to sign terms that are not the ones the page put in front of the reader.

    The price and asset were printed from `/services/{id}` before any of this began. If the
    challenge names a different amount or a different token, the reader would be authorising
    something other than what they read and agreed to — so the flow stops here, before the
    wallet opens, rather than after they have approved it. */
function assertTermsMatchTheQuote(terms) {
  /* Atomic prices arrive from `/services` as decimal strings, so comparison never passes
     through JavaScript's imprecise Number representation. */
  const quotedAmount = String(state.record.price_atomic);
  const quotedAsset = String(state.record.asset);
  if (terms.amountAtomic !== quotedAmount) {
    throw new api.ApiError(
      "quote_changed",
      `This page quoted ${state.record.price_display} (${quotedAmount} atomic units) and ` +
        `the payment challenge asks for ${terms.amountAtomic}. Nothing was signed.`,
    );
  }
  if (terms.token.toLowerCase() !== quotedAsset.toLowerCase()) {
    throw new api.ApiError(
      "quote_changed",
      `This page quoted a price in ${quotedAsset} and the payment challenge asks for ` +
        `${terms.token}. Nothing was signed.`,
    );
  }
  return terms;
}

async function resendPayment() {
  const pending = state.pending;
  if (!pending || pending.resent) return;
  /* Re-checked here, not only where the button was drawn. The panel may have been on
     screen for minutes, and sending a window the server has since closed turns a recovery
     into a 402 whose ordinary recovery is "sign a fresh payment" — the one thing that must
     not be offered when a settled first attempt is still possible. */
  if (!pendingIsLive(pending)) {
    paintFailure(
      new payment.PaymentError(
        "payment_outcome_unknown",
        "That authorization's window closed while this was on screen, so it cannot be " +
          "resent.",
      ),
    );
    return;
  }
  pending.resent = true;
  busy(true);
  say("Resending the same signed authorization.");
  try {
    const answer = await payment.hireWithPayment(
      state.record.service_id,
      pending.inputs,
      pending.header,
    );
    state.pending = null;
    say(
      "It had not arrived the first time. The payment settled and the result arrived.",
    );
    paintResult(answer, { free: false });
    await bindPayment(answer);
  } catch (err) {
    const code = err && (err.code || err.error_code);
    /* A replay refusal on a resend is the good outcome: it proves the first attempt
       landed. The payment id is derivable from the bytes that were sent, so the run can
       still be bound to this activation without the server having to hand one back. */
    if (code === "authorization_replay") {
      await bindSettledReplay(pending);
      return;
    }
    /* Anything the server could not read is still, from here, an unknown outcome — the
       first attempt may have settled. Reporting it as `payment_invalid` would surface the
       ordinary recovery for that code, which offers a fresh payment. */
    if (code === "payment_invalid" || code === "payment_not_verified") {
      paintFailure(
        new payment.PaymentError(
          "payment_outcome_unknown",
          `Docket refused the resent authorization (${code}). That does not say whether ` +
            "the first attempt settled, so no new payment is offered.",
        ),
      );
      return;
    }
    paintFailure(err);
  } finally {
    busy(false);
  }
}

/** A resend refused as a replay: the payment settled, so bind the activation to it.

    The 409 carries no payment id — it is a refusal, not a receipt — but the id is a hash
    of the envelope the browser still holds, computed by the same recipe the server uses.
    Deriving it is what turns "your money left and nothing here knows about it" into a
    bound activation. */
async function bindSettledReplay(pending) {
  say(
    "Docket had already settled that authorization. Binding it to your activation.",
  );
  let derived;
  try {
    derived = await payment.paymentId(pending.envelope);
  } catch (err) {
    paintFailure(
      new api.ApiError(
        "payment_id_underivable",
        "That payment settled, and this browser could not compute the id it was filed " +
          `under. Quote the authorization nonce to support: ${pending.nonce}.`,
      ),
    );
    return;
  }
  state.pending = null;
  try {
    await bindPayment({ payment_id: derived, receipt: null, result: null });
  } catch (err) {
    region("outcome").innerHTML = failurePanel(err, {
      heading: "The payment settled, and Docket could not bind it here",
      note:
        `The work is paid for. Its payment id is ${derived}. Binding it to this ` +
        "activation failed, so quote that id rather than signing anything else.",
      actions: [
        { label: "Bind it again", action: "bind-only" },
        { label: "Check My agents", href: "/my-agents" },
      ],
    });
  }
}

/** Bind again, and only bind. Reached from a settled payment whose activation is not
    recorded against it; nothing on this path can spend. */
async function retryBind() {
  if (!state.answer) return;
  busy(true);
  try {
    await bindPayment(state.answer);
  } catch (err) {
    paintFailure(err);
  } finally {
    busy(false);
  }
}

/** Bind a settled payment to the activation the reader opened for it.

    The payment id is signed into the message, not merely sent beside it: a signature over
    "approve this activation" with an unsigned id in the body would authorise binding
    whatever id happened to arrive with it. */
/** Approve a free-tier one-shot so the service runs. The same signed action as binding a
    payment, minus the payment: there is nothing to bind, and the server runs the service
    on approval and answers with the finished activation, result and receipt on it. */
async function approveFreeTier() {
  say("This service is not in paid stock, so it runs on the free tier. Nothing is charged.");
  const account = await signingAccount();
  const signature = await wallet.personalSign(
    api.authMessage(state.activation, "approve"),
    account,
  );
  state.activation = await api.approveActivation(state.activation.activation_id, {
    owner_signature: signature,
    nonce: state.activation.auth_nonce,
  });
  paintActivation();
  say("Approved. The service ran on the free tier under your activation.");
  if (state.activation.result) {
    paintResult(
      {
        result: state.activation.result,
        receipt: (state.activation.receipts || [])[0],
      },
      { free: false },
    );
  }
  startPolling();
}

async function bindPayment(answer) {
  if (!state.activation) return;
  /* Held so a bind that fails can be retried on its own. Everything before this point has
     already happened — the payment settled — so the recovery for a failed bind must never
     be the flow that would pay again. */
  state.answer = answer;
  say("Binding the payment to your activation.");
  const account = await signingAccount();
  const signature = await wallet.personalSign(
    api.authMessage(state.activation, "approve", answer.payment_id),
    account,
  );
  state.activation = await api.approveActivation(
    state.activation.activation_id,
    {
      owner_signature: signature,
      nonce: state.activation.auth_nonce,
      payment_id: answer.payment_id,
    },
  );
  state.answer = null;
  paintActivation();
  say("Bound. This activation is yours and is listed on My agents.");
  startPolling();
}

/* The account every signature on this page is taken from. Re-read from the wallet each
   time rather than carried in a variable: a reader who switched accounts mid-flow would
   otherwise sign as the address the page remembered, and the server would refuse it as
   `not_owner` after the wallet had already asked them to approve something. */
async function signingAccount() {
  const current = await wallet.currentAccount();
  if (!current) {
    throw new wallet.WalletError(
      "no_account",
      "The wallet has no account connected any more. Reconnect and start again.",
    );
  }
  if (state.account && current.toLowerCase() !== state.account.toLowerCase()) {
    throw new wallet.WalletError(
      "account_changed",
      `This activation belongs to ${state.account} and the wallet is now on ${current}. ` +
        "Switch back, or start again on the account you want to own it.",
    );
  }
  return current;
}

async function onFundSession(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const hash = form.elements.namedItem("tx_hash").value.trim();
  if (!/^0x[0-9a-fA-F]{64}$/.test(hash)) {
    paintFailure(
      new api.ApiError(
        "invalid_tx_hash",
        "A funding transaction hash is 32 bytes of hexadecimal, written 0x followed by 64 characters.",
      ),
    );
    return;
  }
  try {
    if (!state.account) state.account = await wallet.connect();
    const signature = await wallet.personalSign(
      api.authMessage(state.activation, "approve", hash),
      await signingAccount(),
    );
    state.activation = await api.approveActivation(
      state.activation.activation_id,
      {
        owner_signature: signature,
        nonce: state.activation.auth_nonce,
        tx_hash: hash,
      },
    );
    paintActivation();
    say(
      "Funding submitted. Docket confirms it by reading the balances at that block.",
    );
    startPolling();
  } catch (err) {
    paintFailure(err);
  }
}

async function onSignPrepared() {
  const target = region("prepared");
  try {
    const prepared = await api.preparedCalls(state.activation.activation_id);
    const calls = prepared.calls || [];
    if (!calls.length) {
      target.innerHTML =
        '<p class="dim">Docket has no call prepared for this activation right now.</p>';
      return;
    }
    target.innerHTML = calls
      .map(
        (call) => `<div class="panel">
          <dl class="deflist">
            ${definitionRows([
              ["Purpose", call.purpose],
              ["To", call.to],
              ["Value", call.value_atomic],
              ["Gas ceiling", call.gas_ceiling],
              ["Deadline", call.deadline],
              ["Simulated", (call.simulation || {}).ok ? "ok" : "reverted"],
              ["Gas estimate", (call.simulation || {}).gas_estimate],
              ["Revert reason", (call.simulation || {}).revert_reason],
              ["Observed at", (call.simulation || {}).observed_at],
              ["Block", (call.simulation || {}).block],
            ])}
          </dl>
          <pre class="wrap-anywhere">${escapeHTML(call.data)}</pre>
        </div>`,
      )
      .join("");
    for (const call of calls) {
      if (call.simulation && call.simulation.ok === false) {
        throw new api.ApiError(
          "simulation_failed",
          `Docket simulated that call and it reverted: ${call.simulation.revert_reason || "no reason given"}. It was not offered for signing.`,
        );
      }
    }
    if (!state.account) state.account = await wallet.connect();
    await wallet.ensureBsc();
    let lastHash = null;
    for (const call of calls) {
      lastHash = await wallet.sendTransaction({
        from: state.account,
        to: call.to,
        data: call.data,
        ...(call.value_atomic && call.value_atomic !== "0"
          ? { value: "0x" + BigInt(call.value_atomic).toString(16) }
          : {}),
      });
      await wallet.waitForReceipt(lastHash);
      say(`Sent ${call.purpose} in ${lastHash}.`);
    }
    const signature = await wallet.personalSign(
      api.authMessage(state.activation, "approve", lastHash),
      await signingAccount(),
    );
    state.activation = await api.approveActivation(
      state.activation.activation_id,
      {
        owner_signature: signature,
        nonce: state.activation.auth_nonce,
        tx_hash: lastHash,
      },
    );
    paintActivation();
    startPolling();
  } catch (err) {
    paintFailure(err);
  }
}

/* -------------------------------------------------------------------- wiring */

function wireKind() {
  const target = region("kind");
  target.innerHTML = `<fieldset class="kind-choice">
      <legend>How long should this run?</legend>
      <label><input type="radio" name="kind" value="one_shot" checked /> Once — one run, one payment, no standing permission</label>
      <label><input type="radio" name="kind" value="persistent" /> Continuously — a funded session inside limits you set</label>
    </fieldset>
    <div data-region="limits" hidden>
      <h3>The limits it runs inside</h3>
      <div data-region="limits-body">
        <span class="skeleton skeleton-row skeleton-wide"></span>
      </div>
    </div>`;
  const limits = region("limits");
  for (const radio of target.querySelectorAll('input[name="kind"]')) {
    radio.addEventListener("change", async () => {
      state.kind = radio.value;
      limits.hidden = state.kind !== "persistent";
      refreshPermissionCopy();
      paintActions();
      if (state.kind === "persistent") await paintLimits();
    });
  }
}

/* The allowlists are fetched, not assumed. The server owns them, a page that guessed would
   either forbid the work or permit more than the reader agreed to, and one that sent empty
   lists would be asking for a session allowed to call nothing. Fetched once and kept: the
   skeleton for a service does not change while the reader is reading it. */
async function paintLimits() {
  const target = region("limits-body");
  if (state.policyDefaults) return;
  try {
    /* The route answers an envelope — service, category, the skeleton, token hints, and
       what the owner still has to add — not a bare policy. */
    const envelope = await api.policyDefaults(state.record.service_id);
    state.policyDefaults = envelope.policy || null;
    if (!state.policyDefaults) {
      throw new api.ApiError(
        "policy_defaults_missing",
        "Docket answered with no session policy for this service.",
      );
    }
    target.innerHTML = limitsForm(state.record, state.policyDefaults);
  } catch (err) {
    state.policyDefaults = null;
    renderFailure(target, err, {
      heading: "The limits for this session could not be read",
      note:
        "Docket has not said what a session here would be allowed to touch, so there is " +
        "nothing to agree to. Nothing was created.",
      actions: [{ label: "Try again", action: "load-limits" }],
    });
  }
}

/** The one control that opens an activation, whatever the activation will cost.

    The catalogue card says whether a service is in paid stock; the server prices the
    activation itself. A one-shot on an admitted service is bought through x402. A one-shot
    on a service that is not admitted is quoted on the free tier and runs on the owner's
    approval — the API's contract for it is "create, then approve, and the service runs". A
    session is quoted free whatever the service's stock, because the x402 rail has no shape
    for a standing authorization; it is funded, not bought. Every one of those is an
    activation this page has to be able to start. Gating the button on paid stock, as this
    page once did, left the whole activation surface unreachable for as long as no service
    was admitted — which, on a deployment whose canary has not yet passed, is every service. */
function activationLabel(record, kind) {
  if (kind === "persistent") return `Activate ${record.name} as a session`;
  if (record.paid_stock) return `Activate and pay ${record.price_display}`;
  return "Activate on the free tier";
}

function paintActions() {
  const target = region("actions");
  const record = state.record;
  const label = escapeHTML(activationLabel(record, state.kind));
  const unavailable = record.paid_stock
    ? ""
    : `<p class="section-note">This service is <strong>not admitted to paid stock</strong>.
       Its status is <span class="mono">${escapeHTML(record.stock_status)}</span>, so a
       one-shot activation runs free and takes no payment authorization. Its price after
       admission would be <span class="num">${escapeHTML(record.price_display)}</span>.</p>`;
  /* "Try free sample" is the sample form's own submit button, so pressing Enter in a field
     runs the thing the field belongs to. Only the activation lives out here. */
  target.innerHTML = `<p class="btn-row"><button type="button" class="btn btn-primary" data-pay>${label}</button></p>${unavailable}`;
  target.querySelector("[data-pay]").addEventListener("click", activateAndPay);
}

function wireSampleForm() {
  const target = region("sample");
  target.innerHTML = sampleForm(state.record);
  const form = target.querySelector("[data-sample-form]");
  wireArrayControls(form);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    runSample(
      Boolean(event.submitter && event.submitter.matches("[data-example]")),
    );
  });
}

function wireRecovery() {
  /* The recovery panel is repainted on every failure, so its buttons are reached by
     delegation rather than rebound each time. */
  region("outcome").addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (action === "retry-payment") activateAndPay();
    if (action === "run-sample") runSample(false);
    if (action === "poll-once") pollOnce();
    if (action === "load-limits") paintLimits();
    if (action === "resend-payment") resendPayment();
    if (action === "bind-only") retryBind();
  });
}

async function resolveRecord(params) {
  const serviceId = params.get("service");
  if (serviceId) return await api.getService(serviceId);
  const category = params.get("category");
  if (category) {
    const listing = await api.listServices(category);
    const first = (listing.services || [])[0];
    if (!first) {
      throw new api.ApiError(
        "category_empty",
        `No Docket service stands in ${category} yet. A zero here is the honest answer, ` +
          "not a gap being papered over.",
      );
    }
    return await api.getService(first.service_id);
  }
  throw new api.ApiError(
    "no_service_requested",
    "This page activates one service, named by a service or category in the address. " +
      "Neither was given.",
  );
}

export async function init() {
  const params = new URLSearchParams(window.location.search);
  try {
    state.record = await resolveRecord(params);
  } catch (err) {
    region("controls").hidden = true;
    /* The failure is this page's whole content, so it carries the page's only `h1`. A
       document that reaches a reader with no top-level heading gives a screen reader
       nothing to announce it by. */
    renderFailure(region("listing"), err, {
      heading: "Nothing to activate",
      level: 1,
      actions: [{ label: "Pick a service", href: "/" }],
    });
    return;
  }
  paintListing();
  wireKind();
  wireSampleForm();
  paintActions();
  wireRecovery();
  paintActivation();
  /* A wallet that leaves BSC part-way through would sign an authorization no BSC
     facilitator can settle, so the page says so at the moment it happens rather than at
     the moment the payment is refused. `ensureBsc` still runs before every signature; this
     is the warning, not the guard. */
  if (wallet.hasProvider()) {
    wallet.onChainChanged((chain) => {
      const notice = region("chain");
      if (chain.toLowerCase() === wallet.BSC_CHAIN_ID) {
        notice.innerHTML = "";
        notice.hidden = true;
        return;
      }
      notice.hidden = false;
      notice.innerHTML = `<div class="notice notice-warn" role="status">
          <p class="notice-heading">Your wallet is no longer on BNB Smart Chain</p>
          <p>It is on <span class="mono">${escapeHTML(chain)}</span>. Docket settles on
            BNB Smart Chain only, and will ask you to switch back before it takes a
            signature. Nothing already signed is affected.</p>
        </div>`;
    });
    /* An activation belongs to the address that opened it. A reader who switches accounts
       mid-flow is told at that moment, rather than after the wallet has asked them to
       approve something the server will refuse as `not_owner`; `signingAccount` is the
       guard, and this is the warning. */
    wallet.onAccountsChanged((account) => {
      const notice = region("account");
      if (
        !state.account ||
        (account && account.toLowerCase() === state.account.toLowerCase())
      ) {
        notice.innerHTML = "";
        notice.hidden = true;
        return;
      }
      notice.hidden = false;
      notice.innerHTML = `<div class="notice notice-warn" role="status">
          <p class="notice-heading">Your wallet has switched accounts</p>
          <p>This activation belongs to <span class="mono">${escapeHTML(state.account)}</span>
            and the wallet is now on
            <span class="mono">${escapeHTML(account || "no account")}</span>. Docket will
            not sign for it from a different address; switch back, or start again on the
            account you want to own it.</p>
        </div>`;
    });
  }
  window.addEventListener("beforeunload", stopPolling);
  if (params.get("demo") === "1") await runSample(true);
}
