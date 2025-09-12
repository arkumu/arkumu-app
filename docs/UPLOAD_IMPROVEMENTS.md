# Upload Architecture: Findings and Recommendations

This document reviews the current upload implementation in this repository and proposes concrete improvements for performance, resilience, and simplicity. It focuses on direct-to-object-storage uploads via presigned URLs and S3 multipart, and clarifies where Huey should fit in.

## Current State (observed)

- Storage backend
  - `django-storages` with S3/S3-compatible backends, AES256 SSE when not MinIO.
  - `BaseStorageService` creates two clients: a main `s3_client` and a `presigned_client` (optionally using a browser-friendly endpoint). It also configures CORS with `ExposeHeaders: ETag`.
- Upload flows (multiple coexist):
  - Streaming server-to-S3 upload: `storage/views/streaming_upload_views.py` using `upload_fileobj_encrypted`.
  - Server-proxy S3 multipart: `storage/views/s3_multipart_upload_views.py` (`create_multipart_upload`, then server receives each chunk and calls `upload_part`).
  - Direct-to-S3 via presigned URLs (recommended path):
    - Single PUT: `UploadService.generate_presigned_upload_url()` → browser PUTs directly.
    - Multipart: `PresignedURLService.initiate_multipart_upload()` + `generate_multipart_urls()` → browser PUTs each part directly to S3, server completes (`complete_multipart_upload`). Template: `storage/templates/upload/multipart_form.html`.
  - Batch presigned generation: `storage/views/upload_views.py::batch_presigned_urls` creates an `AsyncUploadSession` and one `AsyncUploadFile` per single-part file.
- Client JS
  - `static/js/src/s3/s3-multipart-upload.js` uses server-proxy multipart endpoints at `/storage/upload/multipart/*`.
  - `static/js/src/s3/s3-client.js` references non-existent endpoints (`/storage/multipart/*`); likely legacy/out of sync.
- Huey
  - Configured Redis-backed Huey with 4 workers (`config/settings/base.py::HUEY`). `immediate` mirrors `DEBUG`.
  - Used for: chunk assembly of old resumable flow, verifying uploaded files exist in S3, and post-upload processing. Key tasks: `storage/tasks.py::verify_and_process_upload`, `cleanup_old_upload_sessions`, etc.
- Settings related to uploads (`config/settings/base.py`)
  - `MULTIPART_UPLOAD_SETTINGS` with thresholds (multipart at 5MB, resumable at 50MB), chunk sizes (8MB), concurrency (max_concurrency 6), and retries/timeouts.
  - Development overrides allow large request sizes for server-handled uploads.

## Pain Points / Risks

- Two multipart implementations
  - Server-proxy multipart (Django receives every chunk) competes with direct browser→S3 multipart. The server-proxy path adds bandwidth and CPU load and becomes a bottleneck under latency or large files.
- Endpoint mismatch in client JS
  - `s3-client.js` points to `/storage/multipart/*` which do not exist in `storage/urls.py`. This can break flows or cause confusion.
- Inconsistent chunk-size thresholds
  - Settings note 8MB; `calculate_multipart_parts` defaults to 10MB; JS handler uses 5MB. This fragmentation complicates tuning and predictability.
- Limited resumability for direct multipart
  - There is no persisted tracking of `upload_id`/completed parts for presigned multipart uploads. A browser refresh or transient network error mid-transfer forces a full restart.
- Limited client-side retry/backoff
  - JS presigned uploads do not implement structured retries with exponential backoff or adaptive concurrency based on observed throughput/error rate.
- Huey used for verification, but end-to-end signaling could be tighter
  - Single uploads create `AsyncUploadFile` records; multipart path does not create tracking records until completion, limiting visibility and resumability.

## Recommendations (prioritized)

1) Standardize on direct-to-S3 uploads
   - Prefer presigned single PUT for files ≤ 100MB and presigned multipart for larger files. Keep streaming/server-proxy flows only as a fallback (e.g., private MinIO not client-reachable).

2) Remove/retire server-proxy multipart path
   - Deprecate `storage/views/s3_multipart_upload_views.py` and its endpoints. The presigned multipart path already exists and is more scalable.

3) Unify thresholds and chunk sizes
   - Use a single source of truth for thresholds in settings and reuse them in server and client:
     - `multipart_threshold`: 100MB (AWS guidance; start multipart earlier in high-latency/slow networks if needed).
     - `chunk_size`: 8–16MB (start at 8MB; allow dynamic increase to 16–32MB when throughput is high and RAM is sufficient).
     - `max_concurrency`: 4–6 per file; 6–10 total across many small files. Derive a default from `navigator.hardwareConcurrency` and cap.
   - Expose these values to JS via a small config endpoint or inline script constants rendered by the server.

4) Add resumability for presigned multipart
   - Persist multipart state server-side and in the browser:
     - On init: create a DB record (e.g., extend `AsyncUploadFile` or add `AsyncMultipartUpload`) with `upload_id`, `s3_key`, `part_count`, and `completed_parts`.
     - In browser: also store `{uploadId, s3Key, partsCompleted}` in `localStorage` keyed by a stable file fingerprint (name + size + lastModified + path) so a refresh can resume.
     - Add endpoints to: list completed parts (`ListParts`), mark parts as completed as the client progresses, and to abort.
     - On re-open: look up existing session by fingerprint or server record; fetch completed parts and continue from the next missing part.

5) Implement robust retries and adaptive concurrency in JS
   - For each part PUT:
     - Retry with exponential backoff on 5xx, timeouts, and common S3 transient codes.
     - Use `AbortController` to cancel stuck requests and re-enqueue the part.
   - Adaptive concurrency: start at 3; if average part completes < X seconds without errors, increase by 1 up to a cap; on errors, decrease.
   - Track ETags and ensure parts are sorted by PartNumber at completion (already done server-side).

6) Strengthen integrity checks where supported
   - For AWS S3, prefer modern checksums (`x-amz-checksum-sha256`) on object upload if feasible in your environment; otherwise send `Content-MD5` for each part when generating presigned URLs and add the header in the browser requests.
   - Note: some S3-compatible systems do not support these headers; make it feature-flagged.

7) Tighten security and constraints on presigned URLs
   - Keep expirations short (15–30 minutes for multipart part URLs; refreshable if needed), and 10–30 minutes for single PUT.
   - Include content-type and size constraints where possible.
   - Continue to use AES256 SSE for non-MinIO.

8) Use Huey only for post-upload work, not transfer
   - Keep data transfer in the browser→S3. Use Huey to:
     - Verify presence/metadata of completed objects (`verify_and_process_upload`).
     - Kick off ingest/indexing workflows, previews, and notifications.
     - Periodic cleanup of stale multipart uploads (server-side `AbortMultipartUpload` for idle sessions older than N hours).
   - Consider increasing Huey workers to match workload (e.g., CPU count) for high ingestion rates, and ensure Redis persistence is stable.

9) Fix endpoint inconsistencies and dead code
   - Update or remove `static/js/src/s3/s3-client.js` (references `/storage/multipart/*`, which do not exist). Prefer the presigned multipart template + a single JS handler.
   - Consolidate to one multiparty client: use the presigned approach and delete/disable the server-proxy multipart JS (`s3-multipart-upload.js`) if not needed.

10) Ops and environment tuning
   - CORS: You already expose `ETag`; ensure AllowedMethods include `PUT`, `POST`, `HEAD` and origins cover your domains.
   - Network: If on AWS, consider S3 Transfer Acceleration for cross-region users; `BaseStorageService` can create an accelerated client for presigned URLs behind a feature flag.
   - Boto3 pooling: Set `AWS_MAX_POOL_CONNECTIONS` (or env consumed by `BaseStorageService`) to 64–128 if you see high concurrency on server-initiated calls (initiate/complete/abort/list parts).
   - Nginx/Reverse proxy: Presigned uploads bypass Django, so ensure CSP/CORS headers and large body limits don’t interfere with S3 endpoints.

## Concrete Implementation Plan

Phase 1: Clean-up and correctness
- Remove or gate the server-proxy multipart endpoints (`storage/views/s3_multipart_upload_views.py`) behind a feature flag. Prefer presigned multipart.
- Fix client endpoint mismatch: delete or correct `static/js/src/s3/s3-client.js` to use existing routes under `/storage/upload/*` or remove it entirely.

Phase 2: Unified configuration
- Add a small endpoint or inline template that exposes `MULTIPART_UPLOAD_SETTINGS` to JS (thresholds, chunk size, concurrency caps).
- Align chunk sizes: use 8MB default, allow 16–32MB via dynamic tuning.

Phase 3: Resumable multipart (presigned)
- Model: extend `AsyncUploadFile` (or add `AsyncMultipartUpload`) with fields: `upload_id`, `completed_parts` (JSON), `part_size`, `etag_map`, `last_heartbeat`.
- Endpoints:
  - `POST /storage/upload/presigned/multipart/init` → returns `upload_id`, `s3_key`, `part_size`.
  - `POST /storage/upload/presigned/multipart/parts` → returns presigned URLs for a range of part numbers, idempotent.
  - `GET /storage/upload/presigned/multipart/status` → returns uploaded part numbers (server-side via `ListParts`) for resumption.
  - `POST /storage/upload/presigned/multipart/mark` → optionally mark a part completed (helps if `ListParts` is costly).
  - `POST /storage/upload/presigned/multipart/complete` → already exists.
  - `POST /storage/upload/presigned/multipart/abort` → already exists.
  - Background cleanup task to abort idle multipart uploads > 24h via Huey periodic task.
- Browser:
  - Compute a stable file fingerprint. Store `{uploadId, s3Key, completedParts}` in `localStorage` as progress.
  - On page load, check server for status; resume from the next missing part.

Phase 4: Adaptive client behavior
- Add retries with exponential backoff and jitter per part.
- Adaptive concurrency based on observed throughput and error rate.
- Optional: cap total in-flight requests across files.

Phase 5: Integrity and security
- Feature-flag support for `Content-MD5` or `x-amz-checksum-sha256` in presigned part URLs; send the header from the browser if enabled.
- Keep presigned expirations short; refresh if upload spans multiple windows.

## Suggested Defaults

- Thresholds
  - Single PUT: ≤ 100MB
  - Multipart: > 100MB
- Chunk size: 8MB (increase to 16MB if RTT is high and memory allows)
- Concurrency: 4 parts per file, up to 8–10 total in flight
- Presigned expiry: 15–30 minutes for parts; 10–30 minutes for single PUT

## Notes on Huey

- Keep Huey outside the hot data path. It is excellent for:
  - Verifying uploaded objects, extracting metadata, creating DB records (`verify_and_process_upload`).
  - Post-processing (transcoding, OCR, previews), and progress polling endpoints for UI.
  - Cleaning up stale multipart sessions.
- Consider tuning Huey workers (e.g., 6–8 workers) if ingest throughput grows. Monitor Redis and worker CPU.

## Quick Wins

- Fix mismatched client endpoints and remove dead JS.
- Standardize chunk sizes and thresholds across settings, server, and client.
- Generate presigned multipart URLs only; disable server-proxy multipart path in production.
- Add basic retry/backoff on part PUTs in the browser.

## Longer-Term

- Full resumability across sessions for multipart using persisted state and `ListParts`.
- Optional S3 Transfer Acceleration (AWS) for remote users.
- Checksums on parts/objects when supported by the storage backend.

---

References (paths):
- Settings: `config/settings/base.py` (`HUEY`, `MULTIPART_UPLOAD_SETTINGS`), `production.py` (S3), `dev.py`/`local.py` (dev overrides)
- Services: `arkumu/storage/services/base_storage_service.py`, `.../upload/presigned_url_service.py`, `.../upload/upload_utils.py`, `.../upload_service.py`
- Views: `arkumu/storage/views/upload_views.py`, `.../s3_multipart_upload_views.py`, `.../streaming_upload_views.py`
- Tasks: `arkumu/storage/tasks.py`
- Client JS: `arkumu/static/js/src/s3/s3-multipart-upload.js`, `arkumu/static/js/src/s3/upload-form-handler.js`, `arkumu/static/js/src/s3/s3-client.js`

