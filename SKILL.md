---
name: "shorts-voiceover-pipeline"
description: "Use when adding a voiceover to a Short/vertical video, or downloading+transcribing a video link. Renders and verifies a 60 fps (or native 4K) master."
---

# Shorts Voiceover Pipeline

Follow the steps in order. Do the work in the same turn it is requested and report only what you observed (command output, stage, file probe); never say "in progress" for something you have not launched.

## Fixed decisions (do not re-ask)

- Metadata is always Hindi, written from the Hindi voiceover transcript the user supplies. No transcript: ask for it.
- The VPS has no GPU. Every render goes to Colab T4 + Practical-RIFE except a native 4K-class source that is not slowed down.
- Never attach the video in a chat channel (it gets compressed). Give the absolute local path.
- Never overwrite the source. Write to a new file and promote it only after every check below passes.

## Files in this skill

- `scripts/preflight.py`: probes both files, picks the branch, computes F and the RIFE exp, fills the Colab worker config.
- `references/render-spec.md`: audio, filters, watermark, encoders, Hindi metadata, salvage.
- `references/colab-run.md`: exact `colab-cli` commands and the numbered Colab procedure.
- `references/verify_short_master.py`: final checker.
- `references/colab-gpu-pipeline.md`, `references/detached-colab-supervision.md`: read only when a Colab stage fails or looks stuck. `references/external-gpu-access-and-supervision.md`: only for Kaggle.

## Step 1. Get the source (only when the user gives a link)

1. YouTube: use the `youtube-downloader` skill for all yt-dlp settings and recovery.
2. TikTok: resolve the short URL to the canonical video and take the highest quality (`hdplay`; `play` only if `hdplay` is absent).
3. Transcript of the source video, only if asked: `ffmpeg -i SRC -vn -ac 1 -ar 16000 /tmp/a.wav`, then `/home/linuxbrew/.linuxbrew/bin/whisper /tmp/a.wav --model base --output_format txt --output_dir /tmp`. Deliver it as plain continuous text with no timestamps unless timestamps are requested.

## Step 2. Plan (never skip, never guess from filenames)

```bash
python3 scripts/preflight.py --video SRC.mp4 --voiceover VO.wav --job-dir /home/ubuntu/jobs/<name>
```

Read the JSON. State the `branch`, `F`, `expected_output` and `encoder` to the user before any render command.

- Exit code 2 or a non-empty `stop_and_ask`: stop and ask the user.
- `needs_48k_wav_conversion` is true: convert the voiceover first (render-spec section 1).
- `warnings` are things to handle in the render, not to ignore.

## Step 3. Render

- `branch` = `B_colab_t4_rife` (the normal case): follow `references/colab-run.md` from step 2 to the end. Apply `references/render-spec.md` for audio, metadata and encoder values.
- `branch` = `A_local_4k`: native dimensions, no scale/crop/pad. Build the command from `references/render-spec.md` sections 1-5 (libx264 preset medium, CRF 16, 2 threads). Do not use `veryfast`.
- Background or reaction audio: only when requested; see render-spec section 1.

## Step 4. Verify (required before reporting done)

Run the checker on the finished file (Colab renders: pass the downloaded `.part` and the `encoder_cmd.txt` text):

```bash
python3 references/verify_short_master.py <file> --expect-duration <VO seconds> \
  --expect-title "<title>" --expect-description "<description>" --expect-copyright "<copyright>" \
  --encoder-command "$(cat encoder_cmd.txt)" --expect-cq <CQ used> --report report.json \
  [--expected-sha256 <hash> --expected-size <bytes>]
```

For a native 4K Branch A file also pass `--expect-width/--expect-height` equal to the source and `--expect-fps` equal to the source rate.

Then do these by hand:

1. `ffmpeg -v error -i <file> -f null -` finishes with no output.
2. Look at three frames (start, middle, end) for black bars, padding, cut-off content, a clean floating watermark with no box, and encode defects. Save the frames under `/home/ubuntu/.openclaw/workspace/` so `view_image` can open them, then move that frames folder to `~/.local/share/Trash/files/` once you have looked, because the daily backup commits the whole workspace.
3. Colab renders must show `r_frame_rate=60/1`. 30/1 means RIFE did not run: do not call it finished.
4. Check `colab sessions` shows no active session.

## Step 5. Report

Give the absolute output path, the branch used, resolution, duration, codecs, the CQ, the loudness reading, and every check that was skipped or failed. Never state an unverified check as passed. If a check failed, say which one and keep the failed file out of Downloads.

If the file is corrupt or only loudness failed, use the salvage steps in `references/render-spec.md` section 6 and report which branch actually produced the file.
