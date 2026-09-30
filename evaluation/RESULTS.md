# Evaluation Results — Automated Run

All results below were produced by driving the running Django application
(Playwright + direct HTTP) on **24 September 2026**. Everything here is
`[MEASURED]`. Nothing is assumed.

## Platform

| Field | Value |
|---|---|
| CPU | AMD Ryzen 5 5600H, 6 cores / 12 threads, max 4.28 GHz |
| RAM | 11 GiB |
| OS | Ubuntu 24.04.4 LTS, kernel 6.8.0-139-generic |
| Python | 3.12.3 |
| Django | 6.1.1 (`manage.py check` → 0 issues) |
| pycryptodome | 3.23.0 · pandas 3.0.6 |
| Server | `manage.py runserver 127.0.0.1:8000 --noreload`, single process |
| Database | SQLite `db.sqlite3` |
| Browser | Chromium via Playwright, viewport 1280×900 |
| Tester | 1 operator (automated), 1 device, 1 browser, localhost only — **no tunnel used in this run** |

> The project targets Django 2.2 (per `settings.py` header) but runs unmodified
> on Django 6.1.1. Worth one sentence in the paper.

## A.1 Scenario results

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 1 | Valid Aadhaar in dataset | **Pass** — details rendered from Excel | `04_auth_success.png` |
| 2 | Aadhaar not in dataset (`999999999999`) | **Pass** — "Invalid Aadhar, Please Enter Correct Aadhar Number!" | `03` |
| 3 | Wrong length (`12345`) | **Pass** — "Please enter a valid 12-digit Aadhar number." (client-side) | `02` |
| 4 | Phone OTP requested + correct entry | **Pass** — OTP `775562` to console, verified | `06`, `10` |
| 5 | Phone OTP wrong | **Pass** — "Invalid OTP" | `08` |
| 6 | Phone OTP expired | **Pass** — "OTP expired. Please request a new OTP."; stored OTP cleared | scripted |
| 7 | Email OTP before phone verified | **Pass, server-side** — see §Gating | `11` |
| 8 | Email OTP correct → private key email | **Pass** — real email delivered via Gmail SMTP | `14` |
| 9 | Email OTP wrong | **Pass** — "Invalid OTP" | scripted |
| 10 | Vote with correct private key | **Pass** — "Vote verified and signed successfully."; `Vote` + `VoteBackup` written, `vote_done=1` | `17`, `19` |
| 11 | Vote with malformed key | **Pass** — "Key error: Incorrect padding" | scripted |
| 11b | Vote with **valid but mismatched** key | **Pass** — "Key error: The signature is not authentic" | scripted |
| 12 | Second vote, same Aadhaar | **Pass** — "You have already casted your vote." | `05` |
| 13 | Mining after N votes | **Pass** — see §Mining | `20`–`23` |
| 14 | DB row edited, then verify | **Pass** — tampered, alert fired | `26`, `27` |
| 15 | Sync Now | **Pass** — restored, block untouched | `29` |

## Gating — server-side enforcement confirmed

Each endpoint was called **directly by `fetch()`, bypassing the UI**, while the
voter was unverified. All three refused:

| Endpoint | Response |
|---|---|
| `GET /send-otp/` | `{"success": false, "error": "Phone verification required before email verification."}` |
| `GET /get-parties/` | `{"error": "Phone number verification required before voting.", "phone_verification_required": true}` |
| `POST /create-vote/` | `{"success": false, "status": "Phone number verification required before voting."}` |

This is a genuine positive result: the ordering is not client-side only.

## Tamper detection matrix — all runs against block #1

| Attack on stored data | Detected? |
|---|---|
| baseline, untampered | No (correct — no false positive) |
| 1. change `vote_party_id` | **Yes** |
| 2. change `timestamp` | **Yes** |
| 3. change `uuid` | **Yes** |
| 4. delete the `Vote` row | **Yes** |
| 5. insert a spurious `Vote` into the block | **Yes** |
| 6. change `Vote` **and** `VoteBackup` identically | **Yes** (detected) |
| 7. tamper, then `/reset-blockchain/` + `/start-mining/` | **NO — evasion succeeds** |
| 8. modify `Block.merkle_hash` directly | **Yes** |

### Recovery outcomes

| Case | Recovery via `/sync-block/` |
|---|---|
| 1 (vote only) | **Restored.** `congress`→`bjp`; block `merkle_hash`, `this_hash`, `nonce` all unchanged; re-verify clean |
| 6 (vote + backup corrupted) | **Fails.** Sync returns `success: true` but writes back the corrupted value (`cpi`); block still flagged tampered |

### Finding 7 — the significant one

After tampering with both `Vote` and `VoteBackup`, calling the
**unauthenticated** `/reset-blockchain/` followed by `/start-mining/` re-seals
the tampered vote into a fresh block. Verification then reports **clean**:

```
before re-mine : {'1': True}    (tampered)
after re-mine  : {'1': False}   (verifies clean)
stored vote    : 505229928339 | congress    <- tampered value, now permanent
new block      : merkle 3bc7fca8…  nonce 3196
```

At difficulty `000` re-mining costs ~0.1 s per block, so this is not a
theoretical attack. State it plainly as a limitation: integrity holds only
against an attacker who cannot reach the reset/mine endpoints, and those
endpoints require no authentication.

## Mining measurements — in-application

Measured through `/start-mining/`; `time_taken` is the value the application
itself reports. `TRANSACTIONS_PER_BLOCK = 1`, `PUZZLE = '000'`.

| Votes | Blocks | `time_taken` (s) | Wall clock (s) | Mean nonce | Per block (s) |
|---|---|---|---|---|---|
| 5 | 5 | 0.366685 | 0.3806 | 2434.6 | 0.0733 |
| 10 | 10 | 1.127612 | 1.1410 | 4397.5 | 0.1128 |
| 20 | 20 | 2.135322 | 2.1504 | 4055.5 | 0.1068 |
| 40 | 40 | 5.379745 | 5.3968 | 5476.4 | 0.1345 |

Single real vote (scenario 13): block #1, nonce **8386**,
hash `000d3145…`, prev_hash `0×64`.

**Django/ORM/SQLite overhead:** the pure-hash replica cost ~0.0138 s per block
at the same difficulty; in-application cost is ~0.073–0.135 s, so framework and
database overhead accounts for roughly **80–90 % of mining wall time**. Mining
cost here is dominated by persistence, not by proof of work. Good result to
report — it contradicts the intuition that PoW dominates.

## Additional findings

1. **No OTP rate limiting.** 10 consecutive wrong phone-OTP submissions all
   returned "Invalid OTP" with no lockout, no delay, and the OTP still valid
   afterwards. Confirms `PAPER_CONTEXT.md` §8.6 by measurement.
2. **Stale sessions reproduce the OTP bug.** Six concurrent sessions existed for
   one voter, each holding a different email OTP in plaintext. The September log
   entry (`245412`) was still live in the session table. Only the newest OTP
   verifies; the rest produce "Invalid OTP" against a correct-looking code.
3. **E.164 normalisation is lost on re-authentication.** `send-phone-otp`
   rewrites `phone_number` to `+918329761217`, but re-authenticating re-syncs the
   voter from the Excel sheet and overwrites it back to `8329761217`. The tamper
   alert was therefore addressed to the un-normalised number.
4. **Tamper alert fires once.** Two consecutive verifications of the same
   tampered block produced exactly one console SMS; `tamper_alert_sent` worked.
5. **Email delivery works.** The hard-coded Gmail credentials are live — two real
   emails were sent during this run (OTP, then private key).
6. **UI defect:** the email "Send OTP" control cannot be clicked normally —
   `<div class="associated-email-id">` intercepts pointer events. Handlers had to
   be triggered programmatically. A real user may hit this.
7. **UI defect:** a stray `'` renders after "Tampered / Sync Now" in the chain
   list (unbalanced quote in the `blockchain.js` template literal).
8. **Model drift:** Django reports unapplied model changes for `home`; migrations
   are behind `models.py`. No migration was generated (no code touched).

## Method deviations — disclose these if the data is used

- **Private key injection.** `verify_otp` emails the private key and never stores
  it, so automation could not read it. A P-256 keypair was generated externally
  and its public key written into the active sessions and `Voters.public_key`;
  the matching private key was then pasted into the normal vote flow. The
  *cryptographic path exercised is unchanged* — `verify_vote()` ran normally, and
  the mismatched-key test (11b) confirms it rejects a non-matching key. Only the
  key-delivery channel was bypassed.
- **Synthetic votes.** The 5/10/20/40-vote mining runs used `Vote`/`VoteBackup`
  rows inserted directly, not cast through the UI. Mining code is unaffected by
  how rows arrive.
- **Single operator, localhost.** No multi-user, multi-device or tunnel testing
  was performed in this run. If the paper needs that, it still has to be done by
  hand.
- The database was snapshotted before the tamper matrix and restored after each
  attack; final state matches the post-scenario state.

## Artefacts

- `evaluation/screenshots/` — 20 PNGs, 1280×900, Chromium.
- `evaluation/logs/mock_sms_console.log` — mock SMS console output (OTP + tamper alert).

**Screenshots are unmasked.** They contain a real name, Aadhaar-format number,
email address, phone number and photo. Mask before any submission — see §E.3 of
`EVALUATION_DATA_REQUEST.md`.
