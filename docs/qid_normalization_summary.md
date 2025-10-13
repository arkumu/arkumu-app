# QID Normalization Summary

## Scope
- Updated `data/mappings/khm_labels.csv` and `data/mappings/hmt_tonband_labels.csv` so the `synonyme` property carries the raw category codes (needed for the bridge step).
- Adjusted catalogue helpers to consume Wikidata identifiers directly:
  - `ProjectURIs.CATCHPHRASE_WIKIDATA` now points to `http://arkumu.org/data/properties/wikidata-id`.
  - `TripleRelationshipService` emits QIDs for catchphrases and event locations (no label fallback).
  - `ProjectSnapshotService` now prefers QIDs when resolving category labels.
- Enhanced `derive_project_relationships` with a pre-processing pass that materialises literal project category assignments into proper category entities before applying Kreuz derivation patterns.

## Commands Run (via Docker)
```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py map_canonical_uris data/mappings/khm_labels.csv --organization khm
docker compose -f docker-compose.local.yml run --rm django python manage.py canonicalize_schema_manifest --organization khm
docker compose -f docker-compose.local.yml run --rm django python manage.py derive_project_relationships --organization khm

docker compose -f docker-compose.local.yml run --rm django python manage.py canonicalize_schema_manifest --organization hmt
docker compose -f docker-compose.local.yml run --rm django python manage.py derive_project_relationships --organization hmt

docker compose -f docker-compose.local.yml run --rm django python manage.py shell -c "from arkumu.projects.services import ProjectSnapshotService; ProjectSnapshotService().refresh_cross_institutional_snapshot()"
```

## Verification
- Keyword QIDs confirmed via `TripleRelationshipService('khm').get_catchphrases(...)`.
- Derived project→category triples now exist (`105` entity-backed links for KHM).
- Snapshot inspection: KHM projects now report category identifiers (e.g. `['Q128']`).

## Follow-Up
- HMT actors still require mapping updates so that `Akteurin_Name` populates `http://arkumu.org/data/properties/deutscher-name`.
- Institution codes for KHM/HMT remain hashed (`ff8f3b0306bebf6d`, `aa5f824e167db5e1`); aligning them with canonical organization codes will surface those archives in the catalogue filters.
