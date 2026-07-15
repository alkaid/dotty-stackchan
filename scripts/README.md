# Scripts

Developer tooling. The singing-mode scripts below produce the WAV files that `_handle_dance()` injects into the TTS queue; none of them run in the live audio path.

## UAT session tooling

Companions to [`docs/uat-runbook.md`](../docs/uat-runbook.md):

- **`uat-capture.sh start|stop [--dry-run]`** — tails the four service containers into `uat-sessions/<date>/logs/`, then on stop pulls the day's NDJSON logs out of the containers and snapshots the health/perception endpoints. Needs `XIAOZHI_SSH=user@host`.
- **`uat-slice.py`** — cuts the phone/screen recordings into per-check clips from the session results CSV, using the on-camera sync mark to align wall-clock and video time. PASS clips → `clips/shorts/`, the rest → `clips/issues/`. Requires `ffmpeg`.

## render_singing_piper.py — Phase 1: Quick prototype

Synthesizes the Macarena vocal track using the existing Piper TTS model with per-phrase pitch + speed manipulation. Produces "charming pitched speech," not real singing — fast to iterate on, no new dependencies.

This is a workstation-only asset generator, not part of the live deployment
path. Install its Python dependencies in a local venv, then run:

```bash
python scripts/render_singing_piper.py
docker compose up -d --build xiaozhi-esp32-server
```

The output is written to `songs/macarena.wav`. The root Dockerfile copies the
whole `songs/` directory into the xiaozhi image, so no runtime copy or source
mount is required.

Edit the `PHRASES` list in the script to tweak lyrics, pitch, or timing.

## postprocess_song.py — Phase 2: DiffSinger normalizer

Takes a high-quality singing render from DiffSinger / OpenUtau / NNSVS / VISinger2 and normalizes it to the 24 kHz mono int16 WAV format the device expects. Does the dirty work of resampling, downmixing, and beat-aligned trimming.

```
python scripts/postprocess_song.py input.wav songs/macarena.wav --duration-ms 27936
```

The `27936` ms target matches the choreography duration (`BEAT_MS=582 * 48 beats`). Drop the flag to skip duration fitting.

### DiffSinger authoring workflow (Phase 2)

1. **Install OpenUtau** on the workstation — Linux AppImage from https://www.openutau.com/ or build from source.

2. **Install a DiffSinger English voice bank** (search HuggingFace for `DiffSinger English` — community-trained banks for Miku, Tiger, Cori, etc.). Drop the voicebank folder into OpenUtau's `Singers/` directory.

3. **Author the Macarena project**:
   - Open OpenUtau, set BPM to **103** (matches `BEAT_MS=582`).
   - Import a public-domain Macarena MIDI (BitMidi, MidiWorld) — main melody track only.
   - Switch to the DiffSinger voice bank for the track.
   - Type lyrics syllable-by-syllable on the piano roll. Use `+` for sustains.
   - Export → "Render to file" → WAV (44.1 kHz or 48 kHz mono, doesn't matter — postprocess will normalize).

4. **Normalize and rebuild**:
   ```
   python scripts/postprocess_song.py macarena_diffsinger.wav songs/macarena.wav --duration-ms 27936
   docker compose up -d --build xiaozhi-esp32-server
   ```

5. **Test**: trigger "do the macarena" with the device after the rebuilt
   container is healthy.

### Optional: backing track

Open a Macarena instrumental MIDI in any DAW (Reaper, LMMS) and render to WAV. Mix 70% vocal / 30% backing in your DAW or Audacity, then run that mixdown through `postprocess_song.py`. Avoid using copyrighted instrumental recordings — render from MIDI to keep it safe.
