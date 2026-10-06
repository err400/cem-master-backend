# Test CEM compute and master

Use [CEM_SETUP_GUIDE.md](CEM_SETUP_GUIDE.md) to configure and start both stacks
first. This document verifies the user workflow and describes automated tests;
it is not a second installation guide.

## End-to-end user verification

Local compute is http://localhost:8080 and master is http://localhost:8000.
Deployed compute is https://www.cse.iitd.ernet.in/act4dws5/bio/ and master is
https://www.cse.iitd.ernet.in/act4dws5/bio-master/.

1. Open compute and click **Initialize Storage**. Select a local folder, or use
   the IndexedDB fallback. This enables the application controls. Google Drive
   login is optional and requires configured Google integration credentials.
2. Create/select a project and add a spot with its name, latitude and longitude.
   A site polygon/KML and Earth Engine stratification are optional and are not
   prerequisites for BirdNET publication.
3. Import original WAV recordings for the spot. Use filenames such as
   `SPOT1_20261006_060000.wav` (`SPOTNAME_YYYYMMDD_HHMMSS.wav`). Leave **Import as
   reference** unchecked: references point to local files and cannot be analyzed
   on the server. Import initially uses browser project storage; server analysis
   uploads selected readable audio to compute's shared `/data` folder.
4. Open Analysis, choose server execution and BirdNET Species Detection, select
   the spot and a date range containing the recording date, and queue the job.
   Spot coordinates must reach the server analysis inputs. API clients use
   compact `YYYYMMDD` dates; the browser converts its date fields.
5. Check Jobs and wait for successful completion. Inspect output/logs if there
   are zero detections or missing files. Dependent analyses need BirdNET results;
   acoustic indices process WAVs directly. Local watcher runs alone are not
   sufficient for server publication.
6. Make Public. The server requires completed BirdNET output and
   `dataset/aggregate.csv`. The master indexer polls the same physical data folder
   (default interval 30 seconds).
7. Refresh master and check the spot marker, species inventory, detection counts
   and available analysis summaries. Public species visibility rules can filter
   detections. Do not assume every compute attachment or KML polygon is imported
   into the master catalogue.
8. Play a full recording and an available bird snippet. Check the Network panel
   for a successful audio response under the correct API prefix. A metadata card
   does not prove that its original WAV is accessible to the backend.
9. Check output download links if FileBrowser is enabled. Without shares, output
   names without download links are expected.

For curl-based publication and missing-map diagnostics, see
[Publication and indexer troubleshooting](docs/first-time-local-publication.md).

## Master automated tests

Run from `cem-master-backend` using a host virtualenv. Python 3.12 matches the
runtime image. Dependencies are split: `requirements.txt` is runtime;
`requirements-dev.txt` includes runtime dependencies plus pytest/httpx. The
runtime Docker image does not install pytest.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

The setup guide writes `TEST_DATABASE_URL` into private `.env` for the separate
`cem_master_test` database. Load only that setting without printing its value:

```bash
export TEST_DATABASE_URL="$(python - <<'PYENV'
from pathlib import Path
for line in Path('.env').read_text().splitlines():
    if line.startswith('TEST_DATABASE_URL='):
        print(line.split('=', 1)[1])
        break
PYENV
)"
python -m pytest
```

Use only a disposable test database: database fixtures recreate schema/data.
Without `TEST_DATABASE_URL`, database-dependent modules are skipped; a passing
run with skips does not verify PostgreSQL migrations or API database behavior.
The init SQL creates the test database only on the database volume's first
initialization. If missing on an existing local development installation:

```bash
docker compose -f compose.yaml -f compose.local.yaml exec -T cem-database \
  createdb -U cem_user cem_master_test
```

The bundled setup assumes the `cem_user` role and `cem_master` database.
Do not delete the data volume just to create a test database.

## Frontend automated tests

With Node.js installed, run independently from each frontend repository:

```bash
node --test tests/*.test.mjs
```

These tests verify browser diagnostic helpers; they do not replace the deployed
upload, publication, proxy routing and audio playback checks above.
