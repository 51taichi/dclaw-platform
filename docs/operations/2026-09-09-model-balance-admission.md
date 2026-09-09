# Model calls: positive-balance admission

Model calls no longer freeze the maximum token quote. Ordinary wallets must have a positive balance and an eligible unexpired credit; wallets with the existing overdraft permission retain that exception. Quote records remain for price snapshots, but their amount is not an admission threshold or an actual-charge ceiling. Existing promotional-credit eligibility is preserved.

New calls use zero-credit ledger bookkeeping entries for idempotent settlement; no credits are held. Actual supplier usage settles after the call, even if it exceeds the remaining balance. A subsequent ordinary-wallet call is blocked at a non-positive balance. Unknown usage remains reconcilable without holding funds. Legacy reserved calls continue through their original settlement path.

Scope: shared model-call meter used by client and OpenAPI contexts. This does not change separate fixed-price non-model purchase flows. No database migration or historical ledger rewriting. Not deployed automatically.

Validation: positive balance below quote, actual cost above balance and quote, repeated settlement, subsequent negative-balance blocking, existing unlimited-wallet behavior, reconciliation, legacy settlement, and billing repository regression coverage.

Commit validation: 304 billing/repository unit tests and 56 console/OpenAPI/recovery/background-channel/expert-team integration tests passed. Interruption tests explicitly simulate balance exhaustion before the next call instead of relying on unknown usage freezing funds. PostgreSQL-specific integration tests were not run in this check.

Review corrections: eligibility-aware admission scans past restricted leading lots; new actual settlements use the held capability/tier to avoid consuming restricted promotional credits. Regression verifies 10 ineligible promotional credits plus 1 purchased credit: admission succeeds, a 2-credit actual charge preserves promotional credits, and the next call is rejected for lack of eligible funds.
