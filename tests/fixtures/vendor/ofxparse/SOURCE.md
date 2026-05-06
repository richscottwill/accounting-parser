# vendor/ofxparse

Real-world OFX (Open Financial Exchange) test fixtures copied from the `jseutter/ofxparse` Python library.

## License

MIT License — Copyright (c) 2009 Jerry Seutter. The MIT license explicitly permits redistribution with attribution.

Full license text: https://github.com/jseutter/ofxparse/blob/master/LICENSE

## Source

- **Repo**: https://github.com/jseutter/ofxparse
- **Path**: `tests/fixtures/`
- **Commit**: `master` branch (downloaded 2026-05-05)

## Attribution

These 21 files were created by Jerry Seutter and the `ofxparse` contributors as canonical OFX parser test fixtures. Preserve this SOURCE.md when distributing.

## Why these matter for accounting-parser

OFX/QFX files are how bank feeds actually arrive in real-world accounting pipelines. Our synthetic `ofx_factory` produces a clean, grammatically-correct OFX — useful but trivial. These 21 files cover the gnarly real-world cases:

| Category                     | Fixtures                                             |
| ---------------------------- | ---------------------------------------------------- |
| Checking accounts (simple)   | `bank_small.ofx`, `bank_medium.ofx`, `checking.ofx`  |
| Credit-card statements       | `anzcc.ofx`                                          |
| Savings accounts             | `fidelity-savings.ofx`                               |
| Investment accounts          | `fidelity.ofx`, `vanguard.ofx`, `tiaacref.ofx`, `td_ameritrade.ofx`, `investment_medium.ofx` |
| Retirement / 401(k)          | `investment_401k.ofx`, `vanguard401k.ofx`            |
| Multi-account aggregation    | `account_listing_aggregation.ofx`, `multiple_accounts.ofx`, `multiple_accounts2.ofx` |
| Error / signon paths         | `error_message.ofx`, `signon_fail.ofx`, `signon_success.ofx`, `signon_success_no_message.ofx` |
| OFX version 102              | `ofx-v102-empty-tags.ofx`                            |
| Vendor-specific quirks       | `suncorp.ofx` (Australian bank — exercises non-US conventions even though we reject them) |

Task 11 (Interchange parser) tests should run against all 21 files. Any parser that works on our synthetic fixture but fails on these is broken in the real world.

## Refresh protocol

ofxparse is effectively feature-complete. Pinning to the master branch at download date is fine. To refresh:

1. `git clone https://github.com/jseutter/ofxparse.git /tmp/ofxparse`
2. Compare `/tmp/ofxparse/tests/fixtures/` against `vendor/ofxparse/` — update any changed files.
3. Update the "downloaded" date above.

Preserve the MIT license text upstream even if the upstream file changes — our commitment is to the license under which we originally accepted the files.
