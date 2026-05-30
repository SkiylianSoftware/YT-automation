# API
## Calendar
[x] Auth
[ ] Create
[x] Read
[ ] Update
[ ] Delete
[ ] Synch
[ ] fetch_events

## YouTube
[ ] Auth
[ ] fetch playlist
[ ] fetch public
[ ] fetch private
[ ] fetch scheduled

## Re-Auth
[ ] Auth Calendar
[ ] Auth YouTube

## All
[ ] Runs Calendar
[ ] Runs YouTube

# Automation
## Calendar
[ ] fetch video event
[ ] create video event
[ ] delete video event
[ ] update video event
[ ] 'move' from one calendar to another

## Playlist
[x] Acronym generator
[x] Video mapping
[x] Playlist mapping
[ ] Move videos

# Shotcut Parser (`shotcut.py`)
## Load / Parse
[x] Parse profile
[x] Parse assets (main_bin chains/producers)
[x] Parse timeline tracks (playlists → chain/producer entries)
[x] Parse transitions (tractor entries)
[x] Parse markers (hh:mm:ss.ms and hh:mm:ss:ff SMPTE)
[x] Handle missing main tractor (fallback to first)
[x] Handle both `chain` and `producer` prefixed entries
[x] Handle timewarp speed clips (`producer0` with SPEED:resource format)
[x] Handle duplicate chain IDs (non-fatal skip)
[-] Filters not yet parsed from XML

## Save / Write
[x] Write assets
[x] Write chains
[x] Write playlists
[x] Write transitions
[x] Write markers
[x] Write blend transitions
[x] Prune unused chains/tractors/playlists/markers
[x] Defragment chain/playlist/marker IDs
[x] Multiple saves produce identical output

## API methods
[x] `create_track` / `get_or_create_track`
[x] `split_clip` / `cut_from_clip` / `cut_from_track`
[x] `remove_time` / `insert_time` / `remove_clip`
[x] `condense_clips`
[x] `add_clip_to_track` / `clear_track`
[x] `find_assets_by_path`
[x] `get_track` / `track_by_name`

## Known bugs
[ ] `_collect_block` list.index() fails on mutated objects after split
[ ] `condense_clips` shifts clips by framerate quantization gaps

# Shotcut Transitions (`shotcut_transitions.py`)
[x] All 22 named luma types (BarHorizontal..ClockTop) — resource constant, to_xml, round-trip, index preservation
[x] Dissolve (no resource)
[x] Cut (color format `#RRGGBB`, 0..1 cut value, clamp)
[x] Custom transition (validate=false for load, factory round-trip)
[x] AudioTransition (cross-fade, mix-fraction, clamp, blanks, from_xml with no start)
[x] VideoTransitionBase — default values, common properties, softness, factory round-trip
[x] Produce resource map — all entries map to named types, all luma files covered, dissolve/cut not in map
[x] Parse time format round-trip
[x] Handle `producer` prefix in transition track references (not just `chain`)

# Shotcut Effects (`shotcut_effects.py`)
[x] Brightness — to_xml, round-trip, clamp
[x] ColourGrading — to_xml gain, round-trip, dispatch via SERVICE_MAP, clamp values
[x] Contrast — to_xml, round-trip, dispatch via FILTER_MAP, non-uniform gain
[x] FadeInAudio — all 4 curve types, shorter-than-clip, anim in property
[x] FadeOutAudio — all 4 curve types, anim out property
[x] Gain — round-trip, dispatch, default level
[x] Mute — round-trip, dispatch
[x] FadeInVideo — round-trip, dispatch, keyframed level
[x] FadeOutVideo — round-trip, dispatch, keyframed level
[x] Opacity — round-trip, dispatch, opacity property, default
[x] SizePositionRotate — round-trip, dispatch, defaults
[x] RichText — round-trip, dispatch, empty html
[x] Typewriter — round-trip, dispatch
[x] Timer — round-trip, dispatch, defaults
[x] WhiteBalance — round-trip, dispatch via SERVICE_MAP, defaults, property names
[x] FILTER_MAP + SERVICE_MAP — all classes exist, no duplicates, complete
[x] Edge cases — ColourGrading crash bug, from_xml without mlt_service, no shotcut filter property
[x] Filter dispatch — unknown service falls back to generic Filter

# Silence Pipeline (`silence.py`)
[x] Silence detection via ffmpeg silencedetect
[x] Speech transcription via Whisper (lazy import)
[x] Filler word detection (`um`, `uh`, etc.)
[x] Self-repair detection (word-filler-word pattern)
[x] Region merging with padding
[x] Track-level silence region mapping
[x] Timeline cut region calculation
[x] Apply cuts to Shotcut model

# Background Music (`background_music.py`)
[x] Song discovery from project assets (filter by music dir)
[x] Marker reading from Shotcut timeline
[x] Song bin packing algorithm
[x] Song insertion timing
[x] Gain filter creation
[x] Audio/video blend recombination
[x] Integration with Shotcut object API

# Real-Project Round-Trip
[x] Load real .mlt files from ~/Videos/Projects (84% success rate)
[x] Save to temp file without crash
[x] Reload and verify structural integrity
[x] Consecutive saves produce identical XML

# Coverage
[x] `shotcut_effects.py`: 100%
[x] `shotcut_transitions.py`: 98%
[ ] `shotcut.py`: 63% (write/prune/defragment paths untested)
[ ] `background_music.py`: 22% (song-placement logic under-tested)
