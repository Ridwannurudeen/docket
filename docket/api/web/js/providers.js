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
    state.claim = await api.providerClaim({ agent_id: agentId });
    state.claim.signature = await wallet.personalSign(
      state.claim.message,
      state.account,
    );
    paintOwnership();
    paintListingForm();
    paintSteps("listing");
  } catch (err) {
    paintSteps("identity");
    renderFailure(region("failure"), err, {
      heading: "That identity was not claimed",
      note:
        "Docket recovers the signer and holds it against ownerOf on chain 56; only the " +
        "address the registry names may claim. Nothing was published.",
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
        <p class="dim">Yours to declare. Docket records it as
          <span class="mono">provider_declared</span> and does not let its own rule table
          overwrite what an owner says about their own agent.</p>
      </div>
      <div class="field">
        <label for="listing-capabilities">Capabilities</label>
        <textarea id="listing-capabilities" name="capabilities" rows="4" required></textarea>
        <p class="dim">What the agent does, in the terms a buyer would search for. Stored
          verbatim as your own description.</p>
      </div>
      <div class="field">
        <label for="listing-price">Price (optional)</label>
        <input id="listing-price" name="price" type="text" />
        <p class="dim">Written as you state it, for example
          <span class="mono">0.50 USDT</span>. Left blank, the listing says no price was
          stated rather than showing a zero that reads as free.</p>
      </div>
      <div class="field">
        <label for="listing-payment-method">Payment method (optional)</label>
        <input id="listing-payment-method" name="payment_method" type="text" />
        <p class="dim">How a buyer would pay you, for example
          <span class="mono">x402</span>.</p>
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
  /* Docket stores the capability text a provider wrote, verbatim and as one string: it is
     the owner's own description of their agent, and chopping it into a list would be
     Docket restating somebody else's claim in a shape they did not choose. */
  const capabilities = form.elements.namedItem("capabilities").value.trim();
  const price = form.elements.namedItem("price").value.trim();
  const paymentMethod = form.elements.namedItem("payment_method").value.trim();
  if (!capabilities) {
    renderFailure(region("failure"), {
      code: "invalid_capabilities",
      message:
        "Say what the agent does. A listing that describes nothing is not a listing.",
    });
    return;
  }
  region("failure").innerHTML = "";
  const button = form.querySelector("[data-publish]");
  button.disabled = true;
  try {
    const answer = await api.createListing({
      agent_id: state.agentId,
      nonce: state.claim.nonce,
      signature: state.claim.signature,
      category: form.elements.namedItem("category").value,
      capabilities,
      price: price || null,
      payment_method: paymentMethod || null,
    });
    state.listing = answer.listing || answer;
    paintStatus();
    paintSteps("published");
  } catch (err) {
    /* The nonce is spent on the attempt whether or not the listing was written, so the
       claim above is no longer good and the reader is sent back to make a fresh one
       rather than left pressing a button that can only fail. */
    state.claim = null;
    paintSteps("identity");
    renderFailure(region("failure"), err, {
      heading: "The listing was not published",
      note:
        "Nothing was listed. A claim nonce is single use and this attempt spent it, so " +
        "claim the identity again before publishing.",
    });
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------- step 4 */

function paintStatus() {
  const listing = state.listing;
  const verification = listing.verification || {};
  const rows = verification.evidence || [];
  const failed = rows.filter((row) => row.ok === false);
  const checks = rows.length
    ? `<h3>Every level Docket attempted</h3>
       <ul class="facts">${rows
         .map(
           (row) =>
             `<li><strong>${escapeHTML(row.level || "level")}</strong> —
                ${row.ok ? "passed" : "did not pass"}
                ${row.at ? `<span class="dim">${escapeHTML(timeAgo(row.at))}</span>` : ""}</li>`,
         )
         .join("")}</ul>`
    : `<p class="section-note">Docket has not run a verification pass against this listing
       yet, so it stands at the level a fresh listing starts on and no more.</p>`;
  const note = failed.length
    ? `<div class="notice notice-warn">
        <p class="notice-heading">${failed.length} level${failed.length === 1 ? "" : "s"} did not pass</p>
        <p>The listing stands at the level its evidence supports. Fixing what failed and
          asking for another pass raises it; nothing here is a permanent verdict, and a
          level that was never attempted is recorded as never attempted rather than as a
          failure.</p>
      </div>`
    : "";
  region("status").innerHTML = `<h2 tabindex="-1">Listing status</h2>
    <div class="panel">
      <p>${verificationBadge(verification)}</p>
      <dl class="deflist">
        <dt>Agent</dt><dd class="mono">${escapeHTML(listing.agent_id || state.agentId)}</dd>
        <dt>Job</dt><dd>${escapeHTML(listing.category || "not filed under one of the four jobs")}
          <span class="dim">— ${escapeHTML(listing.capability_source || "source not recorded")}</span></dd>
        <dt>Price</dt><dd>${escapeHTML(listing.price || "none stated")}</dd>
        <dt>Payment method</dt><dd>${escapeHTML(listing.payment_method || "none stated")}</dd>
        <dt>Offered by Docket</dt><dd>${listing.hireable ? "yes" : "no"}</dd>
        <dt>Observed</dt><dd>${escapeHTML(timeAgo(verification.verified_at))}</dd>
      </dl>
      ${checks}
      ${note}
      <p class="dim">A listing is not offered by Docket for being published. It becomes
        hireable only once a verification pass has run it and recorded the result, and
        whether a payment challenge was ever exercised is carried as its own fact beside
        the level rather than implied by it.</p>
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
