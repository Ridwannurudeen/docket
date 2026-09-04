/* Every HTTP call the pivot pages make, in one place, so a route name appears exactly once.

   Two error shapes reach this module and both are normalised to one. The routes that
   predate the activation API answer `{"error": {"code", "message"}}`; the activation,
   marketplace and provider routes answer the flat `{"error_code", "message"}` the pivot
   plan specifies. A caller reads `err.code` either way, and `err.error_code` is kept
   alongside it so a page can render the server's own vocabulary verbatim. */

import { encodeJSON } from "../app.js?v=13";

export class ApiError extends Error {
  constructor(code, message, { status = null, body = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.error_code = code;
    this.status = status;
    this.body = body;
  }
}

function errorFrom(path, status, body) {
  if (body && typeof body.error_code === "string") {
    return new ApiError(body.error_code, body.message || `${path} failed.`, {
      status,
      body,
    });
  }
  if (body && body.error && typeof body.error === "object") {
    return new ApiError(
      body.error.code || `http_${status}`,
      body.error.message || `${path} failed.`,
      { status, body },
    );
  }
  return new ApiError(
    `http_${status}`,
    `${path} failed with status ${status}.`,
    {
      status,
      body,
    },
  );
}

async function readBody(response) {
  try {
    return await response.json();
  } catch (cause) {
    return null;
  }
}

async function send(path, { method = "GET", body = null, headers = {} } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: {
        accept: "application/json",
        ...(body === null ? {} : { "content-type": "application/json" }),
        ...headers,
      },
      ...(body === null ? {} : { body: encodeJSON(body) }),
    });
  } catch (cause) {
    throw new ApiError(
      "network_error",
      `Could not reach ${path}. Docket may not be running, or the connection dropped.`,
    );
  }
  const payload = await readBody(response);
  if (!response.ok) throw errorFrom(path, response.status, payload);
  /* A 200 that still carries an error object is the legacy hire contract's way of
     reporting a refused payment; it is an error here too. */
  if (payload && payload.error && typeof payload.error === "object") {
    throw errorFrom(path, response.status, payload);
  }
  return payload;
}

function query(params) {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(name, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

/* ------------------------------------------------------------------ catalogue */

/** Every service Docket runs, optionally narrowed to one of the four job categories. */
export function listServices(category = null) {
  return send(`/services${query({ category })}`);
}

/** One service in full, including the input schema the sample form is built from. */
export function getService(serviceId) {
  return send(`/services/${encodeURIComponent(serviceId)}`);
}

/** Run one service on the free tier: no payment header, no wallet, no charge. */
export function runFreeSample(serviceId, body) {
  return send(`/hire/${encodeURIComponent(serviceId)}`, {
    method: "POST",
    body,
  });
}

/* ---------------------------------------------------------------- activations */

/* The five actions the server will verify a signature for, and nothing else. */
const ACTIONS = ["create", "approve", "pause", "cancel", "revoke"];

/** The exact string a mutating call has to be signed over.

    `binds` is the evidence the call carries — a transaction hash, or a payment id — and it
    is part of the signed text rather than an unsigned field beside it. Without it a
    signature authorises "approve this activation" and not "approve this activation against
    THIS transaction", and anything else could be substituted into the body after the owner
    signed. This mirrors `docket/jobs/auth.py::action_message`, which is what verifies it;
    the two files have no shared source, so `tests/test_web_pages_pivot.py` compares them.

    There is no counterpart for a create: that message is issued by
    `/api/activations/nonce` and signed verbatim, which is stricter than rebuilding it. */
export function actionMessage(activationId, action, nonce, binds = "") {
  const message = `Docket activation ${activationId} ${action} ${nonce}`;
  return binds ? `${message} ${binds}` : message;
}

/** What to sign for one action on one activation, composed here from checked parts.

    Deliberately not read from a field on the response. A response is attacker-reachable
    the moment anything between the browser and Docket is: a server-supplied string handed
    straight to `personal_sign` is a signature over whatever that string turned out to say,
    and the reader would be approving text nobody in this codebase wrote.

    The parts are checked rather than the assembled sentence, because checking a string
    against a prefix built from the same values proves nothing. What can actually go wrong
    is a component carrying whitespace: the server splits nothing, but it composes the same
    way, and an id or a nonce with a space in it silently shifts which token the server
    reads as the bind — so a signature meant for one transaction hash would verify against
    a sentence about another. Anything with whitespace in it is refused here. */
export function authMessage(activation, action, binds = "") {
  const parts = {
    activation_id: activation.activation_id,
    action,
    nonce: activation.auth_nonce,
    binds,
  };
  if (!ACTIONS.includes(action)) {
    throw new ApiError(
      "unsafe_message",
      `${action} is not an activation action Docket signs for.`,
    );
  }
  for (const [name, value] of Object.entries(parts)) {
    if (name !== "binds" && !value) {
      throw new ApiError(
        "unsafe_message",
        `Docket will not sign an activation message with no ${name}.`,
      );
    }
    if (value && /\s/.test(String(value))) {
      throw new ApiError(
        "unsafe_message",
        `The ${name} carries whitespace, which would change which word the server reads ` +
          "as the evidence this signature binds. Nothing was signed.",
      );
    }
  }
  return actionMessage(
    activation.activation_id,
    action,
    activation.auth_nonce,
    binds,
  );
}

/** A single-use nonce and the exact message to sign for a create.

    `service_id` is not optional in practice: without it the server issues the nonce with a
    null message, and there is then nothing to sign. Asking for the message rather than
    assembling it is what keeps the browser and the server on one sentence. */
export function activationNonce(owner, serviceId) {
  return send(
    `/api/activations/nonce${query({ owner, service_id: serviceId })}`,
  );
}

/** Open one activation. The signature proves the owner asked for it. */
export function createActivation({
  service_id,
  kind,
  owner,
  owner_signature,
  nonce,
  inputs,
  policy = null,
}) {
  return send("/api/activations", {
    method: "POST",
    body: {
      service_id,
      kind,
      owner,
      owner_signature,
      nonce,
      inputs,
      ...(policy === null ? {} : { policy }),
    },
  });
}

export function getActivation(activationId) {
  return send(`/api/activations/${encodeURIComponent(activationId)}`);
}

export function listActivations(owner) {
  return send(`/api/activations${query({ owner })}`);
}

/** The SessionPolicy skeleton for one service: the contract, function and token
    allowlists its category declares, and the caps Docket defaults to.

    The browser cannot know a category's allowlists — they belong to the executor — and a
    page that sent an empty list would be asking for a session permitted to call nothing.
    So it asks, shows the reader what the session may touch, and sends the lists back
    unchanged with only the caps the reader actually chose. */
export function policyDefaults(serviceId) {
  return send(
    `/api/activations/policy-defaults${query({ service_id: serviceId })}`,
  );
}

/** What the browser has to sign or send next, already simulated by the server. */
export function preparedCalls(activationId) {
  return send(`/api/activations/${encodeURIComponent(activationId)}/prepared`);
}

function mutate(activationId, action, body) {
  return send(
    `/api/activations/${encodeURIComponent(activationId)}/${action}`,
    { method: "POST", body },
  );
}

/** Bind a settled payment, or a funding transaction, to an activation.

    A payment is named by its `payment_id` — the id `/hire/{service}` put in the receipt —
    and not by the header that bought it. The server binds against its own settled
    `hire_payments` row, so re-sending the authorization would prove nothing it has not
    already recorded and would put a spent authorization back on the wire. */
export function approveActivation(
  activationId,
  { owner_signature, nonce, tx_hash = null, payment_id = null },
) {
  return mutate(activationId, "approve", {
    owner_signature,
    nonce,
    ...(tx_hash === null ? {} : { tx_hash }),
    ...(payment_id === null ? {} : { payment_id }),
  });
}

export function pauseActivation(activationId, { owner_signature, nonce }) {
  return mutate(activationId, "pause", { owner_signature, nonce });
}

export function cancelActivation(activationId, { owner_signature, nonce }) {
  return mutate(activationId, "cancel", { owner_signature, nonce });
}

export function revokeActivation(activationId, { owner_signature, nonce }) {
  return mutate(activationId, "revoke", { owner_signature, nonce });
}

/* ---------------------------------------------------------------- marketplace */

/** The derived counters the home page and the status line are rendered from. */
export function marketplaceSummary() {
  return send("/api/marketplace/summary");
}

/** Registry and Docket supply in one search, filtered by text, category and level. */
export function searchAgents({ q = "", category = "", level = "" } = {}) {
  return send(`/api/agents${query({ q, category, level })}`);
}

/* ------------------------------------------------------------------ providers */

/** Start a provider claim. Docket mints a single-use nonce and prints the exact sentence
    to sign; it does not need to be told who the owner is, because it reads that from
    `ownerOf` on chain and compares it to whoever signed. */
export function providerClaim({ agent_id }) {
  return send("/api/providers/claim", { method: "POST", body: { agent_id } });
}

/** Publish one listing, spending the claim nonce in the same call.

    A nonce can be spent here or on `/api/providers/claim`, never on both, so the claim is
    proved by this request rather than in a step before it. */
export function createListing({
  agent_id,
  nonce,
  signature,
  category,
  capabilities,
  price = null,
  payment_method = null,
}) {
  return send("/api/providers/listings", {
    method: "POST",
    body: {
      agent_id,
      nonce,
      signature,
      category,
      capabilities,
      price,
      payment_method,
    },
  });
}
