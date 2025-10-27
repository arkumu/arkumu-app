# Metadata Workspace Test Plan

## Objectives
- Guarantee that manual edits created through the workspace UI persist triples exactly like the importer-generated graph, including junction entities.
- Cover the HTMX-driven suggestions, multi-select joins, and banner rendering to avoid regressions.
- Validate that data produced through the workspace can be consumed by downstream tooling (e.g., Project Snapshot) without additional transformations.
- Keep the test scope local to the workspace module(s); do **not** run the entire project test suite.

## Primary Scenarios
| ID | Dataset(s) | Focus | Expected Outcome |
|----|------------|-------|------------------|
| S1 | `Projekt` | Single-value literals | Canonical predicates used; snapshot sees identical triples. |
| S2 | `Projekt` ↔ `Ereignis` join | HTMX lookup, multi-select create/remove | Junction entities minted/removed, only one join control visible. |
| S3 | `Ereignis` ↔ `Digitales Objekt` (dup) | Hidden redundant field | Direct property suppressed when join helper exists. |
| S4 | `Ereignis` ↔ `Informationsträger` join | Nested joins | Correct target dataset/property for intermediate join. |
| S5 | `Ereignis` ↔ `Akteur`/`Rolle` | Formset + join mix | Membership rows created via helper while actor/role forms persist. |
| S6 | HTMX suggestion endpoint | Literal search debounce | Suggestion list rendered, selection clears dropdown. |
| S7 | Snapshot integration (smoke) | Manual data from S1–S5 | Snapshot output equals expected triple set. |
| S8 | Failure paths | Invalid suggestion / empty join removal | 4xx response rendered, no orphan join rows. |

## Test Types
1. **Service / unit tests**
   - `SchemaWorkspaceService.list_join_relationships` deduplicates joins.
   - `sync_join_relationship` create/update/delete behaviour and `dcterms:isPartOf`.
   - `_normalize_fk_values` remains backwards compatible.

2. **View / integration tests** (Django client + HTMX headers)
   - `entity_workspace_dataset` GET/POST round trips for S1–S5.
   - `entity_workspace_field_values` suggestions and “no results”.
   - Ensure banners/badges reflect stored joins.

3. **Snapshot smoke test**
   - Create fixtures through the workspace helpers, run the project snapshot command, and compare to an expected triple set.

4. **Negative tests**
   - Invalid join submission, missing target dataset, duplicate payloads.

## Tooling & Fixtures
- Use minimal resource factories (project, event, actor, digital object) with canonical URIs.
- Leverage `JoinRelationship` to stub join metadata where direct schema is unavailable.
- HTMX assertions via Django test client with `HTTP_HX_REQUEST`.

## Execution (Local Only)
Run the relevant suites inside Docker to keep parity with CI:

```bash
docker compose -f docker-compose.local.yml run --rm django pytest \
  arkumu/metadata/tests/services/test_schema_workspace_service_counts.py \
  arkumu/metadata/tests/views/test_entity_workspace_field_values.py

docker compose -f docker-compose.local.yml run --rm django pytest \
  arkumu/metadata/tests/services/test_entity_creation_service.py
```

Add additional targeted modules as new tests land (e.g., snapshot smoke tests) but avoid invoking the full project suite.

## Iteration Plan
1. Under test: implement missing service/view tests per scenarios above.
2. Confirm local Docker pytest run stays within targeted modules.
3. Evolve the plan as new regressions are found or additional datasets require coverage.
