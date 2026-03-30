# Data Sources

**Status:** 🔴 NOT YET DRAFTED

## Open Decision

What is the authoritative data source for monster stat blocks, spells, and rules text?

| Option | Pros | Cons |
|---|---|---|
| SRD only | Free, no API dependency | Incomplete — missing many monsters and spells |
| D&D Beyond API | Complete | Rate limits, auth complexity, ToS considerations |
| Custom BigQuery table | Full control, integrates with Arcane Analytics infra | Significant manual data entry |
| Open5e API | Free, comprehensive SRD+ | Third-party dependency |

**Decision needed before engine data layer is built.**
