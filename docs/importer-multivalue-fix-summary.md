# Importer Multi-Value FK & Junction Improvements

## Overview
- Multi-value foreign key columns are now processed alongside regular multi-value fields so each entry produces a literal triple while still queuing FK relationships.
- Junction processing expands primary and secondary FK values when either column is multi-value, generating one junction entity per combination and copying context attributes and links for every pair.
- Added a shared helper to extract and normalize junction FK values based on mapping metadata, keeping the behaviour consistent with FK queueing.

## Tests
- `docker compose -f docker-compose.local.yml run --rm django pytest arkumu/importer/tests/services/execution/test_multivalue_fk_and_junction_processing.py`
