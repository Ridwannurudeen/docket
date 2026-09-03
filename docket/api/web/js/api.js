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

/* The exact string the server signs a state change against, written here once so no call
   site hand-assembles one. There is no counterpart for a create: that message is issued by
   `/api/activations/nonce` and signed verbatim, which is stricter than rebuilding it. */
export function actionMessage(activationId, action, nonce) {
  return `Docket activation ${activationId} ${action} ${nonce}`;
}

/** A single-use nonce and the exact message to sign for a create. */
export function activationNonce(owner) {
  return send(`/api/activations/nonce${query({ owner })}`);
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

/** Bind a settled payment, a funding transaction, or an owner approval to an activation. */
export function approveActivation(
  activationId,
  { owner_signature, nonce, tx_hash = null, payment_header = null },
) {
  return mutate(activationId, "approve", {
    owner_signature,
    nonce,
    ...(tx_hash === null ? {} : { tx_hash }),
    ...(payment_header === null ? {} : { payment_header }),
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

/** Start a provider claim: the server issues the nonce and the message to sign. */
export function providerClaim({ agent_id, owner }) {
  return send("/api/providers/claim", {
    method: "POST",
    body: { agent_id, owner },
  });
}

/** Publish one listing against a claimed identity. */
export function createListing({
  agent_id,
  owner,
  owner_signature,
  nonce,
  category,
  capabilities,
  price_atomic,
}) {
  return send("/api/providers/listings", {
    method: "POST",
    body: {
      agent_id,
      owner,
      owner_signature,
      nonce,
      category,
      capabilities,
      price_atomic,
    },
  });
}
