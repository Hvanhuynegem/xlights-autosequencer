<p align="center">
  <img src="assets/logo.svg" alt="xLightsAI logo" width="200">
</p>

<h1 align="center">xLightsAI</h1>
<p align="center"><strong>MP3 to xLights Sequencer</strong></p>
<p align="center">
  Analyzes your music, detects beats/onsets/chords/sections, groups your layout props, and applies themed effects — all driven by the audio.
</p>

---

## What It Does

1. **Audio Analysis** — Analyzes MP3 files using 17 algorithms across 7 hierarchy levels (L0-L6) to extract beats, onsets, chords, sections, energy curves, and stem separation (drums/bass/vocals/guitar/piano/other)
2. **Layout Grouping** — Reads your `xlights_rgbeffects.xml` and auto-generates 8-tier Power Groups (spatial, rhythmic, prop type, compound, heroes)
3. **Effect Library** — 40 xLights effects cataloged with parameters, prop suitability ratings, and analysis-to-parameter mappings
4. **Variant Library** — 212+ pre-tuned effect variants with contextual tags (energy, tier, section role, genre) for quick effect selection
5. **Theme Engine** — 21 composite "looks" (Inferno, Aurora, Winter Wonderland, etc.) organized by mood, occasion, and genre
6. **Song Story** — Automatic section classification with lyric-anchored boundary refinement (syncedlyrics), energy arcs, and lighting moment detection
7. **Sequence Generation** — Produces `.xsq` sequences with effects placed by tier, energy, and theme, packaged with the matching xLights layout
8. **Web UI** — Browser-based dashboard for the full workflow: upload, analyze, review, edit themes, browse variants, group layout, and export

---

## Quick Start

This is the maintained walkthrough for **song → analysis → generated
package → working preview in xLights**, including use with an existing
show. The [screen reference](#the-screens) below explains the individual
controls in more detail.

You need Git, **Docker Desktop** (or Docker Engine with Compose on Linux),
[xLights](https://xlights.org/) installed on your computer, and an MP3 or
WAV file. Keep the original music file: it is **not included in the
downloaded package**. Docker supplies the app's Python, Node, ffmpeg,
and analysis dependencies; you do not need a separate native Python setup
for this walkthrough.

### 1. Download and start the app

```bash
git clone https://github.com/derwin12/xlights-autosequencer.git
cd xlights-autosequencer
```

The default port mapping in `docker-compose.yml` is **`"54321:5000"`**:
port **54321 on your computer** forwards to port **5000 inside Docker**.
This avoids the macOS system-service conflict on host port 5000. No
manual port change is needed for the default setup.

No fixed port is guaranteed to be free on every computer. If 54321 is
already in use, change the mapping to another unused host port, such as
`"54322:5000"`, and use `http://localhost:54322` throughout this guide.

```bash
docker compose up
```

Wait for the server to start, then open **http://localhost:54321**. First
run builds the toolchain image (the Vamp plugins compile from source —
the slow step, easily 20–40 min, but
fully unattended) and installs the Python/JS packages; later runs are
fast. Your song library and cached analysis persist in named Docker
volumes across restarts. Leave Docker running while you use the app. The
container log may still say `localhost:5000`; your browser uses
**http://localhost:54321** with the default mapping. If you already have
a container running with the old mapping, run `docker compose up -d
xonset` to recreate it with the updated port; a restart alone does not
apply port changes.

### 2. Choose the layout that the sequence will use

**The web app uses one layout for all songs:**
[`layout/xlights_rgbeffects.xml`](layout/xlights_rgbeffects.xml). It does
not automatically read your local xLights show folder, and there is no
per-song layout upload in the current web workflow. The supplied file is
the repository's example display.

To generate for **your own existing show**:

1. Save your layout in xLights, then close xLights.
2. Back up the repository's two XML files in `layout/` outside that
   directory. Copy `xlights_rgbeffects.xml` and `xlights_networks.xml`
   from your existing show folder into the repository's `layout/`,
   replacing the example files. These files stay local to your checkout.

For a first preview of the **example display**, keep the supplied layout
files instead. In step 7, use a separate show folder for that example.

**For either layout choice**, prepare the Power Group definitions before
generating a sequence. Back up `layout/xlights_rgbeffects.xml`, then run:

```bash
docker compose exec xonset xlight-analyze group-layout /workspace/layout/xlights_rgbeffects.xml
docker compose restart xonset
```

Refresh the browser. Before generating, check the **Export** tab's
Reference Layout and prop count against your display. The name can
simply be `xlights_rgbeffects.xml`, so also inspect the XML's model
names if you are unsure which layout is loaded.

The grouping command preserves your model definitions and manual groups,
and replaces groups with reserved prefixes `01_BASE_` through
`08_HERO_`. Run it with its default options as shown so the definitions
match the groups the web generator creates. Restart after changing the
layout because the server caches it. If you switch layouts later,
generate and download a new package for that layout.

### 3. Import a song and let analysis finish

Open **Library** or **Import** and drag in your MP3/WAV, or use the file
picker. The app switches to **Analyze** and starts the pipeline.

Check the artist/title fields, especially if you want lyric lookup to
match the correct recording. Wait for **Analysis complete** before
continuing. The first song may take longer while analysis models download;
later runs reuse cached work.

### 4. Review the timeline and confirm themes

1. Open **Timeline**, play the song, and check that beats and section
   boundaries match what you hear. Adjust sections if needed.
2. Open **Theme**. For the quickest first result, click **Accept All
   Defaults** to confirm the suggested themes for every section. You can
   also choose themes per section and adjust brightness, hit strength,
   dwell time, and color shift.
3. **Extras** is optional; skip it for your first sequence. It adds
   pictures, shadow text, and moving-head triggers.

Every section must have a confirmed theme before Export is available.

### 5. Generate and download the sequence package

Open **Export**, check the Reference Layout again, and click **Generate
Sequence**. When generation completes, click **Download Package** and
save the `.xsqz` file, for example `song_AI.xsqz`.

**Save Bundle** on this screen downloads a JSON backup of song settings;
it is a different download and is not the xLights sequence package.

### 6. Extract the downloaded ZIP archive

**The `.xsqz` download is a ZIP archive. Extract it first, then open the
`.xsq` inside it.** Renaming the archive alone does not extract it.

On macOS, use Terminal (replace `song_AI` with your download's name):

```bash
unzip "$HOME/Downloads/song_AI.xsqz" -d "$HOME/Downloads/song_AI_export"
```

Alternatively, duplicate the download in Finder, rename the **copy** from
`.xsqz` to `.zip`, confirm the extension change, and double-click it to
extract with Archive Utility. On Windows, rename a copy to `.zip` and use
**Extract All**; on Linux, use `unzip` or your archive manager.

The extracted folder contains:

| File | Purpose |
|------|---------|
| `song_AI.xsq` | Editable sequence: effects, timing tracks, and references to model/group names and media. This is the file you open in xLights. |
| `xlights_rgbeffects.xml` | Matching layout: models, submodels, previews, and Power Group definitions. |
| `xlights_networks.xml` | Controller/network configuration from `layout/`; included when that file exists. |

The package does **not** include the original music, external shader
files, or a rendered `.fseq`. The sequence needs the matching layout and
any referenced external files to render correctly.

### 7. Replace the layout XML in your existing show folder

With xLights closed, use your **existing show folder** from step 2:

1. Back up its current `xlights_rgbeffects.xml`, for example as
   `xlights_rgbeffects.xml.bak`.
2. Copy the extracted **`xlights_rgbeffects.xml` into the root of the show
   folder**, replacing the old file. Use the XML from the same download
   as the sequence.
3. Copy `song_AI.xsq` into the show folder and keep the original music
   there too (if it is not already there).

When you generate from your own layout, the packaged XML preserves your
models and manual groups and includes the generated **Power Groups**,
including spatial regions. Replacing the old XML makes these additional
effect targets available to xLights when you open the sequence.

Choose the networks file deliberately:

- **Existing show with working controllers:** keep your existing
  `xlights_networks.xml`. Copying in the package's networks file is
  unnecessary if it came from the same show, and a file from a different
  display can replace your controller configuration. Check model channel
  assignments against your controllers before using physical lights.
- **Separate preview of the repository's example display:** create a new
  folder and copy in both packaged XML files, the sequence, and your
  music. The packaged networks file belongs to that example display;
  it does not configure your own hardware.
- **Restoring the exact configuration used for generation:** use the
  packaged networks file when you intentionally want that configuration
  and it matches the selected layout.

#### Why the sequence has unfamiliar group names

Power Groups are generated targets for different lighting roles:
`01_BASE_` (whole-display wash), `02_GEO_` (spatial zones), `03_TYPE_`
(architecture), `04_BEAT_` (rhythm), `05_TEX_` (detail), `06_PROP_`
(prop types), `07_COMP_` (compound props), and `08_HERO_` (spotlights).

For example, **`01_BASE_All`** is a group of your props used for a
whole-display background effect. Its name can differ from your existing
"All Lights" group without indicating the wrong layout. The sequence
targets the generated name exactly; those definitions and their member
models must exist in the **selected show folder's layout XML**. Opening
the `.xsq` alone does not add them to your existing layout. Check member
model names to verify that a group contains your props.

### 8. Open, resolve dependencies, render, preview, and save

1. Launch xLights and use **File → Select Show Folder** to select the
   prepared folder from step 7. Check the **Layout** tab for your expected
   props and the generated Power Groups.
2. Use **File → Open Sequence** and select the extracted/copied
   **`song_AI.xsq`**.
3. If xLights asks for the music, browse to the **original recording you
   analyzed**. You may see a Docker path such as `/home/node/.xlight/...`
   that does not exist on your computer; replace it with the local music
   file. If no prompt appears but audio is missing, update the media file
   in the sequence settings.
4. Resolve missing-file warnings. Shader effects can reference paths such
   as `Shaders/Plasma Emitter.fs`; those `.fs` files are not supplied by
   this repository or the download. Obtain the matching shader through
   the Shader effect's **Download** control when available, or from its
   original source. Put it under `Shaders/` in the prepared show folder
   and select it in the affected effect's file picker. Relink any missing
   video, picture, face image, or other asset in the same way. If an asset
   is unavailable, replace or remove the affected effect in your generated
   sequence. See the [xLights Shader manual](https://manual.xlights.org/xlights/effects/off/shader).
5. Click **Render All** and wait for rendering to finish. Then play the
   sequence in **House Preview** and check the lights against the music.
6. Use **File → Save** (or **Save As** into the prepared show folder).
   Render again after changing effects or resolving missing files. xLights
   creates the rendered `.fseq` when you render and save; see the
   [xLights sequence settings](https://manual.xlights.org/xlights/chapters/chapter-five-menus/file/settings/sequences).

You have completed the workflow when your expected props light up in the
preview, the audio plays in sync, and the sequence is saved in the
prepared show folder.

#### If the preview does not work

| Symptom | Check |
|---------|-------|
| App cannot start because the host port is occupied | The default is `"54321:5000"`. If 54321 is occupied, choose another unused host port, such as `"54322:5000"`, run `docker compose up` again, and use the corresponding browser URL. |
| Export says **Theming Incomplete** | Return to Theme and confirm all sections with **Accept All Defaults**. |
| Layout contains somebody else's props | Replace the repo layout before generation, run `group-layout`, restart, refresh, and generate/download again. |
| Missing groups or effects on empty rows | Select the prepared show folder and confirm its `xlights_rgbeffects.xml` came from the same package as the sequence. |
| Music is missing | Relink the original local audio file; it is not in the package. |
| Missing shaders or other files | Install/relink the referenced assets, or replace the affected effects, then Render All again. |
| Effects exist but preview is blank or stale | Check group membership and preview selection, then Render All before playing. |

#### Updating

The footer of every screen shows `ui <commit> · built <date> · api <commit>` —
when either commit falls behind `main`, update like this:

```bash
git pull
docker compose exec xonset sh -c "cd src/review/frontend && npm run build"
docker compose restart
```

Then hard-refresh the browser (Ctrl+Shift+R). What each step covers:

- `git pull` — the app code runs from your checkout (bind-mounted into the
  container), so pulling is most of the update.
- The `npm run build` line rebuilds the web UI. Only needed when frontend
  files changed (`src/review/frontend/`), but it's fast and always safe —
  the container skips rebuilding it on startup whenever a built bundle
  already exists, so don't rely on a restart alone to pick up UI changes.
- `docker compose restart` — restarts the Python backend so pulled backend
  changes take effect (it doesn't hot-reload). Expect a couple of quiet
  minutes at `[1/5]` while pip re-checks dependencies.

Only if `.devcontainer/Dockerfile` itself changed (new system-level
dependency — rare) do you need a real rebuild: `docker compose up -d --build`.

#### Your data

Everything you upload or generate (song library, cached stems/analysis,
image library, custom themes) lives under `~/.xlight/` inside the
container, backed by named Docker volumes — it survives restarts,
recreates, and image rebuilds, and isn't tracked in git. To carry it to
another machine, `docker cp` it out of/into the `xlight-state` volume.

> **Contributors:** `.devcontainer/` also works as a VS Code Dev
> Container for interactive development inside the same toolchain image.
> Note it runs an outbound-traffic firewall on start (built for
> sandboxing an AI coding agent) — normal internet access outside its
> allowlist is blocked by design. See `scripts/startapp.sh` for
> restarting the server after backend changes.

---

## The screens

Use the [Quick Start](#quick-start) for the complete workflow. This section
is a reference for the seven web tabs: **Library → Import → Analyze →
Timeline → Theme → Extras → Export**. Package extraction and opening in
xLights follow Export, as described in steps 6–8 above.

### 1. Library — empty state

![Empty Library](assets/screenshots/01-library-empty.png)

Where you start the very first time.

1. **Tab bar** (top). Numbered steps; the active tab is underlined orange. You can revisit any tab at any time.
2. **Drop zone** (centered card). Drag an MP3 / WAV file — or a video file (mp4/mov/avi/mkv/webm), whose audio track is extracted automatically — onto it, or click *"or click to browse files"* to open a native file picker. Both mono and stereo audio are accepted; ID3 metadata is read automatically.

That's the entire screen — the app is deliberately empty here so the call to action is unmissable.

---

### 2. Analyze — pipeline running

![Analyze running](assets/screenshots/03-analyze-running.png)

After you drop a file, the app jumps straight to **Analyze** and starts the pipeline.

1. **Title bar** — *"Analyzing... `<slug>` · `<duration>`"* on the left, *"`<elapsed>` / ~`<eta>`"* and a **skip to timeline →** escape hatch on the right. The skip button shows up once enough has been detected to render *something* in the timeline.
2. **Artist / Title fields** — read from the MP3's ID3 tags. Edit either to override what's used for the synced-lyrics lookup.
3. **Phase pills** — seven logical phases (loading audio → separating stems → tracking beats → finding bars → segmenting structure → song story → assigning themes). The active phase is outlined; completed phases get a green checkmark.
4. **Detectors column** (left) — every algorithm the pipeline will run, in execution order. Each row shows status (queued / running / done), library tag (system, demucs, librosa, vamp, madmom), and progress.
5. **Stream column** (middle) — live SSE log lines from the pipeline. Mostly the same information as the Detectors column but in narrative form, with elapsed time per detector.
6. **Findings column** (right) — overall progress %, ETA, list of high-level outputs (waveform, beats, bars, sections, themes), and a live-growing **Sections** list as the structure detector finds boundaries.
7. **Song rail** (far left, collapsible). Songs you've imported, grouped by folder. Switch between songs by clicking; the right side switches to whichever song you pick.

---

### 3. Analyze — complete

![Analyze complete](assets/screenshots/04-analyze-complete.png)

Same screen, after the pipeline finishes (~60–90 s on a typical song with cached stems).

1. **Title bar** flips to *"Analysis complete"* with a prominent **▶ review timeline →** button on the right.
2. **All seven phases** show green checkmarks.
3. **Detectors** — full list (33 / 33 done), each with its detected mark count visible (e.g. `librosa_beats · 288`, `aubio_onset (drums) · 700 marks`).
4. **Stream** — the full progress log, scrollable.
5. **Findings** — 100 %, with per-category counts (`waveform ✓`, `beats 459`, `bars 80`, `sections 5`, `themes ✓`) and the actual section list with role + duration (`01 Verse · 20s`, `02 Pre Chorus · 19s`, ...).
6. **Re-analyze** button (bottom left) — re-runs the pipeline from scratch, ignoring any cache. Useful after a story-builder schema bump, or when you've edited the artist/title fields and want a fresh synced-lyrics lookup.

---

### 4. Timeline — review and adjust

![Timeline](assets/screenshots/05-timeline.png)

The most-used screen. Verifies the analysis matched what you hear.

1. **Transport** (top center) — ⏮ ▶ ⏭ play/scrub controls, current position / total duration.
2. **Zoom controls** — `−` / `+` buttons; reads as `1×`, `2×`, etc. Higher zoom narrows the visible window so you can scrub onto a single beat.
3. **Waveform** — full-mix audio rendered as a green stereo waveform, with a 0:00–total-duration time ruler underneath. Click anywhere on it to seek the playhead.
4. **Sections row** — colored boxes per detected section, labeled by role (Verse, Pre Chorus, Chorus, Bridge, Outro, Interlude, etc.). Click *"Edit sections"* (button on the right) to adjust boundaries by dragging.
5. **Section beat counter** — small dots showing the bar/beat structure within the currently-visible window.
6. **Stem waveforms** (collapsible) — drums / bass / vocals / guitar / piano / other waveforms stacked. Click *"click to load"* to render them; useful for verifying the stem separation looks right.
7. **Raw algorithm tracks** — every individual detector's output as a flash-when-the-event-passes tick row. Each row shows the algorithm name, the event count, and a sparkline. Toggle visibility per-row to declutter; the *"31 / 31 visible"* counter updates.
8. **AYHEAD inspector** (right column) — current playback position formatted as `bar X · beat Y of Z`.
9. **Current section** — name and color of whatever section the playhead is in right now. Updates as you scrub.
10. **Section timing** — start / end / duration of the current section.
11. **Nudge buttons** — `−10 ms` / `+10 ms` to micro-adjust the active section's start time. Hold-and-drag for repeated nudges.
12. **Go to Theme →** (bottom) — finishes timeline review and moves to the next step.

---

### 5. Theme — assign a look per section

![Theme](assets/screenshots/06-theme.png)

Pick a *theme* (composite lighting "look") for each section of the song. Themes encode color palette, effect choice, blend modes, and parameter mappings.

1. **Section navigator** (top) — every detected section as a clickable pill (Verse / Pre Chorus / Chorus / Verse / Outro). The active pill outlines orange; click to switch which section you're theming.
2. **Accept All Defaults** (top right) — auto-assigns theme defaults to every section using the song's energy/genre profile. Good starting point if you don't want to pick one-by-one.
3. **Theme grid** (center) — each card is one theme:
   - **Palette swatch** strip (5 colors) at the top.
   - **Theme name** (e.g. *Aurora*, *Inferno*, *Stellar Wind*).
   - **Mood tags** (e.g. ETHEREAL, AGGRESSIVE, ROCK, DARK) for quick filtering.
   - **One-line description** — what the theme evokes.
   Click a card to assign it to the active section.
4. **Section beat strip** (right of the grid) — visualizes the currently-selected section's beat structure, labeled with the section name.
5. **Section parameters** (right column) — four sliders that fine-tune *this section's* render of the chosen theme:
   - **Brightness** — global intensity (0 – 1)
   - **Hit Strength** — accent emphasis on beats (0 – 1)
   - **Dwell Time** — how long held effects last (0 – 1)
   - **Color Shift** — palette rotation (0 – 1)

Per-section overrides are remembered when you switch sections; the **Accept All Defaults** button resets them.

---

### 6. Extras — Pictures & Shadow Text words

Optional per-song lyric-word triggers for two effects: image accents on
Matrix/Mega Tree props (Pictures), and a two-layer drop-shadow word effect
(Shadow Text). Nothing here is required — skip straight to Export if you
don't want either.

- **Suggested topics** — lyric words from this song that don't have a
  matching image in your shared image library yet. Per word:
  - **Create image** — opens a pre-filled AI image-generation prompt you
    can copy into Gemini (or any image generator), styled to match the
    catalog's flat-icon look.
  - **Choose image** — upload an image file directly for this word.
  - **Shadow** — tags the word for the Shadow Text effect. Click again to
    untag (shows *Shadow ✓* while active).
  - A previously unmapped word shows an *"unmapped from `<file>`"* note
    and a **Restore match** button instead.
- **Already matched** — words already resolved to a library image, shown
  as `"word" → filename.png`. Same **Create image** / **Choose image** /
  **Shadow** buttons, plus **Unmap** — suppresses the Pictures effect for
  that word *in this song only* (the library image itself isn't deleted,
  and stays available for other songs).
- **Moving Head Triggers** — a separate list of lyric words that fire a
  Moving Head accent when sung, independent of Pictures/Shadow. Three
  built-ins (*shake*, *bounce*, *spin*) are on by default; uncheck
  (**Remove**) to disable one for this song. Add your own word either from
  the *"Add from this song's lyrics"* picker or the custom-word box at the
  bottom, assigning it one of four motions: **shake**, **bounce**,
  **spin**, or **flash** (points every head straight up at full white).

At generation time, **Pictures** cycles catalog images in as an overlay on
Matrix/Mega Tree props, timed to each lyric match, with a short pan and an
occasional zoom/rotation flourish. **Shadow Text** renders a tagged word
itself as two stacked layers on the same props whenever it's sung — the
word in the song's main palette color on top, a slightly offset copy in a
second palette color directly behind it — using the same pan/zoom/rotation
movement Pictures bursts use. Both are optional accents layered on top of
whatever the Theme tab already assigned.

---

### 7. Export — produce the .xsq

![Export — layout required](assets/screenshots/07-export.png)

The terminal step. Generates the xLights `.xsq` sequence from the analyzed song + assigned themes + the repo's committed prop layout.

- **Generate Sequence** — produces the `.xsq`.
- **Reference Layout** — identifies the layout loaded from `layout/xlights_rgbeffects.xml` and its prop count.
- **Include Onsets/Chords timing tracks** — controls whether those extra timing tracks are included.
- **Rerandomize** — generates a new variation with the same song and themes.
- **Download Package** — bundles the generated `.xsq` with the layout XML and, when present, networks XML into a `.xsqz` ZIP archive. Extract it and prepare the matching show folder using Quick Start steps 6–8.
- **Save Bundle** — downloads a JSON backup of the song's settings and extras for restoring in this app.

---

### 8. Library — populated state

![Library populated](assets/screenshots/08-library-populated.png)

Where you go to switch between songs once you've imported a few.

1. **Filter pills** (top) — *All / Draft / Analyzed / Themed*. Filters the song list by status. *Draft* = imported but not analyzed; *Analyzed* = pipeline complete; *Themed* = at least one section has a theme assignment.
2. **Folder groups** — songs are bucketed by `folder_id` (default `unfiled`). The count next to each folder name shows how many songs are in it. Click the chevron to collapse / expand.
3. **Song row** — each row shows title, artist (from ID3 or override), and a **status badge** (`Analyzed`, `Themed`, `Draft`). Click anywhere on the row to open it in whatever tab you visit next.
4. **Song rail** (far left) — a permanent compact list across every screen, so you can switch between songs without leaving the current step.

---

## Output Files

For the Docker/web workflow, **Download Package** is the deliverable:

```
song_AI.xsqz                   # ZIP archive saved by your browser
song_AI_export/                # After you extract it
├── song_AI.xsq                # Editable sequence
├── xlights_rgbeffects.xml     # Matching layout and Power Groups
└── xlights_networks.xml       # Controller configuration, if present
```

Uploads and analysis caches are stored inside the container under
`~/.xlight/`, backed by Docker volumes; they are not written alongside
the original file on your computer. Exported sequences are generated in
temporary storage, so download the package before restarting the server.
Use [Quick Start](#quick-start) steps 6–8 to extract, prepare the show
folder, locate music and dependencies, and render in xLights.

---

## Project Structure

```
src/
├── analyzer/               # Audio analysis pipeline
│   ├── audio.py            # MP3 loading via librosa
│   ├── result.py           # Data classes (TimingTrack, HierarchyResult, etc.)
│   ├── runner.py           # Orchestrates algorithm runs
│   ├── orchestrator.py     # Hierarchy assembly (L0-L6)
│   ├── scorer.py           # Quality scoring
│   ├── stems.py            # Demucs stem separation (6 stems)
│   ├── phonemes.py         # WhisperX phoneme analysis
│   ├── xtiming.py          # .xtiming XML writer
│   ├── xvc_export.py       # .xvc value curve writer
│   ├── pipeline.py         # End-to-end export pipeline
│   └── algorithms/         # 17 algorithm implementations (librosa, vamp, madmom, essentia)
├── grouper/                # xLights layout -> Power Groups
│   ├── layout.py           # Parse xlights_rgbeffects.xml
│   ├── classifier.py       # Normalize, classify, detect heroes
│   ├── grouper.py          # 8-tier group generation
│   └── writer.py           # Inject groups back into XML
├── effects/                # xLights effect catalog
│   ├── builtin_effects.json  # 35 effect definitions
│   ├── models.py           # EffectDefinition, EffectParameter, AnalysisMapping
│   └── library.py          # Load, query effects
├── variants/               # Pre-tuned effect presets
│   ├── builtins/           # 34 per-effect JSON files (123+ variants)
│   ├── models.py           # EffectVariant, VariantTags
│   ├── library.py          # Load, query, save custom variants
│   ├── scorer.py           # Context-aware variant scoring
│   └── importer.py         # Import variants from .xsq files
├── themes/                 # Composite effect themes
│   ├── builtin_themes.json # 21 theme definitions
│   ├── models.py           # Theme, EffectLayer (with variant_ref)
│   └── library.py          # Load, query by mood/occasion/genre
├── story/                  # Song story builder
│   ├── models.py           # SongStory, Section, Moment, MoodCurve
│   ├── builder.py          # Build story from hierarchy + lyric-anchored refinement
│   ├── section_classifier.py # Detect verse/chorus/bridge/etc.
│   ├── energy_arc.py       # Energy curve computation
│   └── lighting_mapper.py  # Map story to lighting cues
├── generator/              # Sequence generation
│   ├── models.py           # GeneratorConfig, SequencePlan, EffectPlacement
│   ├── plan.py             # Generate effect placement plan
│   ├── theme_selector.py   # Theme selection by mood/occasion
│   ├── effect_placer.py    # Place effects on props (resolves variant_ref)
│   ├── value_curves.py     # Dynamic parameter changes
│   └── xsq_writer.py      # Write .xsq sequence XML
├── review/                 # Web UI
│   ├── server.py           # Flask app (dashboard, upload, timeline, export)
│   ├── theme_routes.py     # Theme CRUD API + editor page
│   ├── variant_routes.py   # Variant library API + browser page
│   ├── story_routes.py     # Story review API
│   └── frontend/           # React/TypeScript web UI (npm run build)
├── cli/                    # Click CLI entry point and command modules
├── cache.py                # MD5-keyed analysis cache
├── library.py              # ~/.xlight/library.json song index
└── export.py               # JSON serialization
```

---

## User Data

| Path | Contents |
|------|----------|
| `~/.xlight/library/library.json` | Web song library index |
| `~/.xlight/library/songs/<song_id>/` | Uploaded audio and per-song session/analysis data |
| `~/.xlight/custom_themes/*.json` | Custom theme overrides |
| `~/.xlight/custom_variants/*.json` | Custom effect variants |
| `~/.xlight/sweep_configs/` | Parameter sweep configs |
| `.stems/<md5>/` | Cached stem separation output (adjacent to source audio) |

---

## Known Issues

| Issue | Fix |
|-------|-----|
| `TorchCodec is required` warning | Harmless — can be ignored |
| Stem separation slow on first run | Normal — demucs downloads ~200 MB model. Cached after first run. |
| whisperx alignment model fails | `docker compose exec xonset sh -c "pip install huggingface_hub && huggingface-cli login"` |

---

## Running Tests

```bash
docker compose exec xonset pytest tests/ -v
```

---

## Documentation

Detailed docs for each subsystem are in [`docs/`](docs/README.md).

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
