# Logging & Diagnostics

## Log Levels (`LOG_LEVEL`)

Application and API logging supports three levels configured via the `LOG_LEVEL` environment variable in `.env`:

| `LOG_LEVEL` | What is written | Use Case |
|---|---|---|
| `debug` | Verbose traces: ASGI request timing & status, snippet discovery, index inputs/metrics, serialization. | Development & incident diagnosis. |
| `info` *(default)* | Start-up parameters, index completion events, spot counts, watch loop status. | Normal operations. |
| `error` | Failures only: database exceptions, index failures, unhandled ASGI errors. | Production alerts. |

> `DEBUG=true` is also supported as an alias for `LOG_LEVEL=debug` for backward compatibility.

## Log Destinations

Logs are emitted simultaneously to two destinations:
1. **Standard Error / Stdout**: Streamed directly to `docker compose logs -f backend indexer`.
2. **Persistent Log File**: Written to `/data/logs/cem-master-backend/app.log`, mounted from the host (`data/logs/cem-master-backend/`).

## How to Enable Verbose Logging

Set `LOG_LEVEL=debug` (or `DEBUG=true`) in `.env`, then recreate the containers:

```sh
docker compose -f compose.yaml -f compose.local.yaml up -d
docker compose -f compose.yaml -f compose.local.yaml logs -f backend indexer
```

To tail the persistent log file directly:
```sh
tail -f ../cem-backend/data/logs/cem-master-backend/app.log
```

## Snippet Audio Debug Flow

If a 9-second clip player is absent on the UI:
1. Check `snippets.loaded` / `snippet.indexed` in `app.log` during index runs.
2. Confirm the compute stack generated `snippets/species_snippets.json` and 9s `.wav` files in `DATA_DIR/projects/<project>/snippets/`.
3. Check `species.serialize` output in API responses.


