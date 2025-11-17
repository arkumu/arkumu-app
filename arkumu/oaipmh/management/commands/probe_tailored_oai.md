# probe_tailored_oai command

This management command probes the tailored `/oai/tailored/` endpoint against any live base URL so you can validate the new resumption tokens before harvesters do. It shares logic with the optional CLI wrapper (`scripts/probe_tailored_oai.py`).

## What it does

1. Issues the requested verb (`ListIdentifiers` or `ListRecords`) against `/oai/tailored/` with any provided filters (`set`, `from`, `until`).
2. Prints how many headers/records were returned and decodes the resumption token payload so you can verify `profile`, `rt_version`, cursor marker, etc.
3. Optionally performs any combination of:
   - A follow-up `/oai/tailored/` request with the token to ensure pagination resumes correctly.
   - A replay of the token against `/oai/db/` and `/oai/` so you can confirm those endpoints reject tailored-profile tokens.
   - A pause so you can tweak curated data/approvals, then replay the original token to observe `badResumptionToken` after a dataset change.

## Running inside Docker (recommended)

```bash
BASIC_AUTH="user:pass"
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py probe_tailored_oai \
  --base-url https://dev.arkumu.org \
  --basic-auth "$BASIC_AUTH" \
  --metadata-prefix oai_dc \
  --set-spec some_org \
  --internal-bypass \
  --pause-for-dataset-change
```

## Key options

| Flag | Description |
| --- | --- |
| `--base-url` | Required. Base server URL to probe. |
| `--verb` | `ListIdentifiers` (default) or `ListRecords`. |
| `--metadata-prefix` | Metadata prefix to request (`oai_dc`, `mets`, …). |
| `--set-spec`, `--from-date`, `--until-date` | Optional OAI filters. |
| `--basic-auth USER:PASS` | Adds HTTP Basic credentials. |
| `--internal-bypass` | Sends `X-INTERNAL-OAI-BYPASS=1` header. |
| `--skip-tailored-resume` | Skip the follow-up `/oai/tailored/` call. |
| `--skip-db` / `--skip-snapshot` | Skip cross-endpoint checks. |
| `--pause-for-dataset-change` | Pause so you can mutate data, then rerun the stored token to confirm `badResumptionToken`. |

Use these knobs to replicate the exact harvesting sequence you need (e.g., just tailored-only happy path, or full cross-endpoint validation) against dev/staging before contacting external harvesters.
