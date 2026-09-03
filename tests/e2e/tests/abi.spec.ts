import { expect, test } from "../fixtures";

/* The encoders, run in the browser and checked against calldata produced by `eth-abi` —
   the library the server side already depends on. Docket ships no third-party JavaScript,
   so this module is hand-written, and hand-written ABI encoding is exactly the kind of code
   that is silently wrong: a byte of padding in the wrong place still looks like calldata.
   Every vector below was generated with

       from eth_utils import function_signature_to_4byte_selector as sel
       from eth_abi import encode
       sel(signature).hex() + encode(types, args).hex()

   so this compares two independent implementations rather than the module with itself.
   The vectors are stored without their `0x` prefix and it is added back in the assertion. */

const RELAYER = "0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88";
const HOLDER = "0x1111111111111111111111111111111111111111";
const MAX_UINT256 =
  "115792089237316195423570985008687907853269984665640564039457584007913129639935";

const VECTORS = [
  {
    name: "approve(address,uint256)",
    call: "encodeApprove",
    args: [RELAYER, "500000000000000000"],
    expected:
      "095ea7b3000000000000000000000000e1af7daea624ba3b5073f24a6ea5531434d82d88" +
      "00000000000000000000000000000000000000000000000006f05b59d3b20000",
  },
  {
    name: "allowance(address,address)",
    call: "encodeAllowance",
    args: [HOLDER, RELAYER],
    expected:
      "dd62ed3e0000000000000000000000001111111111111111111111111111111111111111" +
      "000000000000000000000000e1af7daea624ba3b5073f24a6ea5531434d82d88",
  },
  {
    name: "balanceOf(address)",
    call: "encodeBalanceOf",
    args: [HOLDER],
    expected:
      "70a082310000000000000000000000001111111111111111111111111111111111111111",
  },
  {
    name: "ERC-721 approve(address,uint256)",
    call: "encodeErc721Approve",
    args: [HOLDER, 7141050],
    expected:
      "095ea7b30000000000000000000000001111111111111111111111111111111111111111" +
      "00000000000000000000000000000000000000000000000000000000006cf6ba",
  },
  {
    name: "transfer(address,uint256)",
    call: "encodeTransfer",
    args: [RELAYER, 1],
    expected:
      "a9059cbb000000000000000000000000e1af7daea624ba3b5073f24a6ea5531434d82d88" +
      "0000000000000000000000000000000000000000000000000000000000000001",
  },
  {
    name: "approve at the top of uint256",
    call: "encodeApprove",
    args: [RELAYER, MAX_UINT256],
    expected:
      "095ea7b3000000000000000000000000e1af7daea624ba3b5073f24a6ea5531434d82d88" +
      "f".repeat(64),
  },
];

test("every encoder matches calldata built by eth-abi", async ({ page }) => {
  await page.goto("/activate");
  for (const vector of VECTORS) {
    const encoded = await page.evaluate(
      async ([call, args]) => {
        const abi = await import("/static/js/abi.js?v=13");
        return (abi as Record<string, (...a: unknown[]) => string>)[
          call as string
        ](...(args as unknown[]));
      },
      [vector.call, vector.args] as const,
    );
    expect(encoded, vector.name).toBe("0x" + vector.expected);
  }
});

test("the decoder reads a uint256 back and refuses an empty return", async ({
  page,
}) => {
  await page.goto("/activate");
  const outcome = await page.evaluate(async () => {
    const abi = await import("/static/js/abi.js?v=13");
    const word = "0x" + 12345n.toString(16).padStart(64, "0");
    const max = "0x" + "f".repeat(64);
    const errors: string[] = [];
    for (const bad of ["", "0x", "0xabc", "0x" + "z".repeat(64)]) {
      try {
        abi.decodeUint256(bad);
        errors.push("accepted:" + bad);
      } catch (err) {
        errors.push((err as { code: string }).code);
      }
    }
    return {
      word: abi.decodeUint256(word).toString(),
      max: abi.decodeUint256(max).toString(),
      errors,
    };
  });

  expect(outcome.word).toBe("12345");
  expect(outcome.max).toBe(MAX_UINT256);
  /* An unread allowance and a zero allowance lead to different actions, so neither an
     empty return nor a short one may come back as 0. */
  expect(outcome.errors).toEqual([
    "empty_return",
    "empty_return",
    "empty_return",
    "invalid_return",
  ]);
});

test("an encoder refuses input it cannot represent rather than truncating it", async ({
  page,
}) => {
  await page.goto("/activate");
  const codes = await page.evaluate(async () => {
    const abi = await import("/static/js/abi.js?v=13");
    const holder = "0x1111111111111111111111111111111111111111";
    const attempts: Array<() => unknown> = [
      () => abi.encodeApprove("0xnotanaddress", 1),
      () => abi.encodeApprove("0x1111", 1),
      () => abi.encodeApprove(holder, -1),
      () => abi.encodeApprove(holder, 1n << 256n),
      () => abi.encodeApprove(holder, "1.5"),
    ];
    return attempts.map((attempt) => {
      try {
        attempt();
        return "accepted";
      } catch (err) {
        return (err as { code: string }).code;
      }
    });
  });

  expect(codes).toEqual([
    "invalid_address",
    "invalid_address",
    "invalid_uint",
    "invalid_uint",
    "invalid_uint",
  ]);
});
