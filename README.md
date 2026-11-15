# shorts-voiceover-pipeline

An OpenClaw skill for putting a custom voiceover on a vertical Short and producing a verified master.

- Probes the source and voiceover, then picks the render branch (`scripts/preflight.py`).
- Renders on a Google Colab T4 with Practical-RIFE (60 fps, 1440x2560), or locally for native 4K sources.
- Checks Hindi metadata (`scripts/check_meta.py`) and verifies the final file (`references/verify_short_master.py`).

Start with [`SKILL.md`](SKILL.md). Details live in `references/`.

Notes:
- Paths such as `/home/ubuntu/...` and the `@IshaniFact` watermark are the author's setup; change them for your own.
- Needs `ffmpeg`/`ffprobe`, `python3`, and `colab-cli` with a Google account that has T4 access.
- No license is set yet; all rights reserved by the author until one is added.
