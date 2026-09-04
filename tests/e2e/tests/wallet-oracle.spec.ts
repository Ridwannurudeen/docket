import { Wallet, verifyMessage, verifyTypedData } from "ethers";
import { expect, test } from "../fixtures";

test("wallet signatures recover with real EIP-191 and EIP-712 cryptography", async ({
  page,
}) => {
  const signer = Wallet.createRandom();
  const message = "Docket activation act_oracle approve nonce-oracle 0xreceipt";
  const domain = {
    name: "USD Tether",
    version: "1",
    chainId: 56,
    verifyingContract: "0x55d398326f99059fF775485246999027B3197955",
  };
  const types = {
    TransferWithAuthorization: [
      { name: "from", type: "address" },
      { name: "to", type: "address" },
      { name: "value", type: "uint256" },
      { name: "validAfter", type: "uint256" },
      { name: "validBefore", type: "uint256" },
      { name: "nonce", type: "bytes32" },
    ],
  };
  const value = {
    from: signer.address,
    to: "0xe55816904796341bf8535e25f6c8b647927fc946",
    value: "500000000000000000",
    validAfter: 0,
    validBefore: 2000000000,
    nonce: "0x" + "ab".repeat(32),
  };
  const personalSignature = await signer.signMessage(message);
  const typedSignature = await signer.signTypedData(domain, types, value);

  await page.addInitScript(
    ({ account, message, personal, typed }) => {
      Object.defineProperty(window, "ethereum", {
        value: {
          async request({ method, params }: { method: string; params?: unknown[] }) {
            if (method === "personal_sign") {
              const expected =
                "0x" +
                Array.from(new TextEncoder().encode(message))
                  .map((byte) => byte.toString(16).padStart(2, "0"))
                  .join("");
              if (params?.[0] !== expected || params?.[1] !== account) {
                throw new Error("personal_sign parameters drifted");
              }
              return personal;
            }
            if (method === "eth_signTypedData_v4") {
              if (params?.[0] !== account || typeof params?.[1] !== "string") {
                throw new Error("eth_signTypedData_v4 parameters drifted");
              }
              return typed;
            }
            if (method === "eth_accounts" || method === "eth_requestAccounts") {
              return [account];
            }
            if (method === "eth_chainId") return "0x38";
            throw Object.assign(new Error(`unsupported ${method}`), { code: 4200 });
          },
        },
      });
    },
    {
      account: signer.address,
      message,
      personal: personalSignature,
      typed: typedSignature,
    },
  );
  await page.goto("/activate");

  const signed = await page.evaluate(
    async ({ account, message, typedData }) => {
      const wallet = await import("/static/js/wallet.js?v=13");
      return {
        personal: await wallet.personalSign(message, account),
        typed: await wallet.signTypedDataV4(account, typedData),
      };
    },
    {
      account: signer.address,
      message,
      typedData: {
        domain,
        types: { ...types, EIP712Domain: [] },
        primaryType: "TransferWithAuthorization",
        message: value,
      },
    },
  );

  expect(verifyMessage(message, signed.personal)).toBe(signer.address);
  expect(verifyTypedData(domain, types, value, signed.typed)).toBe(signer.address);
});
