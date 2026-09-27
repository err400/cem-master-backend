# How to Test — CEM Compute Website

> **Purpose:** This guide walks you through testing the full data pipeline using the **CEM Compute website** (`cem-compute-2`). Completing these steps end-to-end ensures that data entered here will flow correctly and appear on the **main CEM website**.

---

## Prerequisites

Before you begin, make sure the following are running:

- The **backend server** (FastAPI) is up — `docker compose up` or equivalent
- The **frontend** is accessible in your browser (e.g. `http://localhost`)
- You have a **Google account** (Gmail) to log in with
- You have your **audio `.wav` files** ready, named with the correct convention (see Step 6)
- You have a **KML file** for your site boundary (if adding a new site)

---

## Step 1 — Google Login

1. Open the CEM Compute website in your browser.
2. In the **left sidebar (control panel)**, you will see the **auth section** at the top.
3. Click the **"Sign in with Google"** button.
4. A Google OAuth popup will appear — select your Gmail account and grant the requested permissions.

> **What this does:** Authentication uses the Google Identity Services (`accounts.google.com/gsi/client`) to get your Google credentials. These are used to access and store project data in **Google Drive** under your account. All project files (spots, media, analysis results) are tied to this Google identity.

5. Once signed in, all the buttons in the sidebar (which were previously greyed out / disabled) will become **active**.

---

## Step 2 — Initialize Storage (First-Time Setup)

After logging in for the first time, you must initialize storage before doing anything else.

1. After sign-in, you will be prompted (or see a button) to **Initialize Storage**.
2. Click it. A **folder picker dialog will open in your browser** — select a folder on your **local computer** where project data should be stored (e.g., `D:\CEM_Projects`).

> **What this does:** Storage is handled entirely on your local machine — nothing goes to Google Drive at this step. The app uses the browser's **Native File System API** (`showDirectoryPicker`) to read and write files directly into the folder you choose. Your `master_data.json` (which holds all spots, sites, and metadata) is saved there. On browsers that don't support the Native FS API, it falls back to **browser IndexedDB** (in-browser storage) automatically — no folder picker appears in that case.

3. Once the folder is selected (or IndexedDB is initialized), you'll see a toast notification confirming storage is ready.

---

## Step 3 — Create or Select a Project

1. At the top of the left sidebar, find the **Project** dropdown.
2. To create a new project, click **"New"** → enter a project name → click **OK**.
3. To work on an existing project, select it from the dropdown.

> **Optional:** You can also **Share** a project with collaborators (by Gmail address), **Rename** it, or toggle its **public visibility** (public projects are visible on the main website after analysis is complete).

---

## Step 4 — Add a Site *(Optional for Basic Testing)*

> **You do not need to add a Site to add Spots or run analysis.** Sites are geographic boundary polygons that visually group spots on the map. For basic end-to-end testing, you can skip this step and go straight to [Step 5 — Add Spots](#step-5--add-spots).

A **Site** is the geographic boundary of your monitoring area (e.g., a forest polygon). It is used to visually delineate the study area on the map.

### Add Site via KML File

1. Click the **"Add Site"** button in the sidebar.
2. The **"Add New Site"** dialog will appear.
3. Enter a **Site Name** (e.g., `SanjayVan`).
4. Click the **KML upload area** and select your `.kml` file.
   - The KML must contain a `<coordinates>` element describing a **polygon** (minimum 3 coordinate pairs).
   - Format inside the KML: `lon,lat[,alt]` pairs separated by whitespace.
5. Click **Submit**.

> The site boundary will be drawn as a green polygon on the map. The map will automatically zoom to fit it.

### After Adding a Site — Stratification (Optional)

After submitting the site, you may be asked: **"Stratify this Site?"**

- This runs a **Google Earth Engine (GEE) satellite clustering** job to generate habitat stratification overlays for the site boundary.
- Select the **max number of clusters** (2–8; default is 5) and click **"Stratify via Server"** to queue it, or **"Don't Stratify"** to skip.
- This step is optional.

---

## Step 5 — Add Spots

A **Spot** is a specific monitoring location (e.g., where an audio recorder was placed) within a site.

### Adding a Spot with Coordinates

1. In the left sidebar, under **"Spots"**, click the **"Add"** button.
2. The **"New Spot"** form will appear.
3. Fill in:
   - **Spot name** — this becomes the `spot` label used across the entire pipeline. Keep it consistent (e.g., `CRIMESPOT3`).
   - **Description / field notes** — optional free-text.
4. **Location:**
   - By default, **"Use current location"** is checked — this uses your device's GPS.
   - To enter coordinates manually: **uncheck** "Use current location", then enter **Latitude** and **Longitude** in the fields that appear.
5. **Date & Time:**
   - By default, the **current date and time** is used.
   - To set a custom date/time: **uncheck** "Use current date & time" and enter them manually.

---

### What are Camera, Gallery, and Audio for?

These are **media capture options** available directly in the "New Spot" form. They let you attach media *at the moment of creating a spot* — most useful when adding spots in the field from a mobile device:

| Button | Purpose |
|--------|---------|
| Camera | Opens the device camera to take a photo on the spot and attach it immediately. Useful on mobile phones/tablets in the field. |
| Gallery | Opens a file picker to select one or more existing image files from your device. Use this on desktop to attach photos taken separately. |
| Audio (mic icon) | Starts/stops a microphone recording directly in the browser using the MediaRecorder API. The recorded audio (.webm) is attached to the spot. |

> **Note for desktop testing:** Camera may open a file browser instead of a live camera feed. The audio recorder will prompt for microphone permissions. The recorded clip appears in the built-in audio player for preview before submitting.

6. Once you have filled in all details (and optionally attached media), click **Submit**.

The spot will appear as a marker on the map. Check the **"Show"** toggle in the Spots section to make all spot markers visible.

---

## Step 6 — Import Media (Upload Audio Files)

This is the main step for uploading your field audio recordings (.wav files) to be associated with spots for analysis.

1. Click the **"Import Media"** button in the sidebar.
2. The **"Import External Media"** dialog will open.

### 6a — Select the Target Spot(s)

- A list of all your spots will appear as checkboxes.
- Check the spot(s) that this batch of files belongs to.

### 6b — Select Files

- Click the file input and select your `.wav` files.
- You can select **multiple files** at once.

### 6c — Import as Reference (Optional)

- If you check **"Import as reference"**, the files are **not copied** to the server — only their path is stored. You will also need to enter a **Base Directory Path** (e.g., `D:\Recordings\Site1`) so the server can locate them at analysis time.
- Leave this **unchecked** for normal uploads (files are physically copied into project storage).

### 6d — Click "Import"

Files are uploaded and stored on the server under:

```
<DATA_DIR>/projects/<project_name>/<SPOT_NAME>/audio/
```

---

## Audio File Naming Convention

> **This is critical.** The entire analysis pipeline extracts spot identity, date, and time directly from the audio filename. Files that do not follow this convention will be treated as "external" and **will not be attributed correctly** to a spot or time window.

### Required Format

```
SPOTNAME_YYYYMMDD_HHMMSS.wav
```

### Examples

| Filename | Spot | Date | Time |
|----------|------|------|------|
| `CRIMESPOT3_20251130_093100.wav` | CRIMESPOT3 | 2025-11-30 | 09:31:00 |
| `SPOT1_20251215_060000.wav` | SPOT1 | 2025-12-15 | 06:00:00 |
| `RIVERBANK_20260101_183000.wav` | RIVERBANK | 2026-01-01 | 18:30:00 |

### Rules

- **SPOTNAME** — alphanumeric characters, underscores, and hyphens allowed. Must match the spot name created in Step 5 (case-insensitive).
- **YYYYMMDD** — 4-digit year, 2-digit month (01–12), 2-digit day (01–31). Must be a valid calendar date.
- **HHMMSS** — 2-digit hour (00–23), 2-digit minute (00–59), 2-digit second (00–59). Uses 24-hour clock.
- Extension must be `.wav` or `.WAV`.

This is the **Song Meter / CEM convention** automatically parsed by `cem-backend/pipeline/file_metadata.py`:

```regex
^(?P<spot>[A-Za-z0-9][A-Za-z0-9_-]*)_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\.[A-Za-z0-9]+$
```

---

## Step 7 — Run Analysis

After uploading audio files, you can run the ecological analysis pipeline.

1. Click the **"Analysis"** button in the sidebar.
2. The **Analysis Hub** dialog will open.

### 7a — Choose Execution Mode

| Mode | Description |
|------|------------|
| Local Watcher | Runs analysis locally on your computer. Requires running `python watcher.py` in your terminal at the project root first. |
| Connect to Server | Queues the job on the remote compute server. **Recommended** for production testing. |

> If the watcher status indicator is grey (offline) in Local mode, run `python watcher.py` in your terminal before proceeding.

### 7b — Enter a Job Name

- Fill in the **Job Name** field (e.g., `River Survey - Morning`). This field is **required**.

### 7c — Select Analysis Script

From the **"1. Select Analysis Script"** dropdown, choose what to run:

| Analysis Script | What it does | Depends on |
|----------------|-------------|-----------|
| **BirdNET Species Detection** | Runs BirdNET neural network on raw WAV files; discovers and filters bird species; appends detections to `birdnet_results.csv`. | Nothing — run this first |
| **Species Activity Heatmaps** | Per-spot hourly activity heatmaps (normalized + raw counts). | BirdNET |
| **Activity Regularity (Temporal)** | Spearman correlation of consecutive-day hourly activity vectors per species — measures how regular call patterns are. | BirdNET |
| **Habitat Affinity (Spatial)** | Spearman correlation of consecutive-day spatial distribution vectors across spots. Requires 2 or more spots. | BirdNET |
| **Migratory vs Resident** | Classifies species as migratory or resident using SCI, residual kurtosis, and PMR. | BirdNET |
| **Solar Event Correlation** | Pearson correlation between daily peak activity hour and local sunrise/sunset times. | BirdNET |
| **Daily Call Time Series** | Per-species daily call-count line plots + data availability heatmap. | BirdNET |
| **Acoustic Indices + Box Plots** | Computes 6 acoustic indices (ADI, ACI, AEI, NDSI, MFC, CLS) from raw audio. | None — runs directly on WAV files |

### 7d — Select Input Data

- Under **"2. Select Input Data"**, your spots appear as checkboxes.
- **Check the spots** you want to include.
- Set the **date range** — only files whose filenames fall within this range are processed.

### 7e — Configure Parameters (Optional)

If the script has tunable parameters, a **"3. Configure Parameters"** section appears:

| Parameter | Default | Description |
|-----------|---------|-------------|
| SNR for noise removal (dB) | 18 | Clips below this SNR threshold are denoised before processing |
| Min detection confidence (BirdNET) | 0.25 | Minimum BirdNET score to accept a detection |
| Min detection confidence (filter) | 0.3 | Post-BirdNET confidence filter applied by analysis scripts |
| Min detections per species | 10 | Species with fewer total detections are excluded from plots |
| Top N species to plot | 25 | Number of top species shown in heatmaps |
| Top N (temporal stickiness) | 80 | Species count for the temporal regularity plot |
| SCI threshold | 0.9 | Seasonal Concentration Index cutoff for migratory classification |
| Kurtosis threshold | 15 | Residual kurtosis cutoff for migratory classification |
| PMR threshold | 50 | Peak-to-median ratio cutoff for migratory classification |
| Window size (days) | 60 | Rolling window size for migratory classification |
| Min solar days | 5 | Min days with >10 detections required for solar correlation |
| Max species (time series) | 50 | Max species in daily call time series plots |

### 7f — Queue the Job

- Click **"Queue Job"**.
- The job is submitted to the server (or local watcher) and begins processing.

---

## Step 8 — Monitor Jobs

1. Click the **"Jobs"** button in the sidebar to open the **Analysis Jobs** panel.
2. The **left column** lists all queued/running/completed jobs.
3. Click a job to see its **status** and **output files** on the right.
4. Click an output file (CSV, chart image, etc.) to **preview** it in the built-in viewer.
5. Use **"Refresh"** to update job statuses.

> Jobs run asynchronously. A job with status "completed" and output files means the analysis succeeded and the data is ready for the main website.

---

## Step 9 — Verify Data on the Main Website

After completing the above steps, confirm that data appears correctly on the main CEM website:

1. Go to the **main CEM website**.
2. Your project must be set to **public** — use the "Make Public" toggle in the Project section of the sidebar on the compute site.
3. Confirm the following on the main website:
   - **Site polygons** appear on the map.
   - **Spot markers** are visible and clickable.
   - Clicking a spot shows correct **media** (images/audio) and **field notes**.
   - **Analysis results** (charts, CSVs) from Step 7 are accessible and display correctly.

---

## Quick Reference — Workflow Summary

```
1. Open compute website
2. Google Login → Initialize Storage
3. Create / Select Project
4. Add Site  →  upload KML polygon  →  (optional: Stratify)
5. Add Spot(s)  →  enter name + coordinates  →  (optional: Camera / Gallery / Audio)
6. Import Media  →  select spot(s)  →  upload .wav files (must follow naming convention)
7. Analysis  →  enter job name  →  select script  →  select spots + date range  →  configure params  →  Queue Job
8. Jobs  →  monitor status  →  preview output files
9. Main website  →  verify sites, spots, media, and analysis results are visible
```

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| All sidebar buttons stay greyed out after login | Storage not initialized | Click the "Initialize Storage" prompt after login |
| KML upload fails | Missing `<coordinates>` in KML or fewer than 3 points | Validate your KML file — it must define a valid polygon |
| Audio files not picked up in analysis | Filename does not match convention | Rename files to `SPOTNAME_YYYYMMDD_HHMMSS.wav` |
| Analysis job stays "pending" forever | Server offline or watcher not running | Check server logs; or start `python watcher.py` for local mode |
| Data not visible on main website | Project not set to public | Enable the "Make Public" toggle in the Project section |
| Heatmap / stickiness / migratory / solar analysis fails | BirdNET has not been run yet | Run **BirdNET Species Detection** first; all dependent scripts read `birdnet_results.csv` which it produces |
| Acoustic Indices fails | No WAV files found for selected spots/date range | Verify files were imported and naming convention is correct |
| Stratify dialog does not appear | May have been dismissed or GEE not configured | Check server GEE configuration and re-add the site if needed |
