/* Minimal ABI encoding for the calls the browser makes. Authored here rather than pulled
   from a library: this site ships no third-party JavaScript, and the whole surface is a
   4-byte selector followed by 32-byte words.

   Selectors are the keccak-256 prefixes of the canonical signatures named beside each one.
   They are constants because deriving them in the browser would mean shipping a keccak
   implementation to recompute four values that cannot change; tests/test_web_pages_pivot.py
   re-derives them from the signatures and fails if one drifts. */

export const APPROVE = "0x095ea7b3"; /* approve(address,uint256) */
export const ALLOWANCE = "0xdd62ed3e"; /* allowance(address,address) */
export const BALANCE_OF = "0x70a08231"; /* balanceOf(address) */
export const TRANSFER = "0xa9059cbb"; /* transfer(address,uint256) */

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

export class AbiError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "AbiError";
    this.code = code;
  }
}

/** One 32-byte word holding a left-padded address, lowercased so calldata is byte-stable. */
export function padAddress(value) {
  if (
    !ADDRESS.test(String(value === null || value === undefined ? "" : value))
  ) {
    throw new AbiError(
      "invalid_address",
      `${value} is not a 20-byte hexadecimal address.`,
    );
  }
  return String(value).slice(2).toLowerCase().padStart(64, "0");
}

/** One 32-byte word holding an unsigned integer. BigInt throughout: a uint256 amount does
    not survive JavaScript's Number, and 0.50 USDT is already 5e17 atomic units. */
export function padUint(value) {
  let big;
  try {
    big = BigInt(value);
  } catch (cause) {
    throw new AbiError("invalid_uint", `${value} is not an integer.`);
  }
  if (big < 0n) {
    throw new AbiError(
      "invalid_uint",
      `${value} is negative; uint256 is unsigned.`,
    );
  }
  if (big >= 1n << 256n) {
    throw new AbiError("invalid_uint", `${value} does not fit in a uint256.`);
  }
  return big.toString(16).padStart(64, "0");
}

/** ERC-20 approve(spender, amount). Callers pass the exact amount they owe; this encoder
    has no unlimited form for a call site to reach for. */
export function encodeApprove(spender, amount) {
  return APPROVE + padAddress(spender) + padUint(amount);
}

/** ERC-20 allowance(owner, spender). Read through eth_call, never sent. */
export function encodeAllowance(owner, spender) {
  return ALLOWANCE + padAddress(owner) + padAddress(spender);
}

/** ERC-20 balanceOf(owner). Read through eth_call. */
export function encodeBalanceOf(owner) {
  return BALANCE_OF + padAddress(owner);
}

/** ERC-721 approve(to, tokenId). The signature — and so the selector — is identical to
    ERC-20's approve; only the second word's meaning differs. Named separately because a
    call site should read as what it authorises, which is one position and not an amount. */
export function encodeErc721Approve(to, tokenId) {
  return APPROVE + padAddress(to) + padUint(tokenId);
}

/** ERC-20 transfer(to, amount). */
export function encodeTransfer(to, amount) {
  return TRANSFER + padAddress(to) + padUint(amount);
}

/** Read one uint256 out of an eth_call return. An empty return means the call reached a
    non-contract or reverted with no data, and that is reported rather than read as zero:
    "the allowance is nothing" and "the allowance was not read" lead to different actions. */
export function decodeUint256(data) {
  const hex = String(data === null || data === undefined ? "" : data).replace(
    /^0x/,
    "",
  );
  if (hex.length < 64) {
    throw new AbiError(
      "empty_return",
      "The call returned no 32-byte word, so nothing was read.",
    );
  }
  if (!/^[0-9a-fA-F]+$/.test(hex)) {
    throw new AbiError(
      "invalid_return",
      "The call returned data that is not hexadecimal.",
    );
  }
  return BigInt("0x" + hex.slice(0, 64));
}
