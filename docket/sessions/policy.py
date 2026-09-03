"""The bounds an owner sets before a session key exists, and the gate that reads them.

`docket/execution/authority.py` says the sentence this file has to repeat, because it is
even more true here: **a check written in Python is not a limit.** A session key held by
Docket is an ordinary EOA. Nothing on chain stops it doing what its key can do, so the
only thing standing between a bug and somebody's funds is the amount that was sent to the
session address in the first place. That is why funding is per-activation and bounded by
`total_cap_atomic` rather than by an approval on the owner's own wallet: the loss ceiling
is the float, and the float is what the owner chose to move.

Everything below is the second gate. It refuses actions the chain would have allowed, and
it is never the only thing refusing.

Two arguments `allows` cannot derive from the bytes it is given and will not guess at:
the gas price of the moment and the slippage the action was drafted against. Both are
checked when the caller supplies them and skipped when it does not, and the caller that
supplies them is `docket.sessions.executor.execute`, which is the one place that knows.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from web3 import Web3

from ..jobs.executors.base import BSC_CHAIN_ID, PreparedCall

# The native coin, keyed alongside the ERC-20s in the cap dictionaries. Spelled as a
# symbol rather than an address because it has none, and left explicit rather than
# implied so a policy that means to bound BNB has to say so.
NATIVE_TOKEN = "BNB"
MAX_BPS = 10_000


def _checksum(address: str, field: str) -> str:
    try:
        return Web3.to_checksum_address(address)
    except Exception as exc:
        raise ValueError(f"{field}: {address!r} is not an address") from exc


def _token_key(token: str) -> str:
    return NATIVE_TOKEN if token == NATIVE_TOKEN else _checksum(token, "token")


@dataclass(frozen=True)
class SessionPolicy:
    """What one session may call, spend, and for how long."""

    contract_allowlist: tuple[str, ...]
    function_allowlist: tuple[str, ...]
    token_allowlist: tuple[str, ...]
    per_action_limit_atomic: dict[str, int]
    total_cap_atomic: dict[str, int]
    max_slippage_bps: int
    max_gas_price_wei: int
    expires_at: str
    emergency_pause: bool = False

    def validate(self) -> None:
        """Refuse a policy that does not bound anything, at the moment it is written.

        An empty allowlist is not a permissive policy here, it is a policy that permits
        nothing; a cap of zero is the same. Both are refused at construction instead,
        because a policy that silently means "never act" reads to its owner as one that
        means "act freely".
        """
        if not self.contract_allowlist:
            raise ValueError("a policy naming no contract permits no call at all")
        if not self.function_allowlist:
            raise ValueError("a policy naming no function permits no call at all")
        if not self.token_allowlist:
            raise ValueError("a policy naming no token permits no spend at all")
        for address in self.contract_allowlist:
            _checksum(address, "contract_allowlist")
        for selector in self.function_allowlist:
            if not (
                selector.startswith("0x")
                and len(selector) == 10
                and all(c in "0123456789abcdefABCDEF" for c in selector[2:])
            ):
                raise ValueError(
                    f"function_allowlist: {selector!r} is not a 4-byte selector"
                )
        for token in self.token_allowlist:
            _token_key(token)
        allowed_tokens = {_token_key(token) for token in self.token_allowlist}
        for name, caps in (
            ("per_action_limit_atomic", self.per_action_limit_atomic),
            ("total_cap_atomic", self.total_cap_atomic),
        ):
            if not caps:
                raise ValueError(f"{name}: a session with no cap is not a bounded one")
            for token, amount in caps.items():
                if _token_key(token) not in allowed_tokens:
                    raise ValueError(
                        f"{name}: {token} is capped but not in token_allowlist"
                    )
                if int(amount) <= 0:
                    raise ValueError(f"{name}: {token} is capped at {amount}")
        for token, amount in self.per_action_limit_atomic.items():
            total = self.total_cap_atomic.get(token)
            if total is None:
                raise ValueError(
                    f"per_action_limit_atomic: {token} has a per-action limit and no "
                    "total cap, so nothing bounds the sum of its actions"
                )
            if int(amount) > int(total):
                raise ValueError(
                    f"per_action_limit_atomic: {token} allows {amount} in one action "
                    f"against a total cap of {total}"
                )
        for token in self.total_cap_atomic:
            if token not in self.per_action_limit_atomic:
                raise ValueError(
                    f"total_cap_atomic: {token} has a total cap and no per-action "
                    "limit, so one action could spend the whole session"
                )
        if not 0 <= int(self.max_slippage_bps) <= MAX_BPS:
            raise ValueError(
                f"max_slippage_bps must be between 0 and {MAX_BPS}, "
                f"not {self.max_slippage_bps}"
            )
        if int(self.max_gas_price_wei) <= 0:
            raise ValueError("max_gas_price_wei of zero would refuse every transaction")
        self.expiry()

    def expiry(self) -> datetime:
        moment = datetime.fromisoformat(self.expires_at)
        if moment.tzinfo is None:
            raise ValueError("expires_at must carry a UTC offset")
        return moment

    def has_expired(self, now: datetime | None = None) -> bool:
        moment = datetime.now(timezone.utc) if now is None else now
        return moment >= self.expiry()

    def allows(
        self,
        call: PreparedCall,
        *,
        spent: dict,
        token_amounts: dict,
        gas_price_wei: int | None = None,
        slippage_bps: int | None = None,
    ) -> tuple[bool, str]:
        """Whether this call is inside every bound, and the first reason it is not.

        One reason rather than a list: the first refusal is the one that has to be fixed,
        and a policy that reports five is a policy whose owner reads none of them.
        """
        if self.emergency_pause:
            return False, "the policy is emergency-paused"
        if self.has_expired():
            return False, f"the policy expired at {self.expires_at}"
        if call.chain_id != BSC_CHAIN_ID:
            return False, f"chain {call.chain_id} is not BSC mainnet"
        contracts = {
            _checksum(a, "contract_allowlist") for a in self.contract_allowlist
        }
        try:
            target = Web3.to_checksum_address(call.to)
        except Exception:
            return False, f"the call target {call.to!r} is not an address"
        if target not in contracts:
            return False, f"{target} is not in the contract allowlist"
        selectors = {selector.lower() for selector in self.function_allowlist}
        if call.selector not in selectors:
            return False, f"selector {call.selector} is not in the function allowlist"
        if gas_price_wei is not None and int(gas_price_wei) > int(
            self.max_gas_price_wei
        ):
            return (
                False,
                f"the gas price {gas_price_wei} wei is above the policy ceiling of "
                f"{self.max_gas_price_wei} wei",
            )
        if slippage_bps is not None and int(slippage_bps) > int(self.max_slippage_bps):
            return (
                False,
                f"{slippage_bps} bps of slippage is above the policy ceiling of "
                f"{self.max_slippage_bps} bps",
            )

        # The native value the call itself carries is a spend like any other and is
        # folded in here rather than left to a caller to remember.
        amounts: dict[str, int] = {
            _token_key(token): int(amount) for token, amount in token_amounts.items()
        }
        value = int(call.value_atomic)
        if value:
            amounts[NATIVE_TOKEN] = amounts.get(NATIVE_TOKEN, 0) + value
        allowed_tokens = {_token_key(token) for token in self.token_allowlist}
        already = {_token_key(token): int(amount) for token, amount in spent.items()}
        per_action = {
            _token_key(token): int(amount)
            for token, amount in self.per_action_limit_atomic.items()
        }
        total = {
            _token_key(token): int(amount)
            for token, amount in self.total_cap_atomic.items()
        }
        for token, amount in sorted(amounts.items()):
            if token not in allowed_tokens:
                return False, f"{token} is not in the token allowlist"
            limit = per_action.get(token)
            if limit is None or amount > limit:
                return (
                    False,
                    f"{amount} of {token} is above the per-action limit of {limit}",
                )
            cap = total.get(token)
            running = already.get(token, 0) + amount
            if cap is None or running > cap:
                return (
                    False,
                    f"{running} of {token} spent in total would pass the session cap "
                    f"of {cap}",
                )
        return True, "inside every bound this policy sets"

    def to_dict(self) -> dict:
        return {
            "contract_allowlist": list(self.contract_allowlist),
            "function_allowlist": list(self.function_allowlist),
            "token_allowlist": list(self.token_allowlist),
            "per_action_limit_atomic": {
                token: str(amount)
                for token, amount in self.per_action_limit_atomic.items()
            },
            "total_cap_atomic": {
                token: str(amount) for token, amount in self.total_cap_atomic.items()
            },
            "max_slippage_bps": int(self.max_slippage_bps),
            "max_gas_price_wei": str(self.max_gas_price_wei),
            "expires_at": self.expires_at,
            "emergency_pause": bool(self.emergency_pause),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SessionPolicy":
        """Build a policy from JSON, refusing anything the shape does not carry.

        Atomic amounts arrive as strings — a 1e18-scaled cap does not survive a JSON
        number — and are parsed here rather than compared as text somewhere later.
        """
        if not isinstance(payload, dict):
            raise ValueError("a session policy must be a JSON object")
        missing = sorted(
            {
                "contract_allowlist",
                "function_allowlist",
                "token_allowlist",
                "per_action_limit_atomic",
                "total_cap_atomic",
                "max_slippage_bps",
                "max_gas_price_wei",
                "expires_at",
            }
            - payload.keys()
        )
        if missing:
            raise ValueError(f"the session policy is missing {', '.join(missing)}")
        return cls(
            contract_allowlist=tuple(payload["contract_allowlist"]),
            function_allowlist=tuple(payload["function_allowlist"]),
            token_allowlist=tuple(payload["token_allowlist"]),
            per_action_limit_atomic={
                token: int(amount)
                for token, amount in payload["per_action_limit_atomic"].items()
            },
            total_cap_atomic={
                token: int(amount)
                for token, amount in payload["total_cap_atomic"].items()
            },
            max_slippage_bps=int(payload["max_slippage_bps"]),
            max_gas_price_wei=int(payload["max_gas_price_wei"]),
            expires_at=str(payload["expires_at"]),
            emergency_pause=bool(payload.get("emergency_pause", False)),
        )
