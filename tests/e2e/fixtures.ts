import { expect, test as base, type Page, type Route } from "@playwright/test";

/* What these tests stand in for, and what they do not.

   The wallet is faked, because a real one needs a key, a chain and a person. The
   activation, marketplace and provider APIs are faked, because they belong to other lanes
   and are not in this branch. Everything else is real: the pages, their entry modules, the
   wallet module's EIP-1193 conversation, the ABI encoding, the x402 envelope, the canonical
   JSON, the base64, and the server that serves the shells.

   So these tests answer "does the browser do the right thing with the right shapes", and
   they are deliberately unable to answer "is the signature one BSC would accept". The
   second question is the canary's, and it is answered against a real chain. */

export const ACCOUNT = "0x1111111111111111111111111111111111111111";
export const USDT = "0x55d398326f99059fF775485246999027B3197955";
export const RELAYER = "0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88";
export const PAY_TO = "0xe55816904796341bf8535e25f6c8b647927fc946";
export const PRICE_ATOMIC = "500000000000000000";

/** The service record `/services/{id}` returns, trimmed to what the page reads and with
    `paid_stock` true — a fresh database has no canary run, so the real route says false and
    the paid control would never render. */
export const SERVICE = {
  service_id: "range-doctor",
  name: "Range Doctor",
  category: "rebalancing",
  category_job: "Keep LP earning",
  what_you_get:
    "A read-only diagnosis of the PancakeSwap v3 liquidity positions a BSC wallet holds.",
  price_display: "0.50 USDT",
  price_atomic: 500000000000000000,
  asset: USDT,
  paid_stock: true,
  stock_status: "admitted",
  admission: {
    fresh_paired_benchmark: true,
    cold_canary: true,
    decision_grade_presenter: true,
    true_settlement: true,
  },
  typical_seconds: 30,
  activation: "one_shot",
  activation_means: "Runs once when you activate it and hands back a result.",
  evidence_modality: "live_read",
  metrics: [
    {
      name: "Position NFTs read",
      unit: "position NFTs the wallet held",
      window: "one recorded run against one wallet",
      observed_at: "2026-08-08",
      method: "advantage task 01, agent arm",
      value: null,
      numerator: 14,
      denominator: 14,
      display: "14 of 14 position NFTs the wallet held",
    },
  ],
  agent_id: "56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432:311253",
  identity: "Registered as ERC-8004 identity 311253 on BSC.",
  hire_method: "POST",
  hire_path: "/hire/range-doctor",
  registration_uri: "https://example.invalid/registration.json",
  input_schema: {
    wallet: {
      type: "string",
      required: true,
      description: "The BSC wallet whose positions are read.",
      default: PAY_TO,
      example_note:
        "The worked example reads the wallet behind advantage task 01.",
    },
    token_id: {
      type: "integer",
      required: false,
      description: "One position NFT to detail.",
      default: 7141050,
    },
  },
  limitations: "It reads. It never signs, approves or moves anything.",
  evidence: [
    {
      kind: "run",
      url: "/advantage/v1/01-liquidity",
      label: "Advantage task 01",
    },
  ],
  agent_path: null,
  identity_note: "That identity is not in the snapshot being served.",
};

export const RESULT = {
  service_id: "range-doctor",
  wallet: PAY_TO,
  positions_examined: 14,
  summary:
    "One position sits inside its range; thirteen are closed and were not detailed.",
};

export const RECEIPT = {
  service: "range-doctor",
  delivered_at: "2026-09-03T10:00:00Z",
  input_hash: "0x" + "a".repeat(64),
  output_hash: "0x" + "b".repeat(64),
  payment: {
    status: "settled",
    payment_id: "0x" + "c".repeat(64),
    nonce: "0x" + "d".repeat(64),
    transaction_id: "0x" + "e".repeat(64),
    amount: PRICE_ATOMIC,
    asset: USDT,
    recipient: PAY_TO,
    payer: ACCOUNT,
  },
};

export function activation(overrides: Record<string, unknown> = {}) {
  return {
    activation_id: "act_0123456789abcdef01234567",
    service_id: "range-doctor",
    category: "rebalancing",
    kind: "one_shot",
    owner: ACCOUNT,
    state: "authorized",
    quote: {
      asset: USDT,
      amount_atomic: PRICE_ATOMIC,
      amount_display: "0.50 USDT",
      pay_to: PAY_TO,
      payment_scheme: "x402-exact",
    },
    policy: null,
    session: null,
    inputs: { wallet: PAY_TO },
    result: null,
    receipts: [],
    events: [],
    next_action: { kind: "wait", detail: {} },
    auth_nonce: "nonce-two",
    created_at: "2026-09-03T09:59:00Z",
    updated_at: "2026-09-03T10:00:00Z",
    expires_at: "2026-09-04T09:59:00Z",
    ...overrides,
  };
}

/* ------------------------------------------------------------ the fake wallet */

/* An EIP-1193 provider with no key behind it. Signatures are derived from what was signed,
   so a test can assert that a control asked for a signature over the exact message the
   server issued rather than over something the page made up. `window.__wallet` is the
   control surface: a test flips `rejectNext` to make the reader dismiss a prompt, or
   `allowance` to make the relayer's allowance short. */
export const WALLET_INIT = ({
  account,
  chainId,
}: {
  account: string;
  chainId: string;
}) => {
  const script = (config: { account: string; chainId: string }) => {
    const calls: Array<{ method: string; params: unknown }> = [];
    const listeners: Record<string, Array<(value: unknown) => void>> = {};
    const control = {
      account: config.account,
      chainId: config.chainId,
      allowance: (1n << 255n).toString(16).padStart(64, "0"),
      rejectNext: null as string | null,
      failNext: null as {
        method: string;
        code: number;
        message: string;
      } | null,
      calls,
    };

    const digest = (input: string) => {
      /* FNV-1a over the payload, expanded to 65 bytes. Deterministic and reversible by a
         test, which is the only property a fake signature needs. */
      let hash = 0x811c9dc5;
      for (let index = 0; index < input.length; index += 1) {
        hash ^= input.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193) >>> 0;
      }
      let hex = "";
      let state = hash;
      for (let byte = 0; byte < 65; byte += 1) {
        state = (Math.imul(state, 0x01000193) ^ byte) >>> 0;
        hex += (state & 0xff).toString(16).padStart(2, "0");
      }
      return "0x" + hex;
    };

    const provider = {
      isDocketTestWallet: true,
      async request({
        method,
        params,
      }: {
        method: string;
        params?: unknown[];
      }) {
        calls.push({ method, params: params ?? null });
        if (control.failNext && control.failNext.method === method) {
          const failure = control.failNext;
          control.failNext = null;
          const error = new Error(failure.message) as Error & { code: number };
          error.code = failure.code;
          throw error;
        }
        if (control.rejectNext === method) {
          control.rejectNext = null;
          const error = new Error("User rejected the request.") as Error & {
            code: number;
          };
          error.code = 4001;
          throw error;
        }
        switch (method) {
          case "eth_requestAccounts":
          case "eth_accounts":
            return control.account ? [control.account] : [];
          case "eth_chainId":
            return control.chainId;
          case "wallet_switchEthereumChain":
            control.chainId = "0x38";
            return null;
          case "wallet_addEthereumChain":
            return null;
          case "personal_sign":
            return digest(`personal:${String((params ?? [])[0])}`);
          case "eth_signTypedData_v4":
            return digest(`typed:${String((params ?? [])[1])}`);
          case "eth_sendTransaction":
            return digest(`tx:${JSON.stringify((params ?? [])[0])}`).slice(
              0,
              66,
            );
          case "eth_call":
            return "0x" + control.allowance;
          case "eth_getTransactionReceipt":
            return {
              status: "0x1",
              transactionHash: String((params ?? [])[0]),
            };
          default:
            throw Object.assign(new Error(`unsupported ${method}`), {
              code: 4200,
            });
        }
      },
      on(event: string, handler: (value: unknown) => void) {
        (listeners[event] ??= []).push(handler);
      },
      removeListener(event: string, handler: (value: unknown) => void) {
        listeners[event] = (listeners[event] ?? []).filter(
          (one) => one !== handler,
        );
      },
      emit(event: string, value: unknown) {
        for (const handler of listeners[event] ?? []) handler(value);
      },
    };

    Object.defineProperty(window, "ethereum", {
      value: provider,
      writable: true,
    });
    Object.defineProperty(window, "__wallet", {
      value: control,
      writable: true,
    });
  };
  return { script, arg: { account, chainId } };
};

export async function installWallet(
  page: Page,
  { account = ACCOUNT, chainId = "0x38" } = {},
) {
  const { script, arg } = WALLET_INIT({ account, chainId });
  await page.addInitScript(script, arg);
}

/** No wallet at all: the page has to say so rather than render a broken control. */
export async function installNoWallet(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(window, "ethereum", {
      value: undefined,
      writable: true,
    });
  });
}

/* ------------------------------------------------------------- the fake server */

function json(
  route: Route,
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
) {
  return route.fulfill({
    status,
    contentType: "application/json",
    headers: { date: new Date().toUTCString(), ...headers },
    body: JSON.stringify(body),
  });
}

export type HireOutcome =
  | { kind: "settled" }
  | { kind: "replay" }
  | { kind: "facilitator_rejected" }
  | { kind: "service_failed" };

export async function mockServices(page: Page, record = SERVICE) {
  await page.route("**/services/range-doctor", (route) =>
    json(route, 200, record),
  );
  await page.route("**/services?category=*", (route) =>
    json(route, 200, {
      services: [record],
      total: 1,
      category: record.category,
      ordering: "declared",
      declaration: "Docket's own declaration about services Docket runs.",
    }),
  );
}

export async function mockHire(
  page: Page,
  outcome: HireOutcome = { kind: "settled" },
) {
  await page.route("**/hire/range-doctor", async (route) => {
    const header = route.request().headers()["x-payment"];
    if (!header) {
      return json(route, 200, {
        result: RESULT,
        receipt: { ...RECEIPT, payment: { status: "free_tier" } },
      });
    }
    if (header === "challenge-request") {
      return json(route, 402, {
        x402Version: 2,
        resource: {
          url: `${new URL(route.request().url()).origin}/hire/range-doctor`,
          description: SERVICE.what_you_get,
          mimeType: "application/json",
        },
        accepts: [
          {
            scheme: "exact",
            network: "eip155:56",
            amount: PRICE_ATOMIC,
            asset: USDT,
            payTo: PAY_TO,
            maxTimeoutSeconds: 300,
            extra: {
              assetTransferMethod: "b402-relayer",
              name: "B402",
              version: "1",
              chainId: 56,
              verifyingContract: RELAYER,
              relayerContract: RELAYER,
            },
          },
        ],
        error: {
          code: "payment_invalid",
          message:
            "The payment header is not a base64-encoded JSON PaymentPayload. No work ran.",
        },
      });
    }
    if (outcome.kind === "replay") {
      return json(route, 409, {
        error: {
          code: "authorization_replay",
          message: "That authorization already settled and cannot be replayed.",
        },
      });
    }
    if (outcome.kind === "facilitator_rejected") {
      return json(route, 402, {
        error: {
          code: "payment_not_verified",
          message:
            "The facilitator rejected the payment. No work ran and no charge was attempted.",
        },
      });
    }
    if (outcome.kind === "service_failed") {
      return json(route, 502, {
        error: {
          code: "service_failed",
          message:
            "range-doctor could not complete this request. No settlement ran.",
        },
      });
    }
    return json(route, 200, { result: RESULT, receipt: RECEIPT });
  });
}

export async function mockActivations(
  page: Page,
  {
    onCreate = activation(),
    afterApprove = activation({
      state: "completed",
      result: RESULT,
      receipts: [RECEIPT],
    }),
    /* Successive answers to `GET /api/activations/{id}`, one per poll, the last repeating.
       Omitting it is a server that never moves; two or more entries drive the page's own
       polling loop through a real state change. */
    poll = null as Array<ReturnType<typeof activation>> | null,
    listing = [] as Array<ReturnType<typeof activation>>,
    approveError = null as {
      status: number;
      error_code: string;
      message: string;
    } | null,
  } = {},
) {
  await page.route("**/api/activations/nonce*", (route) =>
    json(route, 200, {
      nonce: "nonce-one",
      message: "Docket activation create range-doctor nonce-one",
      expires_at: "2026-09-03T10:15:00Z",
      expires_in_seconds: 900,
    }),
  );
  await page.route("**/api/activations/*/approve", (route) =>
    approveError
      ? json(route, approveError.status, {
          error_code: approveError.error_code,
          message: approveError.message,
        })
      : json(route, 200, afterApprove),
  );
  await page.route("**/api/activations/*/pause", (route) =>
    json(
      route,
      200,
      activation({
        kind: "persistent",
        state: "paused",
        auth_nonce: "nonce-three",
      }),
    ),
  );
  await page.route("**/api/activations/*/cancel", (route) =>
    json(
      route,
      200,
      activation({ state: "failed", auth_nonce: "nonce-three" }),
    ),
  );
  await page.route("**/api/activations/*/revoke", (route) =>
    json(
      route,
      200,
      activation({
        kind: "persistent",
        state: "revoked",
        auth_nonce: "nonce-three",
      }),
    ),
  );
  await page.route("**/api/activations?owner=*", (route) =>
    json(route, 200, { activations: listing, total: listing.length }),
  );
  await page.route("**/api/activations", (route) =>
    route.request().method() === "POST"
      ? json(route, 201, onCreate)
      : json(route, 200, { activations: listing, total: listing.length }),
  );
  let polled = 0;
  await page.route("**/api/activations/act_*", (route) => {
    if (!poll) return json(route, 200, afterApprove);
    const answer = poll[Math.min(polled, poll.length - 1)];
    polled += 1;
    return json(route, 200, answer);
  });
}

/** `/api/agents` answers with `items`, plus the paging and registry-lookup fields the
    marketplace router serves. */
export async function mockAgents(
  page: Page,
  items: unknown[],
  { registryLookup = { attempted: false, hydrated: 0, reason: null } } = {},
) {
  await page.route("**/api/agents*", (route) =>
    json(route, 200, {
      items,
      total: items.length,
      limit: 25,
      offset: 0,
      filters: { q: null, category: null, level: null },
      registry_lookup: registryLookup,
      levels: [
        "registered",
        "endpoint_detected",
        "live",
        "payment_tested",
        "docket_tested",
        "docket_verified",
      ],
      listings_by_level: {},
    }),
  );
}

/* The provider routes as the marketplace router serves them: `claim` with only
   `{agent_id}` mints a nonce and prints the sentence to sign, and `listings` spends that
   same nonce, so there is no separate spend step. */
export async function mockProviders(
  page: Page,
  {
    evidence = [] as Array<{ level: string; ok: boolean; at?: string }>,
    level = "docket_tested" as string | null,
    paymentTested = false,
    hireable = false,
    listingError = null as { status: number; error_code: string; message: string } | null,
  } = {},
) {
  await page.route("**/api/providers/claim", (route) =>
    json(route, 201, {
      agent_id: "311253",
      nonce: "claim-nonce",
      message: "Docket provider claim 311253 claim-nonce",
      issued_at: "2026-09-03T10:00:00Z",
      expires_in_seconds: 900,
    }),
  );
  await page.route("**/api/providers/listings", (route) =>
    listingError
      ? json(route, listingError.status, {
          error_code: listingError.error_code,
          message: listingError.message,
        })
      : json(route, 201, {
          listing: {
            agent_id: "311253",
            chain_id: 56,
            name: "Somebody's Range Agent",
            owner: ACCOUNT,
            endpoints: [{ kind: "a2a", url: "https://example.invalid/a2a" }],
            category: "rebalancing",
            capability_source: "provider_declared",
            capabilities: "Rebalances v3 ranges",
            price: "0.50 USDT",
            payment_method: "x402",
            verification: {
              level,
              payment_tested: paymentTested,
              payment_tested_evidence: null,
              evidence,
              verified_at: "2026-09-03T10:00:00Z",
            },
            hireable,
            source: "provider_submitted",
            updated_at: "2026-09-03T10:00:00Z",
          },
        }),
  );
}

/** The exact message a control signed, read back out of the fake wallet's call log. */
export async function signedMessages(page: Page) {
  return await page.evaluate(() => {
    const decode = (hex: string) => {
      const bytes = hex.replace(/^0x/, "").match(/.{2}/g) ?? [];
      return new TextDecoder().decode(
        Uint8Array.from(bytes.map((byte) => parseInt(byte, 16))),
      );
    };
    return (
      window as unknown as {
        __wallet: { calls: Array<{ method: string; params: unknown }> };
      }
    ).__wallet.calls
      .filter((call) => call.method === "personal_sign")
      .map((call) => decode(String((call.params as unknown[])[0])));
  });
}

export const test = base;
export { expect };
