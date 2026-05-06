# tests

Cross-cutting test artifacts.

- `fixtures/` — synthetic accounting documents. Populated by Task 2.
- `fixtures/factories/` — Python factories that generate fixtures.
- `fixtures/vendor/` — vendor-published sample files (CCH, AdvanceFlow templates). Populated by Task 2.
- `integration/` — cross-service integration tests that bring up docker-compose and exercise the full stack.
- `playwright/` — end-to-end Playwright scenarios. Task 26 is the flagship 11-step ex-RSM scenario.

Backend unit tests and Hypothesis property tests live alongside the code in `backend/tests/`.
