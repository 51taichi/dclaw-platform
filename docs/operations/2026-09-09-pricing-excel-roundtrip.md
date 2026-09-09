# Pricing Excel roundtrip correction

The exported draft could contain duplicate specifications when older trusted cost snapshots omitted `unit_size` and newer snapshots explicitly stored one million. Fixed derived prices also prevented changing costs or multipliers without manually updating dependent columns and internal provenance.

The shared specification normalizer separates unit size from conditions, preserves explicit sizes and selects the newest equivalent trusted snapshot. Imports recalculate sale prices and credits, mark cost changes as manual pending confirmation, and continue rejecting changed specifications. Editable columns are highlighted and explained in the workbook. Per-dimension multipliers persist in model policy settings, and confirmed costs take precedence over collected candidates on reexport.

Validation: 142 pricing unit/integration tests pass. A read-only copy of local inputs contained 22 models, 82 historical cost records and 39 equivalent-specification groups. In an isolated SQLite database, the 45-row export completed import, confirmation, publication and reexport/reimport; 41 priced dimensions were included and two models with four missing-cost rows were explicitly excluded. No active catalog or account balance was changed by these checks.

Local runtime: overlay image `dclaw-local:pricing-roundtrip-20260909` built on the currently installed `dclaw-local:s6ff108447-c8db8c83dd`, applying only pricing changes to preserve other installed fixes. This update does not publish a new live price catalog. Reexport the workbook to obtain the updated instructions and editable-column hints.
