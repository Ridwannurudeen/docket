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

const POLL_INTERVAL_MS = 3000;
/* Long enough for a queued run to reach a runner and finish, short enough that the page
   stops claiming to be watching something it has given up on. */
const POLL_ATTEMPTS = 200;

const state = {
  record: null,
  kind: "one_shot",
  account: null,
  activation: null,
  poller: null,
  polls: 0,
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
    `Two wallet actions and no standing permission: one ERC-20 approval for exactly ` +
    `${escapeHTML(record.price_display)}, so the B402 relayer can pull that amount, and one ` +
    "signed authorization for the same amount. Nothing is approved beyond the price, and " +
    "nothing remains approved afterwards."
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
function limitsForm(record) {
  const symbol = assetSymbol(record);
  return `<form class="activate limits-form" data-limits-form novalidate>
      <div class="field">
        <label for="limit-total">Total cap (${escapeHTML(symbol)})</label>
        <input id="limit-total" name="total_cap" type="number" step="any" min="0" value="10" required />
        <p class="dim">The most this session may spend in total before it stops.</p>
      </div>
      <div class="field">
        <label for="limit-action">Per-action limit (${escapeHTML(symbol)})</label>
        <input id="limit-action" name="per_action_limit" type="number" step="any" min="0" value="1" required />
        <p class="dim">The most any single transaction it sends may move.</p>
      </div>
      <div class="field">
        <label for="limit-slippage">Maximum slippage (basis points)</label>
        <input id="limit-slippage" name="max_slippage_bps" type="number" step="1" min="0" max="10000" value="50" required />
        <p class="dim">50 is 0.50%. A swap that would cost more than this is not sent.</p>
      </div>
      <div class="field">
        <label for="limit-gas">Maximum gas price (gwei)</label>
        <input id="limit-gas" name="max_gas_price_gwei" type="number" step="any" min="0" value="5" required />
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
  const record = state.record;
  const number = (name) => Number(form.elements.namedItem(name).value);
  const total = toAtomic(record, number("total_cap"));
  const perAction = toAtomic(record, number("per_action_limit"));
  if (total === null || perAction === null) {
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
  return {
    token_allowlist: [record.asset],
    per_action_limit_atomic: { [record.asset]: perAction.toString() },
    total_cap_atomic: { [record.asset]: total.toString() },
    max_slippage_bps: Math.trunc(number("max_slippage_bps")),
    max_gas_price_wei: (
      BigInt(Math.round(number("max_gas_price_gwei") * 1e6)) * 1000n
    ).toString(),
    expires_at: expiresAt,
    emergency_pause: false,
  };
}

function readInputs() {
  const form = document.querySelector("[data-sample-form]");
  const body = readForm(state.record, form);
  const missing = Object.entries(state.record.input_schema)
    .filter(([name, field]) => {
      if (!field.required) return false;
      if (field.type === "array") {
        const container = form.querySelector(`[data-array-control="${name}"]`);
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
  authorization_replay: {
    heading: "That authorization was already used",
    note:
      "An authorization is spendable once. If the earlier attempt settled, the run it " +
      "paid for is on My agents; do not sign a second payment for the same work until " +
      "you have looked.",
    actions: [
      { label: "Check My agents", href: "/my-agents" },
      { label: "Sign a fresh payment", action: "retry-payment" },
    ],
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
  payment_outcome_unknown: {
    heading: "The connection dropped mid-payment",
    note:
      "Docket cannot tell from here whether that authorization settled. Look before you " +
      "sign another: a second payment would buy the same work twice.",
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

function paintFailure(err) {
  const code = err && (err.code || err.error_code);
  const recovery = RECOVERY[code] || {
    heading: "That step did not complete",
    note: "Nothing beyond what is listed above was done.",
    actions: [{ label: "Start again", action: "retry-payment" }],
  };
  const outcome = region("outcome");
  outcome.innerHTML = failurePanel(err, recovery);
  const heading = outcome.querySelector("h3");
  if (heading) heading.focus();
  region("live-status").textContent = `${recovery.heading}.`;
}

/* --------------------------------------------------------------- activations */

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
  if (next.kind === "fund_session") {
    const amounts = Object.entries(detail.required_atomic || {})
      .map(
        ([token, amount]) =>
          `<li><span class="mono">${escapeHTML(amount)}</span> atomic units of
             <span class="mono">${escapeHTML(token)}</span></li>`,
      )
      .join("");
    target.innerHTML = `<div class="panel">
        <h3>Fund the session</h3>
        <p>Send the amounts below to the session address from your own wallet, then paste
          the transaction hash so Docket can confirm the funding at a block.</p>
        <p class="mono wrap-anywhere">${escapeHTML(detail.address || (activation.session || {}).address || DASH)}</p>
        <ul class="facts">${amounts || "<li>No amount was named.</li>"}</ul>
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
    window.clearInterval(state.poller);
    state.poller = null;
  }
}

function startPolling() {
  stopPolling();
  state.polls = 0;
  if (!state.activation || TERMINAL_STATES.has(state.activation.state)) return;
  state.poller = window.setInterval(pollOnce, POLL_INTERVAL_MS);
}

async function pollOnce() {
  if (!state.activation) return;
  state.polls += 1;
  if (state.polls > POLL_ATTEMPTS) {
    stopPolling();
    paintFailure(
      new api.ApiError(
        "poll_timeout",
        `This page watched activation ${state.activation.activation_id} for ` +
          `${Math.round((POLL_ATTEMPTS * POLL_INTERVAL_MS) / 1000)} seconds and it has not ` +
          "reached a final state.",
      ),
    );
    return;
  }
  try {
    state.activation = await api.getActivation(state.activation.activation_id);
  } catch (err) {
    stopPolling();
    paintFailure(err);
    return;
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

    say("Asking for the exact payment terms.");
    const challenge = await payment.fetchChallenge(
      state.record.service_id,
      inputs,
    );
    const terms = payment.paymentTerms(challenge);
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

    say("Signing the payment authorization.");
    const envelope = await payment.signPayment(state.account, challenge);
    const header = payment.encodePaymentHeader(envelope);

    say("Submitting the signed authorization once.");
    const answer = await payment.hireWithPayment(
      state.record.service_id,
      inputs,
      header,
    );
    say("The payment settled and the result arrived.");
    paintResult(answer, { free: false });

    say("Binding the payment to your activation.");
    const bindSignature = await wallet.personalSign(
      api.authMessage(state.activation, "approve"),
      state.account,
    );
    state.activation = await api.approveActivation(
      state.activation.activation_id,
      {
        owner_signature: bindSignature,
        nonce: state.activation.auth_nonce,
        payment_id: answer.payment_id,
      },
    );
    paintActivation();
    say("Bound. This activation is yours and is listed on My agents.");
    startPolling();
  } catch (err) {
    paintFailure(err);
  } finally {
    busy(false);
  }
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
      api.authMessage(state.activation, "approve"),
      state.account,
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
      api.authMessage(state.activation, "approve"),
      state.account,
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
      ${limitsForm(state.record)}
    </div>`;
  const limits = region("limits");
  for (const radio of target.querySelectorAll('input[name="kind"]')) {
    radio.addEventListener("change", () => {
      state.kind = radio.value;
      limits.hidden = state.kind !== "persistent";
      refreshPermissionCopy();
      paintActions();
    });
  }
}

function paintActions() {
  const target = region("actions");
  const record = state.record;
  const paid = record.paid_stock
    ? `<button type="button" class="btn btn-primary" data-pay>Activate and pay ${escapeHTML(record.price_display)}</button>`
    : "";
  const unavailable = record.paid_stock
    ? ""
    : `<p class="section-note">This service is <strong>not admitted to paid stock</strong>.
       Its status is <span class="mono">${escapeHTML(record.stock_status)}</span>, so it runs
       free and takes no payment authorization. Its price after admission would be
       <span class="num">${escapeHTML(record.price_display)}</span>.</p>`;
  /* "Try free sample" is the sample form's own submit button, so pressing Enter in a field
     runs the thing the field belongs to. Only the paid action lives out here. */
  target.innerHTML = `${paid ? `<p class="btn-row">${paid}</p>` : ""}${unavailable}`;
  const pay = target.querySelector("[data-pay]");
  if (pay) pay.addEventListener("click", activateAndPay);
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
    renderFailure(region("listing"), err, {
      heading: "Nothing to activate",
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
  }
  window.addEventListener("beforeunload", stopPolling);
  if (params.get("demo") === "1") await runSample(true);
}
