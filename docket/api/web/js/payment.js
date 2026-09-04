/* The x402 payment leg, driven from the browser with the reader's own wallet.

   This is the same exchange `docket/canary.py` performs from a terminal, with one
   difference: the key belongs to the reader and never reaches Docket. The steps are

     1. ask `/hire/{id}` for the challenge with a deliberately unreadable payment header,
     2. make sure the B402 relayer may pull exactly the price and not a unit more,
     3. sign the EIP-712 TransferWithAuthorization the challenge describes,
     4. submit it once.

   Every field below is mirrored from `docket/hire/x402.py`; tests/test_web_pages_pivot.py
   compares the two files and fails if either side drifts. */

import { encodeJSON } from "../app.js?v=13";
import * as wallet from "./wallet.js?v=13";
import { decodeUint256, encodeAllowance, encodeApprove } from "./abi.js?v=13";

export const X402_VERSION = 2;

/* The EIP-712 struct the B402 RelayerV3 verifies. Field order is part of the type hash,
   so this tuple is not a set and must not be sorted. */
export const TRANSFER_WITH_AUTHORIZATION = [
  { name: "token", type: "address" },
  { name: "from", type: "address" },
  { name: "to", type: "address" },
  { name: "value", type: "uint256" },
  { name: "validAfter", type: "uint256" },
  { name: "validBefore", type: "uint256" },
  { name: "nonce", type: "bytes32" },
];

export const EIP712_DOMAIN = [
  { name: "name", type: "string" },
  { name: "version", type: "string" },
  { name: "chainId", type: "uint256" },
  { name: "verifyingContract", type: "address" },
];

/* A payment header the server cannot decode. It is how a caller asks for the challenge:
   the hire route reads the header's presence to route the request down the paid path, then
   answers 402 with the offer instead of spending the free allowance on it. The hyphen puts
   it outside the base64 alphabet, so the decode fails for a stated reason. */
const CHALLENGE_PROBE = "challenge-request";

/* Only ever short of the wallet's own signing window: the authorization is bound to the
   reader's clock when no server clock is available, and a browser running ahead of the
   server by more than this would sign a window the server reads as too long. */
const CLOCK_SKEW_MARGIN_S = 30;

/* The authorization is valid from a minute ago, so a server whose clock trails the
   browser's does not read a freshly signed payment as not yet valid. */
const BACKDATE_S = 60;

export class PaymentError extends Error {
  constructor(code, message, { status = null, body = null } = {}) {
    super(message);
    this.name = "PaymentError";
    this.code = code;
    this.error_code = code;
    this.status = status;
    this.body = body;
  }
}

function apiError(status, body, fallbackCode, fallbackMessage) {
  const code =
    (body && body.error && body.error.code) ||
    (body && body.error_code) ||
    fallbackCode;
  const message =
    (body && body.error && body.error.message) ||
    (body && body.message) ||
    fallbackMessage;
  return new PaymentError(code, message, { status, body });
}

async function readBody(response) {
  try {
    return await response.json();
  } catch (cause) {
    return null;
  }
}

/* The server's own clock, read from the response it just sent. Same-origin, so the header
   is readable without any CORS exposure. Used in preference to the browser's clock because
   the server compares `validBefore` against its own `now` plus the advertised timeout: a
   browser one second ahead would otherwise sign a window the server refuses as too long. */
function serverSeconds(response) {
  const header = response.headers.get("date");
  if (!header) return null;
  const parsed = Date.parse(header);
  return Number.isNaN(parsed) ? null : Math.floor(parsed / 1000);
}

function challengeFrom(body, response) {
  const accepts = body && Array.isArray(body.accepts) ? body.accepts : null;
  if (
    !body ||
    body.x402Version !== X402_VERSION ||
    !body.resource ||
    !accepts ||
    accepts.length !== 1
  ) {
    return null;
  }
  const serverNow = serverSeconds(response);
  return {
    x402Version: body.x402Version,
    resource: body.resource,
    accepts,
    server_now_seconds: serverNow,
    /* How far this browser's clock is from the server's, measured once when the challenge
       arrived. Signing uses the offset rather than the absolute reading, because minutes
       can pass between the challenge and the signature — an allowance approval has to be
       mined in between — and a window anchored to a stale instant is a window that has
       already begun expiring. */
    clock_offset_seconds:
      serverNow === null ? null : serverNow - Math.floor(Date.now() / 1000),
    fetched_at_ms: Date.now(),
  };
}

/** Ask one service for its exact payment terms without spending anything.

    `body` is the same request that will carry the payment. It is required because the hire
    route rejects a request missing a declared field before it ever reaches the payment
    branch, and a 422 is not a challenge. Nothing is charged and no allowance is spent:
    Docket routes a request carrying a payment header down the paid path, finds the header
    unreadable, and answers with the offer.

    Encoded by `encodeJSON` rather than `JSON.stringify`: a declared integer field arrives
    from the form as a BigInt, so that a uint256 does not lose its low digits passing
    through JavaScript's Number, and `JSON.stringify` throws on one rather than writing it. */
export async function fetchChallenge(serviceId, body) {
  const path = `/hire/${encodeURIComponent(serviceId)}`;
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        "X-PAYMENT": CHALLENGE_PROBE,
      },
      body: encodeJSON(body),
    });
  } catch (cause) {
    throw new PaymentError(
      "network_error",
      `Could not reach ${path}. Docket may not be running, or the connection dropped.`,
    );
  }
  const payload = await readBody(response);
  const challenge = challengeFrom(payload, response);
  /* 402 is the offer. 429 carries the same offer when the free tier is exhausted but the
     priced tier is open, which is a challenge and not a failure. */
  if (challenge && (response.status === 402 || response.status === 429)) {
    return challenge;
  }
  /* 200 means the service is not admitted to paid stock: the request went down the free
     path and ran. There is nothing to pay for, and saying so is more use than a status. */
  if (response.status === 200) {
    throw new PaymentError(
      "not_for_sale",
      `${serviceId} is not admitted to paid stock, so Docket issues no payment challenge ` +
        "for it. It runs on the free tier instead.",
      { status: 200, body: payload },
    );
  }
  throw apiError(
    response.status,
    payload,
    "challenge_unavailable",
    `${serviceId} did not answer with payment terms.`,
  );
}

/** The token the relayer may pull, the contract that pulls it, and the exact amount. */
export function paymentTerms(challenge) {
  const requirements = challenge.accepts[0];
  const extra = requirements.extra || {};
  const missing = ["name", "version", "chainId", "verifyingContract"].filter(
    (field) => extra[field] === undefined || extra[field] === null,
  );
  if (missing.length) {
    throw new PaymentError(
      "challenge_incomplete",
      `The challenge does not name ${missing.join(", ")}, so nothing can be signed against it.`,
    );
  }
  return {
    requirements,
    token: requirements.asset,
    payTo: requirements.payTo,
    amountAtomic: String(requirements.amount),
    maxTimeoutSeconds: Number(requirements.maxTimeoutSeconds),
    /* The relayer pulls through an ERC-20 allowance, so the spender is the relayer
       contract — the same address that verifies the signature. */
    spender: extra.relayerContract || extra.verifyingContract,
    domain: {
      name: extra.name,
      version: extra.version,
      chainId: Number(extra.chainId),
      verifyingContract: extra.verifyingContract,
    },
  };
}

/** Make sure the relayer may pull `amount`, approving exactly that amount if it may not.

    Docket never requests an unlimited approval. An existing allowance that already covers
    the price belongs to the reader and is left unchanged; this flow neither reduces nor
    revokes permission the reader granted before. */
export async function ensureAllowance(account, token, relayer, amount) {
  const required = BigInt(amount);
  let current;
  try {
    current = decodeUint256(
      await wallet.call({ to: token, data: encodeAllowance(account, relayer) }),
    );
  } catch (cause) {
    throw new PaymentError(
      "allowance_unreadable",
      `The allowance ${account} has given ${relayer} could not be read: ${cause.message}`,
    );
  }
  if (current >= required) {
    return { allowance: current, approved: false, tx_hash: null };
  }
  const hash = await wallet.sendTransaction({
    from: account,
    to: token,
    data: encodeApprove(relayer, required),
  });
  await wallet.waitForReceipt(hash);
  /* Read it back rather than assuming the approval did what it said. A receipt with
     status 0x1 proves the transaction was mined, not that the allowance now covers the
     price: a token with a non-standard approve, or a second approval racing this one, ends
     with a mined receipt and an allowance that is still short. Signing on that assumption
     would produce an authorization the relayer cannot pull. */
  let settled;
  try {
    settled = decodeUint256(
      await wallet.call({ to: token, data: encodeAllowance(account, relayer) }),
    );
  } catch (cause) {
    throw new PaymentError(
      "allowance_unreadable",
      `The approval in ${hash} was mined, but the allowance it should have set could not ` +
        `be read back: ${cause.message}`,
    );
  }
  if (settled < required) {
    throw new PaymentError(
      "allowance_not_applied",
      `The approval in ${hash} was mined and the allowance is still ${settled}, short of ` +
        `the ${required} this payment needs. Nothing was signed.`,
    );
  }
  return { allowance: settled, approved: true, tx_hash: hash };
}

/* How stale a challenge may be before it is worth asking for a fresh one. The allowance
   step in between can take a block or several, and a challenge signed against terms the
   server has since changed is refused for a reason the reader cannot see. */
export const CHALLENGE_MAX_AGE_MS = 120_000;

/** Whether this challenge has been sitting long enough to be worth refetching. */
export function challengeIsStale(challenge, now = Date.now()) {
  return now - Number(challenge.fetched_at_ms || 0) > CHALLENGE_MAX_AGE_MS;
}

/* 32 random bytes from the platform CSPRNG. The nonce is what makes one authorization
   unreplayable, so it is never derived from a counter or a timestamp. */
function randomNonce() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  let hex = "0x";
  for (const byte of bytes) hex += byte.toString(16).padStart(2, "0");
  return hex;
}

/** Sign the exact TransferWithAuthorization the challenge describes.

    The window is anchored to the server's clock when the challenge response carried one.
    The server refuses an authorization whose `validBefore` is further out than its own now
    plus the advertised timeout, so a browser running even a second fast would otherwise
    sign a window that cannot be accepted. Without a server clock the window is shortened
    by a fixed margin instead. */
export async function signPayment(account, challenge) {
  const terms = paymentTerms(challenge);
  const anchored =
    challenge.clock_offset_seconds !== null &&
    challenge.clock_offset_seconds !== undefined;
  const now = anchored
    ? Math.floor(Date.now() / 1000) + Number(challenge.clock_offset_seconds)
    : Math.floor(Date.now() / 1000);
  const authorization = {
    token: terms.token,
    from: account,
    to: terms.payTo,
    value: terms.amountAtomic,
    validAfter: now - BACKDATE_S,
    validBefore:
      now + terms.maxTimeoutSeconds - (anchored ? 0 : CLOCK_SKEW_MARGIN_S),
    nonce: randomNonce(),
  };
  const signature = await wallet.signTypedDataV4(account, {
    types: {
      EIP712Domain: EIP712_DOMAIN,
      TransferWithAuthorization: TRANSFER_WITH_AUTHORIZATION,
    },
    primaryType: "TransferWithAuthorization",
    domain: terms.domain,
    message: authorization,
  });
  return {
    x402Version: X402_VERSION,
    resource: challenge.resource,
    accepted: terms.requirements,
    payload: { authorization, signature },
  };
}

/* Canonical JSON: keys sorted, no insignificant whitespace. Docket's Python side encodes
   the same envelope with `sort_keys=True, separators=(",", ":")`, so an envelope encoded
   here and one encoded there are the same bytes and hash to the same payment id. */
function canonicalJSON(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJSON(item)).join(",")}]`;
  }
  const fields = Object.keys(value)
    .filter((key) => value[key] !== undefined)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJSON(value[key])}`);
  return `{${fields.join(",")}}`;
}

/** The id Docket will file this payment under: SHA-256 over the canonical JSON envelope,
    `0x`-prefixed.

    The same recipe as `docket/hire/receipts.py::canonical_hash`, computed over the same
    object the server parses out of the header. It is derivable here because it has to be:
    a 409 replay says the payment settled and carries no id, and without one the browser
    cannot bind a payment the reader has already made. */
export async function paymentId(envelope) {
  const bytes = new TextEncoder().encode(canonicalJSON(envelope));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return (
    "0x" +
    Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("")
  );
}

/** The `X-PAYMENT` header value: base64 over the canonical JSON envelope. */
export function encodePaymentHeader(envelope) {
  const bytes = new TextEncoder().encode(canonicalJSON(envelope));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** Submit one signed authorization, once.

    Once is the whole point: the authorization is bound to this request's input, and a
    second attempt with the same header is refused as a replay. A caller that has reached
    this function and failed needs a fresh signature, never a retry of the same bytes. */
export async function hireWithPayment(serviceId, body, header) {
  const path = `/hire/${encodeURIComponent(serviceId)}`;
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        "X-PAYMENT": header,
      },
      body: encodeJSON(body),
    });
  } catch (cause) {
    /* The request may or may not have reached the server, so the authorization may or may
       not be spent. Saying which is not possible from here, and guessing would send the
       reader to sign a second payment for work already paid for. */
    throw new PaymentError(
      "payment_outcome_unknown",
      `The connection to ${path} dropped while a signed payment was in flight. Docket ` +
        "cannot tell from the browser whether it settled. Check My agents before signing again.",
    );
  }
  const payload = await readBody(response);
  if (response.status === 200 && payload && payload.receipt) {
    const payment = payload.receipt.payment || {};
    return {
      receipt: payload.receipt,
      result: payload.result,
      payment_id: payment.payment_id || null,
    };
  }
  if (response.status === 409) {
    throw apiError(
      409,
      payload,
      "authorization_replay",
      "That authorization has already been used. Sign a fresh one before trying again.",
    );
  }
  throw apiError(
    response.status,
    payload,
    "payment_failed",
    `${serviceId} did not return a settled result.`,
  );
}
