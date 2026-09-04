/* The browser's wallet, reached through EIP-1193 and nothing else. No connector library,
   no injected SDK, no vendor branch: every wallet Docket supports is one that exposes
   `window.ethereum.request`.

   Every function here throws a `WalletError` carrying a `code` the page can render. The
   provider's own numeric codes are mapped to those names rather than surfaced raw, because
   "4001" is not something to put in front of a reader — and an unmapped provider error keeps
   its own message so a wallet-specific failure is not flattened into a generic one. */

export const BSC_CHAIN_ID = "0x38"; /* 56 */

/* The parameters wallet_addEthereumChain needs when the wallet has never seen BSC. Public
   endpoints only: Docket never asks a reader's wallet to trust an RPC that Docket operates. */
export const BSC_CHAIN_PARAMS = {
  chainId: BSC_CHAIN_ID,
  chainName: "BNB Smart Chain",
  nativeCurrency: { name: "BNB", symbol: "BNB", decimals: 18 },
  rpcUrls: ["https://bsc-dataseed.binance.org"],
  blockExplorerUrls: ["https://bscscan.com"],
};

export class WalletError extends Error {
  constructor(code, message, cause) {
    super(message);
    this.name = "WalletError";
    this.code = code;
    if (cause !== undefined) this.cause = cause;
  }
}

/* EIP-1193 and EIP-1474 numeric codes, in Docket's own words. A reader who cancelled a
   prompt has not hit an error and should not be told they have. */
const PROVIDER_CODES = {
  4001: [
    "user_rejected",
    "You dismissed the wallet prompt. Nothing was signed and nothing was sent.",
  ],
  4100: [
    "not_authorized",
    "The wallet has not authorised this account for that request. Reconnect and try again.",
  ],
  4200: [
    "unsupported_method",
    "This wallet does not implement the method Docket needs for that step.",
  ],
  4900: ["wallet_disconnected", "The wallet is not connected to any chain."],
  4901: [
    "chain_disconnected",
    "The wallet is not connected to BNB Smart Chain right now.",
  ],
  4902: [
    "chain_not_added",
    "This wallet does not have BNB Smart Chain configured yet.",
  ],
  "-32002": [
    "request_pending",
    "A wallet prompt is already open. Finish or dismiss it, then try again.",
  ],
  "-32602": [
    "invalid_request",
    "The wallet rejected the shape of that request.",
  ],
  "-32603": [
    "wallet_internal_error",
    "The wallet failed internally while handling that request.",
  ],
};

/* Wallets nest the code they mean. MetaMask wraps a provider rejection in a -32603
   "internal error" whose real cause is at `data.originalError.code`, and some wrappers nest
   that again; reading only the top level turns "this chain is not configured" into an
   unexplained internal error, and `ensureBsc` never offers to add the chain. */
function providerCode(cause, depth = 0) {
  if (!cause || depth > 4) return null;
  const code = cause.code;
  if (code !== undefined && code !== null && code !== -32603) return code;
  const nested =
    (cause.data && (cause.data.originalError || cause.data)) || cause.originalError;
  return providerCode(nested, depth + 1) ?? (code ?? null);
}

function asWalletError(cause, fallbackCode, fallbackMessage) {
  if (cause instanceof WalletError) return cause;
  const raw = providerCode(cause);
  const known =
    raw !== null && Object.prototype.hasOwnProperty.call(PROVIDER_CODES, raw)
      ? PROVIDER_CODES[raw]
      : null;
  if (known) return new WalletError(known[0], known[1], cause);
  const detail = cause && cause.message ? ` ${cause.message}` : "";
  return new WalletError(fallbackCode, `${fallbackMessage}${detail}`, cause);
}

/** The injected EIP-1193 provider, or a typed refusal naming what is missing. */
export function detectProvider() {
  const provider = typeof window === "undefined" ? null : window.ethereum;
  if (!provider || typeof provider.request !== "function") {
    throw new WalletError(
      "no_wallet",
      "No EIP-1193 wallet is available in this browser. Docket holds no key of yours, " +
        "so every signature has to come from a wallet you control.",
    );
  }
  return provider;
}

/** Whether a wallet is present at all, for pages that offer a read-only view without one. */
export function hasProvider() {
  try {
    detectProvider();
    return true;
  } catch (err) {
    return false;
  }
}

async function request(method, params) {
  const provider = detectProvider();
  try {
    return await provider.request(
      params === undefined ? { method } : { method, params },
    );
  } catch (cause) {
    throw asWalletError(cause, "wallet_request_failed", `${method} failed.`);
  }
}

function firstAccount(accounts) {
  if (!Array.isArray(accounts) || accounts.length === 0 || !accounts[0]) {
    throw new WalletError(
      "no_account",
      "The wallet returned no account. Unlock it and select an account, then try again.",
    );
  }
  return String(accounts[0]);
}

/** Ask for accounts, prompting the reader if the site is not connected yet. */
export async function connect() {
  return firstAccount(await request("eth_requestAccounts"));
}

/** The already-authorised account, or null. Never prompts, so a page can paint its
    connected state on load without opening a wallet dialog nobody asked for. */
export async function currentAccount() {
  try {
    const accounts = await request("eth_accounts");
    return Array.isArray(accounts) && accounts.length
      ? String(accounts[0])
      : null;
  } catch (err) {
    return null;
  }
}

/** The chain the wallet is on, as the provider's own hex string. */
export async function chainId() {
  return String(await request("eth_chainId"));
}

/** Put the wallet on BNB Smart Chain, adding the chain first if it does not know it.

    Switching is attempted before adding, in that order: a wallet that already has BSC
    configured keeps whatever RPC its owner chose, and Docket does not overwrite it. */
export async function ensureBsc() {
  const current = await chainId();
  if (current.toLowerCase() === BSC_CHAIN_ID) return BSC_CHAIN_ID;
  try {
    await request("wallet_switchEthereumChain", [{ chainId: BSC_CHAIN_ID }]);
  } catch (err) {
    if (err.code !== "chain_not_added") throw err;
    await request("wallet_addEthereumChain", [BSC_CHAIN_PARAMS]);
    await request("wallet_switchEthereumChain", [{ chainId: BSC_CHAIN_ID }]);
  }
  const settled = await chainId();
  if (settled.toLowerCase() !== BSC_CHAIN_ID) {
    throw new WalletError(
      "wrong_chain",
      `The wallet is on ${settled} and Docket only settles on BNB Smart Chain (${BSC_CHAIN_ID}).`,
    );
  }
  return BSC_CHAIN_ID;
}

function subscribe(event, handler) {
  const provider = detectProvider();
  if (typeof provider.on !== "function") return () => {};
  provider.on(event, handler);
  return () => {
    if (typeof provider.removeListener === "function") {
      provider.removeListener(event, handler);
    }
  };
}

/** Call back when the wallet switches accounts. Returns an unsubscribe function. */
export function onAccountsChanged(handler) {
  return subscribe("accountsChanged", (accounts) => {
    handler(
      Array.isArray(accounts) && accounts.length ? String(accounts[0]) : null,
    );
  });
}

/** Call back when the wallet switches chains. Returns an unsubscribe function. */
export function onChainChanged(handler) {
  return subscribe("chainChanged", (id) => handler(String(id)));
}

/* personal_sign takes the message as hex. A wallet handed raw UTF-8 either renders it as
   bytes or rejects it outright, and hex is what every implementation agrees on. The server
   recovers with EIP-191 `encode_defunct`, which reads the same bytes back. */
function toHexUtf8(message) {
  const bytes = new TextEncoder().encode(String(message));
  let hex = "0x";
  for (const byte of bytes) hex += byte.toString(16).padStart(2, "0");
  return hex;
}

/** EIP-191 personal_sign of the exact message the server issued. */
export async function personalSign(message, account) {
  const signature = await request("personal_sign", [
    toHexUtf8(message),
    account,
  ]);
  if (typeof signature !== "string" || !signature.startsWith("0x")) {
    throw new WalletError(
      "bad_signature_shape",
      "The wallet returned something that is not a signature.",
    );
  }
  return signature;
}

/** EIP-712 eth_signTypedData_v4. The typed data goes over the wire as a JSON string,
    which is what the method takes — an object is silently rejected by most wallets. */
export async function signTypedDataV4(account, typedData) {
  const signature = await request("eth_signTypedData_v4", [
    account,
    JSON.stringify(typedData),
  ]);
  if (typeof signature !== "string" || !signature.startsWith("0x")) {
    throw new WalletError(
      "bad_signature_shape",
      "The wallet returned something that is not a signature.",
    );
  }
  return signature;
}

/** Send one transaction and return its hash. The wallet chooses gas; Docket never
    overrides it, because a ceiling guessed here would be a ceiling the reader cannot see. */
export async function sendTransaction(tx) {
  const hash = await request("eth_sendTransaction", [tx]);
  if (typeof hash !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(hash)) {
    throw new WalletError(
      "bad_transaction_hash",
      "The wallet returned something that is not a transaction hash.",
    );
  }
  return hash;
}

/** eth_call against the latest block. Reads only; nothing here can spend. */
export async function call(tx) {
  return await request("eth_call", [tx, "latest"]);
}

/** The receipt for one hash, or null while it is still pending. */
export async function transactionReceipt(hash) {
  const receipt = await request("eth_getTransactionReceipt", [hash]);
  return receipt || null;
}

/** Wait for one transaction to be mined, then hand back its receipt.

    Polls rather than subscribing: `eth_subscribe` is not available over every injected
    provider, and a page that silently never resolves is worse than one that says it timed
    out. A receipt whose status is not 0x1 is a failure and is reported as one. */
export async function waitForReceipt(
  hash,
  { attempts = 60, intervalMs = 3000 } = {},
) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const receipt = await transactionReceipt(hash);
    if (receipt) {
      if (String(receipt.status).toLowerCase() === "0x0") {
        throw new WalletError(
          "transaction_reverted",
          `Transaction ${hash} was mined and reverted. Nothing it would have authorised took effect.`,
        );
      }
      return receipt;
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
  }
  throw new WalletError(
    "receipt_timeout",
    `Transaction ${hash} was submitted but has not been mined within ` +
      `${Math.round((attempts * intervalMs) / 1000)} seconds. It may still confirm; ` +
      "check it in your wallet before sending another.",
  );
}
