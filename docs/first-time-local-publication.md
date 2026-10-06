# Publication and indexer troubleshooting

Complete [CEM_SETUP_GUIDE.md](../CEM_SETUP_GUIDE.md) first. Use the same private
configuration and Compose overlays here; do not overwrite an existing `.env`.

## Data flow

```text
compute uploads WAVs → server BirdNET analysis → Make Public
    → shared DATA_DIR/projects → master indexer → PostgreSQL → public website
```

Compute, master API and master indexer must see the same physical data folder.
Compute writes it; both master services mount it at `/data` read-only. Publishing
updates project visibility; it does not copy files to master or call a separate
placeholder publication API.

## API publication example

Run from a Bash terminal. For local use:

```bash
export COMPUTE_API="http://localhost:8002"
export MASTER_API="http://localhost:8000"
```

For the current deployed master proxy, use
`MASTER_API=https://www.cse.iitd.ernet.in/act4dws5/bio-master/api`.
Set `COMPUTE_API` to the server administrator's confirmed compute API base;
the compute UI URL alone does not establish its API route. Both deployed UIs
share origin `https://www.cse.iitd.ernet.in` for CORS configuration.

Choose a project/spot and a directory containing matching WAV filenames.
Use identifier values without quotes or shell metacharacters in this example:

```bash
export PROJECT="demo_project"
export SPOT="SPOT1"
export LAT="28.533"
export LON="77.176"
export START_DATE="20261006"
export END_DATE="20261006"
export WAV_DIR="/absolute/path/to/wavs"
export JOB_ID="job_$(date +%s)"
```

For these dates use filenames such as `SPOT1_20261006_060000.wav`.
Upload WAV files:


```bash
for f in "$WAV_DIR"/*.wav; do
  [ -e "$f" ] || { echo "No .wav files found in $WAV_DIR"; exit 1; }
  curl --fail-with-body -sS -X POST "$COMPUTE_API/api/v1/projects/upload/audio" \
    -F "project=$PROJECT" \
    -F "spot=$SPOT" \
    -F "files=@$f"
  echo
done
```

Run BirdNET on the compute server:

```bash
curl --fail-with-body -sS -X POST "$COMPUTE_API/api/v1/analyze" \
  -H "Content-Type: application/json" \
  -d "{
    \"project\": \"$PROJECT\",
    \"spots\": [\"$SPOT\"],
    \"start_date\": \"$START_DATE\",
    \"end_date\": \"$END_DATE\",
    \"spots_geo\": [{\"name\": \"$SPOT\", \"lat\": $LAT, \"lon\": $LON}],
    \"job_id\": \"$JOB_ID\",
    \"script\": \"birdnet\",
    \"min_confidence\": 0.25
  }" | python3 -m json.tool
```

Make it public:

```bash
curl --fail-with-body -sS -X POST "$COMPUTE_API/api/v1/projects/publish" \
  -H "Content-Type: application/json" \
  -d "{\"project\":\"$PROJECT\"}" | python3 -m json.tool
```


## Confirm publication and indexing

```bash
curl --fail-with-body -sS "$COMPUTE_API/api/v1/projects/status?project=$PROJECT" | python3 -m json.tool
```

From `cem-master-backend`, define the matching `cem_compose` function from the
setup guide (include `compose.production.yaml` for its single-server deployment).
Check the project metadata in the indexer's mounted tree:

```bash
cem_compose exec -T indexer python -c 'import json,sys; from pathlib import Path; p=Path("/data/projects")/sys.argv[1]/"project.json"; d=json.loads(p.read_text()); print({k:d.get(k) for k in ("visibility","is_public","published_at")})' "$PROJECT"
cem_compose exec -T backend python -m app.indexer --data-dir /data --project "$PROJECT"
curl --fail-with-body -sS "$MASTER_API/api/v1/spots" | python3 -m json.tool
cem_compose logs --tail=100 indexer
```

A fresh empty catalogue is expected until a useful public project is indexed.
`no public projects` can mean no project has been published, the mount is wrong,
or metadata is missing; the message alone does not identify which cause applies.

Check inside both master services:

```bash
cem_compose exec -T backend ls -la /data/projects
cem_compose exec -T indexer ls -la /data/projects
cem_compose exec -T indexer ls -lh "/data/projects/$PROJECT/dataset/aggregate.csv"
```

Compare with the compute data folder named by `CEM_DATA_DIR_HOST`. If the project
is elsewhere, correct the shared host path in both `.env` files and recreate the
services. Do not reset the database volume. If public metadata is present but
no useful rows appear, check server BirdNET completion, nonempty aggregate
results, selected dates, spot coordinates and public-species visibility rules.

## Recordings visible but playback fails

Inspect the audio request in browser DevTools. The configured API prefix must
be retained for both raw recordings and snippets. The current deployed raw
stream route is `/act4dws5/bio-master/api/api/v1/recordings/<audio_id>/stream`.

- A redirect or HTML response usually means the request hit the wrong route.
- `Recording not found` means no accessible public recording matched the ID.
- `Audio file not found` means the backend could not locate the WAV in `/data`;
  it does not establish whether the file is absent from the host or just mounted
  elsewhere. Check the API container as well as the indexer container.

Original files belong under
`/data/projects/<project>/<spot>/audio/<filename>` or their indexed relative path.
Restore missing originals or correct mounts/paths, then retry playback. Reindex
if the project's metadata paths changed. Metadata cards alone do not verify files.

## Optional output downloads

Compute `FILEBROWSER_BASE_URL=http://filebrowser:80` is an internal URL used to
create shares. Master `FILEBROWSER_PUBLIC_URL` is the browser-accessible HTTPS
URL used to render downloads. Keep both disabled until FileBrowser and its
credentials/access controls are configured. Shares are created during analysis;
older jobs without hashes may need to be rerun after enabling the integration.
