## Media links sync: what writes to which tables

- **Seed** (`media_links_sync` default/`--full`): writes curated project→digital links to `OAIProjectMediaLink`.
  - KHM/HMT: uses materialized project→digital triples (canonical/URI `digitales-objekt`); if none exist for a project, it logs a warning and skips (no assembler fallback).
  - DET/RSH/FUK: assembles each project via the tailored assembler to derive curated digital objects.
  - Marks `OAIMediaSyncState.last_seed_at`.
  - Marks stale links when no candidates are found.

- **Publication sync** (always after seed unless `--approvals-only`): writes OAI approvals to `OAIProjectPublication`.
  - Auto-approves when harvestable digital objects are found.
  - Marks `OAIMediaSyncState.last_publication_sync_at`.

- **Approvals only** (`--approvals-only`): skips `OAIProjectMediaLink`, only updates `OAIProjectPublication`.

- **Queueing** (`--queue`): runs the same seed+publication flow in Huey; no logic change, just background execution.

- **Scope**:
  - Projects are filtered by org and must match both project type (`OAI_PROJECT_TYPE_URIS`) **and** a project link predicate (`OAI_PROJECT_LINK_PREDICATES`), unless the org is in `OAI_PROJECT_LINK_SCOPE_DISABLED_ORGS`.
  - This reduces KHM scope to ~3.2k true projects (type + link) instead of ~15.9k link-only resources.

- **Progress logging**:
  - Start: candidate count and full/incremental flag.
  - First project processed.
  - Every ~5s: processed/total, created/refreshed/stale/skipped, rate, ETA.
  - Completion summary.
