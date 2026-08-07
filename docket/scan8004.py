"""Client for 8004scan's internal API.

Two APIs exist on 8004scan with incompatible conventions. This targets the
internal one (`/api/v1`, snake_case params, 180 req/min + 20k/day, no key),
because it is the only one exposing `min_feedbacks`/`min_score` and it carries
18x the anonymous quota of the documented public API. Verified 2026-08-07.

Not used deliberately: `/agents/search` (returns 502) and `/feedbacks?tokenId=`
(silently ignores the filter).
"""

import time

import httpx

API_BASE = "https://8004scan.io/api/v1"
MAX_LIMIT = 100
MAX_ATTEMPTS = 4
BACKOFF_S = (1.0, 3.0, 8.0)
# 180 req/min ceiling; pace below it so a long sweep never trips the limiter.
MIN_INTERVAL_S = 0.4


class Scan8004Client:
    def __init__(
        self,
        base_url: str = API_BASE,
        transport: httpx.BaseTransport | None = None,
        pace: bool = True,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=30.0,
            headers={"accept": "application/json"},
        )
        self._pace = pace
        self._last_call = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Scan8004Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        if not self._pace:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: dict) -> dict:
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            try:
                resp = self._client.get(path, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = httpx.HTTPStatusError(
                        f"{resp.status_code} from {path}", request=resp.request, response=resp
                    )
                else:
                    resp.raise_for_status()
                    return resp.json()
            except httpx.TransportError as exc:
                last = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
        raise last  # type: ignore[misc]

    def list_agents(
        self,
        chain_id: int,
        *,
        limit: int = MAX_LIMIT,
        offset: int = 0,
        min_feedbacks: int | None = None,
        sort_by: str = "token_id",
        sort_order: str = "asc",
    ) -> tuple[list[dict], int]:
        params: dict[str, object] = {
            "chain_id": chain_id,
            "limit": min(limit, MAX_LIMIT),
            "offset": offset,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if min_feedbacks is not None:
            params["min_feedbacks"] = min_feedbacks
        data = self._get("/agents", params)
        return list(data.get("items") or []), int(data.get("total") or 0)

    def get_agent(self, chain_id: int, token_id: str) -> dict:
        return self._get(f"/agents/{chain_id}/{token_id}", {})
