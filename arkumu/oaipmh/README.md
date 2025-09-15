# Arkumu OAI‑PMH Provider

Goal: Build a robust, OAI‑PMH 2.0 compliant, highly performant provider integrated with Arkumu’s metadata graph (Resource + Triple) and aligned with harvesting best‑practices used by large aggregators (e.g., DPLA, Europeana, OpenAIRE).

This document is the implementation plan and service breakdown for the `arkumu.oaipmh` app.


## Scope and Non‑Goals

- Scope: Provider only (verbs: Identify, ListMetadataFormats, ListSets, ListIdentifiers, ListRecords, GetRecord). GET requests first; POST parity is optional.
- Non‑Goals (now): OAI‑PMH “Aggregator” role, OAI‑ORE serialization, bulk internal mapping editor. These can be future work.


## High‑Level Architecture

- HTTP layer: one baseURL endpoint, e.g. `/oai/` handling all verbs via query params.
- Repository core: a thin orchestrator that validates verbs/params, dispatches to verb services, and assembles OAI‑PMH envelopes.
- Metadata crosswalks: pluggable mappings from graph data to OAI metadata formats (start with `oai_dc`; optionally add MODS, MARCXML, DataCite).
- Storage/query: read‑optimized queries against `Resource`/`Triple` for public, harvestable records with correct datestamps and sets.
- Tokens and flow control: stateless HMAC‑signed resumption tokens with TTL; support 503 Retry‑After for load shedding.
- Validation: schema‑conformant XML, correct error codes, UTC datestamps with second‑level granularity, and granular tests per verb.


## Core Decisions (Best Practices)

- Protocol version: 2.0
- Granularity: seconds (`YYYY-MM-DDThh:mm:ssZ`).
- Encoding: UTF‑8, normalized NFC for literals.
- Deleted records policy: Persistent with tombstones (recommended) so harvesters can reconcile deletes.
- Required format: Always provide `oai_dc` (Dublin Core simple via `oai_dc:dc`).
- Caching: ETag/Last‑Modified where feasible; paginate with deterministic ordering.
- Flow control: When under pressure, respond 503 with `Retry-After` instead of hard failures.
- Schema compliance: ship XSDs in repo or pin URLs; validate in CI against OAI‑PMH and `oai_dc` schemas.


## Integration With Arkumu Metadata

- Records: Treat a “record” as a top‑level subject `Resource` that is publicly accessible (`resource.public_access_level == public` AND `is_public_approved == True`).
- Datestamp: Use `Resource.updated_at` (UTC). Optionally use `public_approved_at` as the minimum availability bound; choose the max of the two to avoid exposing pre‑approval changes.
- Identifier: Mint an OAI identifier deterministically from the Arkumu stable ID/URI. Examples:
  - `oai:{REPOSITORY_IDENTIFIER}:resource/{uuid}` (preferred, stable) or
  - `oai:{REPOSITORY_IDENTIFIER}:{normalized_uri_hash}` for URI resources.
- Deleted records: Introduce a small tombstone log that stores OAI identifier + deletion datestamp. For soft‑deleted resources or removals of public approval, emit `status="deleted"` in headers.
- Metadata mapping via Triples: Crosswalk to Dublin Core using configured predicate URIs (e.g., `dcterms:title`, `dcterms:creator`, …). Keep mapping configurable and testable.
- Sets: Provide stable setSpecs derived from organization and optional curated groupings from Triples (e.g., collection, project). Examples:
  - `org:{organization_code}`
  - `type:{class_curie}` or `coll:{collection_slug}` depending on your graph.


## Services (Modules to implement)

- Repository services
  - RepositoryInfoService
    - Returns Identify fields: `repositoryName`, `baseURL`, `protocolVersion`, `adminEmail`, `earliestDatestamp`, `deletedRecord`, `granularity`, `compression`.
    - Emits `<description>` with `oai-identifier` declaration (scheme, repositoryIdentifier, delimiter, sampleIdentifier) and optional branding block.
  - VerbRouter
    - Validates `verb` and arguments; maps to specific verb service; assembles OAI‑PMH envelope and error codes.

- Query and model services
  - RecordQueryService
    - Yields harvestable records with filters `from`, `until`, `set`, `metadataPrefix`.
    - Applies public visibility filter using `Resource.is_publicly_accessible` and organization scoping when serving multi‑tenant endpoints.
    - Deterministic ordering by `updated_at` then stable `id` for pagination.
  - SetService
    - Defines repository sets. Seed: `org:{code}` from `Resource.organization`. Optional: sets from Triples (collection, subject taxonomy), with stable setSpec strings and human‑readable names.
  - IdentifierService
    - Deterministic OAI identifier minting/parsing; reversible mapping between Arkumu Resource and OAI identifier.
  - DatestampService
    - UTC conversion, granularity enforcement, earliestDatestamp computation across harvestable records (or tombstones).
  - TombstoneService
    - Persisted deleted records with `identifier`, `datestamp`, `extra` (reason). Supplies headers with `status="deleted"`.

- Resumption tokens and pagination
  - ResumptionTokenService
    - Stateless, HMAC‑signed JSON payload: `{ from, until, set, metadataPrefix, cursor, pageSize, issuedAt }`. TTL configurable (e.g., 24h). Include `completeListSize` when cheap; otherwise omit gracefully.

- Metadata crosswalks
  - MetadataFormatRegistry
    - Registry of formats `{ metadataPrefix, schemaURL, metadataNamespace, serializer }`. Always register `oai_dc`.
  - DublinCoreSerializer (oai_dc)
    - Maps Resources/Triples to `oai_dc:dc` using configurable predicate URI map.
    - Handles language tags, repeats, and basic value normalization.
  - Additional formats (optional): MODS, MARCXML, DataCite. Keep in modular serializers.

- XML composition
  - XMLBuilder
    - Produces canonical OAI‑PMH envelopes and verb payloads with correct namespaces and schemaLocation.
    - Applies pretty printing; escapes values; ensures UTF‑8 output.

- HTTP and runtime concerns
  - ThrottleAndFlowControl
    - 503 with `Retry-After` on overload; adaptive page sizes; per‑client rate limits (IP‑based).
  - CachingService
    - Cache Identify/ListMetadataFormats/ListSets responses; cache pages of ListIdentifiers/ListRecords for hot windows.
  - LoggingAndMetrics
    - Per‑verb logs: params, counts, duration, token usage, errors. Emit structured logs for ops.

- Validation and testing
  - XSDValidation
    - Validate OAI envelopes and `oai_dc` outputs (either using local XSDs or `xmllint` in CI). Unit tests per verb and error path.


## Data Model Notes (Resource + Triple)

- Use `Resource` as the record backbone.
  - Public filter: `public_access_level == public` AND `is_public_approved is True`.
  - Datestamp: `max(updated_at, public_approved_at or created_at)` in UTC.
  - Header `<identifier>` renders from `IdentifierService` mapping to Arkumu ID.
  - Header `<setSpec>`: at least one `org:{code}`; add others via SetService.
- Use `Triple` to derive metadata elements.
  - Example mapping (configurable):
    - `dcterms:title` -> dc:title
    - `dcterms:creator` -> dc:creator
    - `dcterms:subject` -> dc:subject
    - `dcterms:description` -> dc:description
    - `dcterms:publisher` -> dc:publisher
    - `dcterms:contributor` -> dc:contributor
    - `dcterms:date|issued|created` -> dc:date
    - `dcterms:type` -> dc:type
    - `dcterms:format` -> dc:format
    - `dcterms:identifier` or resource URI -> dc:identifier
    - `dcterms:source` -> dc:source
    - `dcterms:language` -> dc:language
    - `dcterms:relation` -> dc:relation
    - `dcterms:coverage` -> dc:coverage
    - `dcterms:rights` -> dc:rights
  - Keep multi‑valued; serialize each value as a separate DC element in order.


## Endpoints and Verbs

- BaseURL: `/oai/` (configure in `config/urls.py`).
- Supported verbs: `Identify`, `ListMetadataFormats`, `ListSets`, `ListIdentifiers`, `ListRecords`, `GetRecord`.
- Arguments: `verb`, `identifier`, `metadataPrefix`, `from`, `until`, `set`, `resumptionToken`.
- Errors to implement (spec): `badVerb`, `badArgument`, `cannotDisseminateFormat`, `idDoesNotExist`, `noRecordsMatch`, `noMetadataFormats`, `noSetHierarchy`.


## XML and Schema Details

- Namespaces:
  - `oai` `http://www.openarchives.org/OAI/2.0/`
  - `oai_dc` `http://www.openarchives.org/OAI/2.0/oai_dc/`
  - `dc` `http://purl.org/dc/elements/1.1/`
  - `xsi` `http://www.w3.org/2001/XMLSchema-instance`
- schemaLocation examples:
  - Envelope: `http://www.openarchives.org/OAI/2.0/ http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd`
  - oai_dc: `http://www.openarchives.org/OAI/2.0/oai_dc/ http://www.openarchives.org/OAI/2.0/oai_dc.xsd`
- Datestamps: UTC with Z; enforce `from`/`until` validity and range; treat open intervals properly.


## Performance and Scale

- Indexes: rely on existing `Resource` indexes and add a covering index for `(public_access_level, is_public_approved, updated_at)` if needed for harvest scans.
- Page size: start at 100–500 records; configurable; ensure deterministic pagination and token replay safety.
- Precomputation (optional, Phase 3): materialize a “harvestable view” table with flattened DC fields for hot‑path scans.


## Security and Privacy

- Only expose public and approved records. Never leak restricted/private.
- Multi‑tenant: either one global baseURL with org set filtering, or one baseURL per org (via routing). Keep both options in config.
- Input validation: strict verb/argument checks and safe XML escaping.


## Configuration (settings)

```
OAI_BASEURL = "https://example.org/oai/"
OAI_REPOSITORY_NAME = "Arkumu Repository"
OAI_ADMIN_EMAILS = ["admin@example.org"]
OAI_REPOSITORY_IDENTIFIER = "example.org"  # for oai:identifier scheme
OAI_PAGE_SIZE = 200
OAI_TOKEN_TTL_SECONDS = 86400
OAI_ENABLE_SETS = True
OAI_DELETED_RECORD_POLICY = "persistent"  # or "transient"
OAI_METADATA_FORMATS = {
  "oai_dc": {
    "namespace": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "schema": "http://www.openarchives.org/OAI/2.0/oai_dc.xsd"
  }
}
# Dublin Core crosswalk mapping from predicate URIs to DC terms
OAI_DCTERMS_MAPPING = {
  "http://purl.org/dc/terms/title": "title",
  "http://purl.org/dc/terms/creator": "creator",
  # ... add others
}
```


## File/Module Layout (proposed)

```
arkumu/oaipmh/
  ├─ apps.py
  ├─ views.py                # Thin HTTP layer, delegates to repository
  ├─ urls.py                 # baseURL routing
  ├─ repository.py           # VerbRouter + OAI envelope composition
  ├─ xml.py                  # XMLBuilder
  ├─ formats/
  │    ├─ registry.py       # MetadataFormatRegistry
  │    ├─ dublin_core.py    # DublinCoreSerializer (oai_dc)
  ├─ services/
  │    ├─ identify.py       # RepositoryInfoService
  │    ├─ records.py        # RecordQueryService, DatestampService
  │    ├─ sets.py           # SetService
  │    ├─ identifiers.py    # IdentifierService
  │    ├─ tokens.py         # ResumptionTokenService
  │    ├─ tombstones.py     # TombstoneService
  │    ├─ caching.py        # CachingService
  │    └─ throttle.py       # ThrottleAndFlowControl
  ├─ tests/
  │    ├─ test_identify.py
  │    ├─ test_list_metadata_formats.py
  │    ├─ test_list_sets.py
  │    ├─ test_list_identifiers.py
  │    ├─ test_list_records.py
  │    └─ test_get_record.py
  └─ README.md
```


## Phased Implementation Plan

- Phase 1: Minimal compliance (MVP)
  - Add `urls.py`, wire `/oai/` in `config/urls.py`.
  - Implement Identify, ListMetadataFormats, GetRecord.
  - Implement `oai_dc` crosswalk (Triples -> DC) and XML envelope builder.
  - Deterministic identifiers and UTC datestamps.

- Phase 2: Harvest at scale
  - Implement ListIdentifiers, ListRecords with resumption tokens.
  - Add SetService with `org:{code}` sets; return `noSetHierarchy` when disabled.
  - Add basic caching and configurable page size.

- Phase 3: Production hardening
  - Add 503 Retry‑After flow control; rate limiting; structured logging.
  - TombstoneService with persistent delete policy; CI XSD validation.
  - Additional metadata formats (MODS, MARCXML, DataCite) as needed.

- Phase 4: Performance & multi‑tenant options
  - Optional materialized harvestable view; ETag/Last‑Modified on “hot” pages.
  - Support per‑organization baseURLs or query scoping.


## Open Questions / Choices to Confirm

- Identifier scheme: confirm repositoryIdentifier (domain) and desired OAI identifier form.
- Deleted record policy: persistent with tombstones vs transient (no deletes advertised).
- Sets design: baseline `org:{code}` only vs additional curated sets from Triples.
- Additional formats priority: which crosswalks to ship first beyond `oai_dc`.


## Next Steps

- Confirm the configuration choices above.
- I’ll scaffold `urls.py`, repository services, and the `oai_dc` crosswalk.
- Wire route in `config/urls.py` and add verb tests for MVP.

---

References (domain best‑practice distilled): OAI‑PMH v2.0 spec, large‑scale provider implementations’ practices (Identify `<description>` with `oai-identifier`, persistent deletes, 503 for flow control, stateless signed resumption tokens, and DC crosswalks using graph mappings).

