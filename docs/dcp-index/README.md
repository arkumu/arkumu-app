# KHM DCP Path Index Reference

## What is this?

KHM DCP projects contain **digital cinema packages** where a single logical digital object corresponds to a folder (`*.dcp`) with multiple member files (CPL, PKL, MXF, etc.).  
The tailored OAI profile needs to expand these bundles into individual files for METS representations, without repeatedly scanning the large `_khm_paths.txt` mapping or hard‑coding absolute Rosetta paths.

The **DCP path index** provides a database‑backed, relative view of DCP bundle membership so that:

- DCP expansion is fast and deterministic.
- Paths remain stable even if the Rosetta root directory changes.
- Tailored OAI METS always sees the correct list of files for each DCP bundle.

This document explains how the index works, how to seed it, and which commands to use in development and production.

---

## Components

### Data model

Defined in `arkumu/oaipmh/models.py`:

- `OAIDcpPathIndex`
  - `org_code` – organization code (e.g. `"khm"`).
  - `bundle_key` – canonical identifier for the DCP folder, derived from the relative path up to the first `*.dcp` segment (e.g. `9999_bundle_dcp` or `sub/dir/9999_bundle_dcp`).
  - `folder_name` – last path segment of the DCP directory (e.g. `9999_bundle_dcp`), used to match `dateipfad-dcp-ordner` triples.
  - `relative_file_path` – full file path **relative** to the KHM Rosetta root (e.g. `9999_bundle_dcp/asset.mxf`).
  - `file_name` – basename within the bundle (e.g. `asset.mxf`).

Constraints/indices:

- Unique on `(org_code, relative_file_path)`.
- Indexed on `(org_code, bundle_key)` and `(org_code, folder_name)` for fast bundle lookups.

### Runtime lookup service

Implemented in `arkumu/oaipmh/services/dcp_index.py`:

- `BundleLookupResult`
  - Contains `org_code`, `folder_name`, and a tuple of `relative_file_paths`.

- `get_bundle_members(org_code: str, folder_name: str, *, folder_path: Optional[str] = None) -> BundleLookupResult`
  - Primary path:
    - Queries `OAIDcpPathIndex` for the given `org_code` and `folder_name`.
    - Uses `folder_path` (absolute, from the triple) as a hint to narrow to a specific `bundle_key` when needed.
    - Returns a de‑duplicated list of **relative** file paths for files that are direct children of the DCP folder.
  - Fallback path:
    - If no DB entries exist, loads the in‑memory `PathIndex` via `arkumu.oaipmh.path_mapping._load_index("khm")` (backed by `OAI_EXTERNAL_PATH_FILES["khm"]`, usually `data/mappings/_khm_paths.txt`).
    - Applies the legacy semantics to find direct children of the folder and converts absolute paths to relative ones using `OAI_EXTERNAL_ROSETTA_ROOTS["khm"]`.
    - Logs a note when the fallback is used so gaps in the DB index can be identified and fixed.

### DCP expansion in the builder

The base OAI project builder uses the index in `arkumu/oaipmh/oai_project.py`:

- `OAIProjectBuilder._expand_dcp_folder_if_needed(obj, institution_code)`
  - Only active for `institution_code == "khm"`.
  - Reads the `dateipfad-dcp-ordner` triple for the digital object:
    - Predicate: `http://arkumu.org/data/khm/properties/dateipfad-dcp-ordner`.
    - Extracts the **folder path** (absolute) and the **folder name** (last segment).
  - Calls:
    - `dcp_index.get_bundle_members("khm", folder_name, folder_path=folder_path)`
  - For each returned `relative_file_path`:
    - Builds an absolute Rosetta path: `abs_path = f"{OAI_EXTERNAL_ROSETTA_ROOTS['khm'].rstrip('/')}/{relative_file_path.lstrip('/')}"`.
    - Constructs a new `ProjectDigitalObject`:
      - `path` and `storage_key` set to `abs_path`.
      - Copies non‑path metadata from the original object (content type, checksum, etc.).
  - The tailored builder (`OAIProjectBuilderTailored`) uses this method to expand DCP bundles while preserving curated selection semantics.

This keeps existing behavior (which files belong to which bundle) but avoids re‑scanning `_khm_paths.txt` for every DCP expansion and makes path handling robust to future root changes.

---

## Seeding and Maintenance

### Prerequisites

Environment / settings:

- `OAI_EXTERNAL_PATH_FILES['khm']` points to the KHM path mapping file (e.g. `data/mappings/_khm_paths.txt`).
- `OAI_EXTERNAL_ROSETTA_ROOTS['khm']` is set to the current KHM Rosetta root, e.g.:
  - `/rosetta/khm/sandbox/input/arkumu/daten`

The seeding command reads **absolute** paths from `_khm_paths.txt` and stores **relative** paths in `OAIDcpPathIndex`.

### Seeding command

Management command: `seed_khm_dcp_index`, defined in `arkumu/oaipmh/management/commands/seed_khm_dcp_index.py`.

Behavior:

- Loads the KHM `PathIndex` via `path_mapping._load_index("khm")`.
- For each absolute path under the KHM Rosetta root:
  - Computes `rel_path` (relative to the root).
  - Derives:
    - `bundle_key`: segments up to the first `*.dcp` component.
    - `folder_name`: the `*.dcp` component itself.
    - `relative_file_path`: full `rel_path`.
    - `file_name`: basename.
  - Populates or updates `OAIDcpPathIndex` for `(org_code="khm", relative_file_path)`.

#### Usage (via Docker)

From the repository root:

```bash
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py seed_khm_dcp_index --reset
```

Flags:

- `--reset` – clears existing `OAIDcpPathIndex` rows for `org_code="khm"` before seeding.

This command should be run:

- After significant changes to `_khm_paths.txt` or the underlying KHM Rosetta directory.
- After changing `OAI_EXTERNAL_ROSETTA_ROOTS['khm']` to a new root.

---

## Deployment Checklist

When deploying changes that affect KHM DCP handling:

1. **Configuration**
   - Verify:
     - `OAI_EXTERNAL_PATH_FILES['khm']` points to the correct `_khm_paths.txt`.
     - `OAI_EXTERNAL_ROSETTA_ROOTS['khm']` matches the active Rosetta path root.
2. **Migrations**
   - Apply migrations that create `OAIDcpPathIndex`.
3. **Seeding**
   - Run:
     - `docker compose -f docker-compose.local.yml run --rm django python manage.py seed_khm_dcp_index --reset`
   - Confirm log output:
     - Number of created/updated rows.
     - Warnings for paths outside the configured root (if any).
4. **Verification (tests)**
   - Run the targeted test suite:
     ```bash
     docker compose -f docker-compose.local.yml run --rm django \
       pytest tests/test_oai_tailored_endpoint.py \
              arkumu/oaipmh/tests/unit/test_dcp_index.py \
              arkumu/oaipmh/tests/unit/test_oai_project_tailored.py
     ```
   - This validates:
     - The index service (DB + fallback behavior).
     - Tailored builder DCP expansion at unit level.
     - Tailored `/oai/tailored/` METS responses for a synthetic KHM DCP project using the index.

---

## Operational Notes

- **Fallback behavior**
  - If `OAIDcpPathIndex` has no matching rows for a folder name, the system falls back to the in‑memory path index (backed by `_khm_paths.txt`).
  - This ensures no loss of coverage during rollout, but you should treat fallback usage as a signal to re‑seed or correct configuration.

- **Relative vs absolute paths**
  - All DB entries store **relative** paths.
  - Only settings (`OAI_EXTERNAL_ROSETTA_ROOTS['khm']`) determine the active root.
  - Changing the root should not require rewriting the index; re‑seeding from an updated `_khm_paths.txt` is sufficient when the underlying paths change.

- **Scope**
  - The DCP path index is currently used for:
    - KHM DCP expansion in the canonical and tailored OAI builders.
  - Other institutions (HMT, FUK, etc.) continue to use their existing path‑resolution strategies and are not affected by this index.

