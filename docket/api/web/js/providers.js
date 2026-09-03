/* Providers: list an ERC-8004 agent you already control on Docket.

   Four steps, in this order, because each one depends on the last. Name the identity, prove
   you own it by signing the message the server issues for that identity, describe what it
   does and what it costs, then publish. Docket verifies the listing itself afterwards and
   publishes what failed as plainly as what passed: a listing that fails its checks stays
   visible with its failures attached, because a provider who cannot see why is a provider
   who cannot fix it. */

import * as api from "./api.js?v=13";
import * as wallet from "./wallet.js?v=13";
import {
  escapeHTML,
  region,
  renderFailure,
  timeAgo,
  verificationBadge,
} from "./ui.js?v=13";

const CATEGORIES = [
  ["rebalancing", "Manages LP ranges, resets positions automatically"],
  ["grid_trading", "Places and manages automated grid orders"],
  ["yield_optimisation", "Routes liquidity to the highest available APR"],
  ["health_factor", "Protects lending positions from liquidation"],
];

const state = { agentId: "", account: null, claim: null, listing: null };

function step(number, name, status) {
  return `<li class="step" data-step="${escapeHTML(name)}" data-status="${status}"${
    status === "current" ? ' aria-current="step"' : ""
  }>
      <span class="step-name">${number}. ${escapeHTML(name)}</span>
    </li>`;
}

function paintSteps(current) {
  const names = ["identity", "ownership", "listing", "published"];
  const index = names.indexOf(current);
  region("steps").innerHTML =
    `<ol class="stepper" aria-label="Listing progress">
      ${names
        .map((name, position) =>
          step(
            position + 1,
            name,
            position < index
              ? "done"
              : position === index
                ? "current"
                : "ahead",
          ),
        )
        .join("")}
    </ol>`;
}

/* ------------------------------------------------------------------- step 1 */

function paintIdentityForm() {
  region("identity").innerHTML =
    `<form class="activate" data-identity-form novalidate>
      <div class="field">
        <label for="provider-agent">ERC-8004 agent id</label>
        <input id="provider-agent" name="agent_id" type="text" inputmode="numeric"
          value="${escapeHTML(state.agentId)}" required />
        <p class="dim">The token id of the identity you registered on BSC. Docket reads its
          owner from the IdentityRegistry and will only accept a signature from that address.</p>
      </div>
      <p class="btn-row">
        <button type="submit" class="btn btn-primary" data-claim>Connect wallet and claim</button>
      </p>
    </form>`;
  region("identity")
    .querySelector("[data-identity-form]")
    .addEventListener("submit", onClaim);
}

async function onClaim(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const agentId = form.elements.namedItem("agent_id").value.trim();
  if (!agentId) {
    renderFailure(region("failure"), {
      code: "missing_agent_id",
      message: "Name the agent id you are claiming.",
    });
    return;
  }
  state.agentId = agentId;
  region("failure").innerHTML = "";
  paintSteps("ownership");
  try {
    state.account = await wallet.connect();
    await wallet.ensureBsc();
    /* The server issues the nonce and the exact message; the browser signs what it was
       given rather than a string it assembled, so a message the server does not recognise
       can never be signed by accident. */
    state.claim = await api.providerClaim({
      agent_id: agentId,
      owner: state.account,
    });
    const signature = await wallet.personalSign(
      state.claim.message,
      state.account,
    );
    state.claim.owner_signature = signature;
    paintOwnership();
    paintListingForm();
    paintSteps("listing");
  } catch (err) {
    paintSteps("identity");
    renderFailure(region("failure"), err, {
      heading: "That identity was not claimed",
      note:
        "Docket accepts a claim only from the address the IdentityRegistry names as the " +
        "owner. Nothing was published.",
    });
  }
}

function paintOwnership() {
  region("ownership").innerHTML = `<div class="panel">
      <h2>Ownership proved</h2>
      <dl class="deflist">
        <dt>Agent</dt><dd class="mono">${escapeHTML(state.agentId)}</dd>
        <dt>Owner</dt><dd class="mono">${escapeHTML(state.account)}</dd>
        <dt>Signed message</dt><dd class="mono wrap-anywhere">${escapeHTML(state.claim.message)}</dd>
      </dl>
      <p class="dim">The signature stays with this request. Docket recovers the address from
        it and compares that to the registry owner; it never holds a key of yours.</p>
    </div>`;
}

/* ------------------------------------------------------------------- step 3 */

function paintListingForm() {
  const categories = CATEGORIES.map(
    ([value, label]) =>
      `<option value="${escapeHTML(value)}">${escapeHTML(label)}</option>`,
  ).join("");
  region("listing-form").innerHTML =
    `<form class="activate" data-listing-form novalidate>
      <div class="field">
        <label for="listing-category">Job category</label>
        <select id="listing-category" name="category" required>${categories}</select>
        <p class="dim">One of the four jobs BNB names. A listing outside them is not filed
          under a job it does not do.</p>
      </div>
      <div class="field">
        <label for="listing-capabilities">Capabilities</label>
        <textarea id="listing-capabilities" name="capabilities" rows="4" required></textarea>
        <p class="dim">One capability per line, in the terms a buyer would search for.</p>
      </div>
      <div class="field">
        <label for="listing-price">Price per call, in atomic units</label>
        <input id="listing-price" name="price_atomic" type="text" inputmode="numeric"
          pattern="[0-9]+" required />
        <p class="dim">Atomic units of USDT, so 0.50 USDT is
          <span class="mono">500000000000000000</span>. Written exactly, never rounded.</p>
      </div>
      <p class="btn-row">
        <button type="submit" class="btn btn-primary" data-publish>Publish listing</button>
      </p>
    </form>`;
  region("listing-form")
    .querySelector("[data-listing-form]")
    .addEventListener("submit", onPublish);
}

async function onPublish(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const capabilities = form.elements
    .namedItem("capabilities")
    .value.split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const price = form.elements.namedItem("price_atomic").value.trim();
  if (!capabilities.length) {
    renderFailure(region("failure"), {
      code: "missing_capabilities",
      message:
        "Name at least one capability. A listing with none says nothing.",
    });
    return;
  }
  if (!/^[0-9]+$/.test(price)) {
    renderFailure(region("failure"), {
      code: "invalid_price",
      message:
        "The price is a whole number of atomic units, written in base 10 with no decimal point.",
    });
    return;
  }
  region("failure").innerHTML = "";
  const button = form.querySelector("[data-publish]");
  button.disabled = true;
  try {
    state.listing = await api.createListing({
      agent_id: state.agentId,
      owner: state.account,
      owner_signature: state.claim.owner_signature,
      nonce: state.claim.nonce,
      category: form.elements.namedItem("category").value,
      capabilities,
      price_atomic: price,
    });
    paintStatus();
    paintSteps("published");
  } catch (err) {
    renderFailure(region("failure"), err, {
      heading: "The listing was not published",
      note: "Nothing was listed. The claim above is still good; correct the listing and publish again.",
    });
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------- step 4 */

function paintStatus() {
  const listing = state.listing;
  const verification = listing.verification || {};
  const failed = listing.failed_checks || [];
  const checks = failed.length
    ? `<div class="notice notice-warn">
        <p class="notice-heading">${failed.length} check${failed.length === 1 ? "" : "s"} did not pass</p>
        <ul class="facts">${failed
          .map(
            (check) =>
              `<li><strong>${escapeHTML(check.name || check.check || "check")}</strong>
                 — ${escapeHTML(check.detail || check.reason || "no detail was recorded")}</li>`,
          )
          .join("")}</ul>
        <p>The listing stands at the level its evidence supports. Fixing a failed check and
          publishing again raises it; nothing here is a permanent verdict.</p>
      </div>`
    : `<p class="section-note">Every check Docket ran against this listing passed.</p>`;
  region("status").innerHTML = `<h2 tabindex="-1">Listing status</h2>
    <div class="panel">
      <p>${verificationBadge(verification.level)}</p>
      <dl class="deflist">
        <dt>Listing</dt><dd class="mono">${escapeHTML(listing.listing_id || state.agentId)}</dd>
        <dt>Agent</dt><dd class="mono">${escapeHTML(listing.agent_id || state.agentId)}</dd>
        <dt>Job</dt><dd>${escapeHTML(listing.category || "")}</dd>
        <dt>Price</dt><dd class="mono">${escapeHTML(String(listing.price_atomic || ""))}</dd>
        <dt>Verified</dt><dd>${escapeHTML(timeAgo(verification.verified_at))}</dd>
      </dl>
      ${checks}
      <p class="btn-row">
        <a class="btn" href="/search?q=${encodeURIComponent(state.agentId)}">See it in search</a>
      </p>
    </div>`;
  region("status").querySelector("h2").focus();
}

export function init() {
  const params = new URLSearchParams(window.location.search);
  state.agentId = params.get("agent") || "";
  paintSteps("identity");
  paintIdentityForm();
}
