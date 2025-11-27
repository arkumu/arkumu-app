# OAI project scope & direct-link materialization

This documents how projects enter the OAI media-link / publication pipeline and how to create the direct project→digital triples when needed.

## Scope rules (project_queryset_for_org)
- Projects must be `Resource` entities for the org.
- If `OAI_PROJECT_LINK_PREDICATES` is set (default: canonical `projekt` predicate), the project must have an outgoing triple with that predicate **unless** its org code is in `PROJECT_LINK_PREDICATE_BYPASS_ORGS`.
- If `OAI_PROJECT_TYPE_URIS` is set, a matching `rdf:type` also admits the project.
- Bypass orgs (default: `fuk`, `det`, `rsh`) skip the predicate gate because their media links are derived via events; if no other scope clause applies, all entity resources for the org are considered in scope.
- KHM/HMT are **not** bypassed; they use direct project→digital triples and must have the canonical predicate to be in scope.

## Creating direct project→digital triples
Run the materializer per org to mint derived triples with the canonical predicate:

```bash
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py materialize_project_digital_triples -o <org> \
  --log-interval 50 --batch-size 10000
```

Use `--dry-run` to inspect first. Run without `--dry-run` to persist. This should be done for orgs expected to satisfy the predicate gate (e.g., `khm`, `hmt`; also possible for `fuk/det/rsh` if you want them to use direct links rather than the bypass).

## End-to-end workflow (per org)
1) Ensure scope: either have the canonical predicate (or configured type), or be in the bypass list.
2) Seed curated links: `_run_media_link_seed(org, force_full_refresh=True)` or “Force full sync” in the dashboard to populate `OAIProjectMediaLink`.
3) Sync publication: `_sync_oai_publication_for_org(org, force_full_refresh=True)` (also part of “Force full sync”) to create/update `OAIProjectPublication` and auto-approve based on org rules.

After the initial full run, incremental “Sync curated data”/“Sync OAI approvals” use watermarks to process only changes.
