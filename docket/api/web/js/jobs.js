/* My agents: everything one wallet has activated, what each is allowed to spend, and the
   three controls that stop it.

   Ownership here is proved, not asserted. The listing is read by address, but pausing,
   cancelling and revoking each carry a fresh EIP-191 signature over the exact message the
   activation's current nonce belongs to — so reading this page needs no signature and
   changing anything on it cannot be done by anyone but the owner. */

import * as api from "./api.js?v=13";
import * as wallet from "./wallet.js?v=13";
import {
  DASH,
  IN_FLIGHT_STATES,
  TERMINAL_STATES,
  escapeHTML,
  receiptBlock,
  region,
  renderFailure,
  shortAddress,
  stateMeans,
  timeAgo,
  wireReceiptBlocks,
} from "./ui.js?v=13";

const state = { account: null, activations: [], expanded: new Set() };

/* An activation id reaches this page from the server, so it is not this module's to assume
   well-formed. `CSS.escape` makes it safe inside an attribute selector: an id carrying a
   quote or a bracket would otherwise break the selector out of its attribute and match
   rows it was never about. */
function byAttribute(name, value) {
  return `[${name}="${CSS.escape(String(value))}"]`;
}

/* ------------------------------------------------------------------ derived */

/** What one activation has spent, per token, from the session ledger the server keeps. */
function spentSummary(activation) {
  const spent = (activation.session || {}).spent_atomic || {};
  const rows = Object.entries(spent);
  if (!rows.length)
    return activation.kind === "persistent" ? "nothing yet" : DASH;
  return rows
    .map(([token, amount]) => `${amount} of ${shortAddress(token)}`)
    .join("; ");
}

/** The permission scope in one line: what the session may touch and what it may spend.

    A one-shot activation has no session and therefore no standing permission, and that is
    said rather than left blank — an empty cell reads as missing data, not as "none". */
function policySummary(activation) {
  const policy = activation.policy;
  if (!policy) {
    return activation.kind === "persistent"
      ? "no policy recorded"
      : "no standing permission";
  }
  const caps = Object.entries(policy.total_cap_atomic || {})
    .map(([token, amount]) => `${amount} of ${shortAddress(token)}`)
    .join("; ");
  const parts = [];
  if (caps) parts.push(`cap ${caps}`);
  if (
    policy.max_slippage_bps !== undefined &&
    policy.max_slippage_bps !== null
  ) {
    parts.push(`slippage ${policy.max_slippage_bps} bps`);
  }
  if (policy.max_gas_price_wei)
    parts.push(`gas ${policy.max_gas_price_wei} wei`);
  const contracts = (policy.contract_allowlist || []).length;
  if (contracts)
    parts.push(`${contracts} contract${contracts === 1 ? "" : "s"}`);
  if (policy.expires_at) parts.push(`expires ${policy.expires_at}`);
  if (policy.emergency_pause) parts.push("emergency pause set");
  return parts.length ? parts.join(", ") : "no limits recorded";
}

/** The most recent recorded delivery, which is the only "last run" Docket can evidence. */
function lastRun(activation) {
  const receipts = activation.receipts || [];
  const last = receipts[receipts.length - 1];
  if (last && last.delivered_at) return timeAgo(last.delivered_at);
  return activation.state === "quoted"
    ? "never"
    : timeAgo(activation.updated_at);
}

/* A schedule only exists for a session that is actually running one. Docket shows the
   server's own field and nothing else: a "next run" computed in the browser from an
   interval would be a promise this page has no standing to make. */
function nextRun(activation) {
  const declared =
    activation.next_run_at ||
    ((activation.next_action || {}).detail || {}).next_run_at;
  if (declared) return timeAgo(declared);
  if (TERMINAL_STATES.has(activation.state)) return "not scheduled";
  return activation.kind === "persistent" ? "unscheduled" : DASH;
}

/* --------------------------------------------------------------- the listing */

/* Which controls a state actually permits. Offering "pause" on a revoked session would ask
   for a signature the server is bound to refuse, and a refusal the page could have
   predicted is a defect in the page. */
function controlsFor(activation) {
  const controls = [];
  /* A sweep already in flight takes no further instruction: revoking again would ask for
     a signature over a transition the server is bound to refuse, and a refusal the page
     could have predicted is a defect in the page. The row still says what is happening. */
  if (IN_FLIGHT_STATES.has(activation.state)) return controls;
  if (activation.kind === "persistent") {
    if (activation.state === "active") controls.push(["pause", "Pause"]);
    if (!TERMINAL_STATES.has(activation.state))
      controls.push(["revoke", "Revoke"]);
  } else if (!TERMINAL_STATES.has(activation.state)) {
    controls.push(["cancel", "Cancel"]);
  }
  return controls;
}

function row(activation) {
  const id = activation.activation_id;
  const controls = controlsFor(activation)
    .map(
      ([action, label]) =>
        `<button type="button" class="btn" data-control="${escapeHTML(action)}" data-activation="${escapeHTML(id)}">${escapeHTML(label)}</button>`,
    )
    .join("");
  const receipts = activation.receipts || [];
  const exportButton = receipts.length
    ? `<button type="button" class="btn" data-export="${escapeHTML(id)}">Export receipt</button>`
    : "";
  return `<tr data-row="${escapeHTML(id)}">
      <td><span class="state-pill" data-state="${escapeHTML(activation.state)}">${escapeHTML(
        String(activation.state).replaceAll("_", " "),
      )}</span>
        <span class="dim">${escapeHTML(stateMeans(activation.state))}</span></td>
      <td><a href="/activate?service=${encodeURIComponent(activation.service_id)}">${escapeHTML(activation.service_id)}</a>
        <span class="dim">${escapeHTML(activation.kind)}</span></td>
      <td>${escapeHTML(lastRun(activation))}</td>
      <td>${escapeHTML(nextRun(activation))}</td>
      <td class="mono">${escapeHTML(spentSummary(activation))}</td>
      <td>${escapeHTML(policySummary(activation))}</td>
      <td class="btn-row">${controls}${exportButton}</td>
    </tr>
    <tr class="detail-row" data-detail="${escapeHTML(id)}" hidden>
      <td colspan="7"><div data-region="detail-${escapeHTML(id)}"></div></td>
    </tr>`;
}

function emptyState(reason) {
  if (reason === "no_wallet") {
    return `<div class="panel">
        <h2>No wallet in this browser</h2>
        <p>This page lists what one address has activated, so it needs to know which address.
          Docket holds no key of yours and no account: without a wallet there is nothing for
          it to look up.</p>
        <p class="btn-row"><a class="btn" href="/">Browse what Docket runs</a></p>
      </div>`;
  }
  if (reason === "not_connected") {
    return `<div class="panel">
        <h2>Connect the wallet that owns your activations</h2>
        <p>Reading this list takes no signature. Pausing, cancelling or revoking anything on
          it takes one, every time.</p>
        <p class="btn-row"><button type="button" class="btn btn-primary" data-connect>Connect wallet</button></p>
      </div>`;
  }
  return `<div class="panel">
      <h2>Nothing activated from this address yet</h2>
      <p><span class="mono">${escapeHTML(state.account || DASH)}</span> owns no activation.
        Activating a service from its page puts it here, with its state, its limits and the
        controls that stop it.</p>
      <p class="btn-row"><a class="btn" href="/search">Find an agent</a></p>
    </div>`;
}

function paintListing() {
  const target = region("jobs");
  if (!state.activations.length) {
    target.innerHTML = emptyState("empty");
    return;
  }
  target.innerHTML = `<p class="section-note">
      ${state.activations.length} activation${state.activations.length === 1 ? "" : "s"}
      owned by <span class="mono">${escapeHTML(state.account)}</span>. Spend figures are the
      session ledger's own totals, in atomic units of each token.
    </p>
    <div class="table-wrap">
      <table class="jobs-table">
        <caption>Every activation this address owns, newest first.</caption>
        <thead>
          <tr>
            <th scope="col">State</th>
            <th scope="col">Service</th>
            <th scope="col">Last run</th>
            <th scope="col">Next scheduled run</th>
            <th scope="col">Spent</th>
            <th scope="col">Permission scope</th>
            <th scope="col">Controls</th>
          </tr>
        </thead>
        <tbody>${state.activations.map(row).join("")}</tbody>
      </table>
    </div>`;
  for (const id of state.expanded) paintReceipts(id);
}

function paintReceipts(activationId) {
  const detailRow = document.querySelector(byAttribute("data-detail", activationId));
  if (!detailRow) return;
  const activation = state.activations.find(
    (item) => item.activation_id === activationId,
  );
  const target = document.querySelector(
    byAttribute("data-region", `detail-${activationId}`),
  );
  const receipts = activation ? activation.receipts || [] : [];
  detailRow.hidden = false;
  target.innerHTML = receipts.length
    ? receipts
        .map(
          (
            receipt,
            index,
          ) => `<h3>Receipt ${index + 1} of ${receipts.length}</h3>
            ${receiptBlock(receipt, {
              filename: `docket-receipt-${activationId}-${index + 1}.json`,
            })}`,
        )
        .join("")
    : '<p class="dim">This activation has produced no receipt yet.</p>';
  wireReceiptBlocks(target);
}

/* ------------------------------------------------------------------ controls */

const CONTROL_CALLS = {
  pause: api.pauseActivation,
  cancel: api.cancelActivation,
  revoke: api.revokeActivation,
};

/* Sign the exact message the activation's current nonce belongs to, then send it. The nonce
   rotates on every accepted mutation, so a page holding a stale copy refetches once and
   signs again rather than reporting a failure the reader did not cause. */
async function runControl(activationId, action) {
  const call = CONTROL_CALLS[action];
  const status = region("control-status");
  let activation = state.activations.find(
    (item) => item.activation_id === activationId,
  );
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const nonce = activation.auth_nonce;
    const signature = await wallet.personalSign(
      api.authMessage(activation, action),
      state.account,
    );
    try {
      const updated = await call(activationId, {
        owner_signature: signature,
        nonce,
      });
      state.activations = state.activations.map((item) =>
        item.activation_id === activationId ? updated : item,
      );
      paintListing();
      status.textContent = `${activationId} is now ${updated.state}.`;
      return;
    } catch (err) {
      if (err.code !== "stale_nonce" || attempt === 1) throw err;
      activation = await api.getActivation(activationId);
      state.activations = state.activations.map((item) =>
        item.activation_id === activationId ? activation : item,
      );
    }
  }
}

function wireDelegation() {
  region("jobs").addEventListener("click", async (event) => {
    const exporter = event.target.closest("[data-export]");
    if (exporter) {
      const id = exporter.dataset.export;
      if (state.expanded.has(id)) {
        state.expanded.delete(id);
        const detailRow = document.querySelector(byAttribute("data-detail", id));
        if (detailRow) detailRow.hidden = true;
      } else {
        state.expanded.add(id);
        paintReceipts(id);
      }
      return;
    }
    const control = event.target.closest("[data-control]");
    if (control) {
      const id = control.dataset.activation;
      const action = control.dataset.control;
      control.disabled = true;
      try {
        await runControl(id, action);
      } catch (err) {
        renderFailure(region("control-failure"), err, {
          heading: `${action} did not go through`,
          note:
            "Nothing changed. Every control here needs a signature over the activation's " +
            "current nonce, and the server refuses anything else.",
        });
      } finally {
        control.disabled = false;
      }
      return;
    }
    const connect = event.target.closest("[data-connect]");
    if (connect) {
      await connectAndLoad();
      return;
    }
    const retry = event.target.closest('[data-action="reload"]');
    if (retry) await load();
  });
}

/* --------------------------------------------------------------------- load */

async function load() {
  const target = region("jobs");
  target.setAttribute("aria-busy", "true");
  try {
    const listing = await api.listActivations(state.account);
    state.activations = listing.activations || [];
    paintListing();
  } catch (err) {
    renderFailure(target, err, {
      heading: "Your activations could not be read",
      actions: [{ label: "Try again", action: "reload" }],
    });
  } finally {
    target.setAttribute("aria-busy", "false");
  }
}

async function connectAndLoad() {
  try {
    state.account = await wallet.connect();
    await paintAccount();
    await load();
  } catch (err) {
    renderFailure(region("jobs"), err, {
      heading: "The wallet did not connect",
    });
  }
}

async function paintAccount() {
  const target = region("account");
  target.innerHTML = state.account
    ? `<span class="status-key">owner</span>
       <strong class="mono">${escapeHTML(state.account)}</strong>`
    : '<span class="dim">No wallet connected.</span>';
}

export async function init() {
  wireDelegation();
  if (!wallet.hasProvider()) {
    region("jobs").innerHTML = emptyState("no_wallet");
    await paintAccount();
    return;
  }
  /* A page load never opens a wallet prompt. An address the wallet has already authorised
     for this site is read silently; anything else waits for the reader to ask. */
  state.account = await wallet.currentAccount();
  await paintAccount();
  if (!state.account) {
    region("jobs").innerHTML = emptyState("not_connected");
    return;
  }
  await load();
  wallet.onAccountsChanged(async (account) => {
    state.account = account;
    state.activations = [];
    state.expanded.clear();
    await paintAccount();
    if (account) await load();
    else region("jobs").innerHTML = emptyState("not_connected");
  });
}
