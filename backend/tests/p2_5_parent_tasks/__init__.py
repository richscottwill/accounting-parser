"""P2.5 parent-task coverage tests.

Verifies that the 5 absorbed parent tasks ship their orchestration
surface:

- Task 19: UltraTax + AdvanceFlow exporter registered.
- Task 22: individual_1040_prep template registered.
- Task 23: PBC Request domain types + lifecycle constants.
- Task 26: year_end_tax_prep template registered with correct step
  ordering + two pause points (preparer + reviewer).
- Task 28: Lacerte + QuickBooks IIF exporters registered.
"""
