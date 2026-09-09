# Live Grid Operator validation — 9 September 2026

Supplementary operational evidence captured at 23:01 UTC. This does not replace the submitted version or any registered Agent Advantage experiment. It makes no human-versus-agent speed or profit claim.

Docket's persistent Grid Operator activation `act_aed21eca7ed37c9b4dc68be6` completed two autonomous buy swaps on BSC. Both successful receipts and their ERC-20 transfer logs were independently read through public BSC RPC; the exact inputs and outputs match the recorded fills.

Owner: `0xe55816904796341BF8535e25f6c8b647927fc946`. Session: `0x97319911292c36Be5e7d8f61f7EdF242e1aBcE00`.

## Funding and limits

The owner funded [0.50 USDT](https://bscscan.com/tx/0x82309fb8cb8b5ab4df6d949d1b6ffae64c30e0588ac335f3fd3507e828d59dcc) and [0.0004 BNB](https://bscscan.com/tx/0x51d1af5a2f24baded157259522b0b66e52752614f12c6085ee449a61393f8cfa). Combined owner funding gas was 0.000003774732 BNB. The activation became active at 22:49:53 UTC.

The approved trial budget was 0.50 USDT principal and at most 0.0005 BNB total gas. The session policy limits total USDT spending to 0.50 and each action to 0.25; BNB is capped at 0.0004 total and 0.00005 per service transaction, with a 0.1 gwei gas-price ceiling and 50 basis points maximum slippage. Expiry is 10 September 2026 at 22:38:45 UTC. These are software controls around a session account, not onchain policy enforcement.

Four WBNB/USDT levels were watched. The executable per-level amount was `249999999999999998` atomic USDT, two atomic units below 0.25. WBNB has no spending cap in this policy, so the session is not authorized to sell it; received WBNB remains discoverable for return on closure.

## Confirmed buys

| Level | Block | USDT input, atomic | WBNB output, atomic | Receipt |
| --- | --- | --- | --- | --- |
| 3 | 120961932 | 249999999999999998 | 346109660973625 | [First buy](https://bscscan.com/tx/0xdf023656b9d1945ce4e986169fa8e142760963f783e85f698b1e09ff5c0593ef) |
| 2 | 120962072 | 249999999999999998 | 346306343016753 | [Second buy](https://bscscan.com/tx/0xa2a9d465872826e8b62b941920d88dc34b6200c28858bb6f9ddbab0537d6cd3a) |

These are swaps triggered by watched AMM prices, not resting exchange orders. No artificial historical reference price was needed for the observed fills.

At pinned BSC block **120962569**, the session held:

- **0.000692416003990378 WBNB**;
- **4 atomic USDT**;
- **0.0003843329 BNB**.

USDT and WBNB allowances to both configured PancakeSwap V2 and V3 swap routers were zero. The two swaps cost 0.0000110453 BNB in gas. Initial BNB funding less the remaining balance gives 0.0000156671 BNB of total session gas, including approvals; together with owner funding gas, observed cost was **0.000019441832 BNB**, below the trial ceiling.

## What remains unproved

The activation was still active at capture. Return of the received WBNB, remaining USDT and BNB requires subsequent revocation or expiry and successful return receipts. This record proves funded setup and two real swaps; it does not establish profit, long-term performance or completed end-to-end closure. Other categories' funded operations require their own evidence. Original interrupted, failed and unscored experiments remain unchanged.
