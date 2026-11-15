# Render spec (both branches)

Read this when a step in SKILL.md points here. Each rule has one place; SKILL.md only links to it.

## 1. Voiceover audio

1. If the voiceover is MP3 or not 48 kHz PCM, convert it first: `ffmpeg -y -i vo.mp3 -ar 48000 -ac 2 -c:a pcm_s16le vo.wav`. (`preflight.py` reports `needs_48k_wav_conversion`.)
2. Normalize with two-pass loudnorm to `vo_norm.wav` (48 kHz stereo). Pass 1: `-af loudnorm=I=-14:TP=-1.5:LRA=7:print_format=json -f null -`. Pass 2: the same filter plus `measured_I`, `measured_TP`, `measured_LRA`, `measured_thresh`, `offset`, `linear=true`.
3. Measure `vo_norm.wav` again with pass 1. The master's loudness equals this file's, and two-pass loudnorm can land near -14.7, which fails the verifier. If `input_i` is more than 0.3 LUFS from -14, re-encode with `-af volume=<-14 minus input_i>dB`, measure again, and repeat until `input_i` reads -14.0 and `input_tp` is below -1.5. Upload only after this passes.
4. Keep background or reaction audio only when the user asks. Separate stems with Demucs, time-stretch the instrumental by 1/F, and place reaction segments at original timestamp x F. Mix the background at about 0.35-0.40 under the narration.

## 2. Video chain

- Speed: `setpts=F*PTS` with `F = voiceover duration / video-stream duration`. Take the video duration from the video stream, because `format=duration` can follow the audio stream and skew F.
- Order of filters: `hqdn3d=1.5:1.5:3:3` (only when source noise is visible) -> scale -> `unsharp=3:3:0.15:3:3:0.0` -> `eq=saturation=1.05:contrast=1.02` -> watermark `drawtext` -> `format=yuv420p`. Avoid stronger sharpening or grading.
- Scale: 4K-class sources keep their exact width and height, with no scale, crop, or pad. Every other source goes to exactly 1440x2560 with `scale=1440:2560:flags=spline`. Never pad.
- Source below 1080p: spline scaling is the default. Use Real-ESRGAN only if a side-by-side of representative frames shows a clear gain, and the runtime is acceptable (see `references/colab-gpu-pipeline.md`).
- Non-9:16 source: look at one frame after scaling and make sure nothing important is cut off.
- Colour tags: `-color_primaries bt709 -color_trc bt709 -colorspace bt709`.

## 3. Watermark

- Text `@IshaniFact`, font `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`, white.
- `fontsize=46` at 1440x2560; scale proportionally for other sizes (69 at 2160x3840).
- Shadow only: `shadowcolor=black@0.6:shadowx=2:shadowy=2`. Never set `box=1` or `boxcolor`; no box, blur patch, or dark rectangle.
- Position: `x=(w-text_w)/2:y=h-360`. Do not move it to avoid subtitles unless the user says the subtitles sit at the bottom.

## 4. Encoders

- Branch A (local, 4K-class only, F <= 1): `libx264 -preset medium -crf 16 -threads 2 -pix_fmt yuv420p`, AAC 320 kbps, 48 kHz, stereo. Do not use `veryfast`.
- Branch B (Colab T4): `h264_nvenc -preset p4 -cq 22 -b:v 0 -pix_fmt yuv420p`. Use CQ 18 only when the user asks for higher quality or accepts a bigger file. Record the CQ used and pass it to the verifier as `--expect-cq`. Never use libx264 on Colab.
- Final frame rate on Branch B is exactly 60/1. A 30/1 result means RIFE did not run.

## 5. Metadata (always Hindi)

The user supplies the Hindi transcript of the voiceover. Write all metadata from that transcript. If it is missing, ask for it; do not translate from another language or invent facts. If the transcript ends mid-sentence or is clearly shorter than the voiceover, tell the user and ask for the rest instead of finishing the story yourself; do not add claims or calls to action that the transcript does not contain.

- `title`: pure Hindi, with relevant `#Shorts`.
- `description`: 150-250 Hindi words, plus relevant English search terms, plus 3-5 relevant hashtags.
- `artist`: `@IshaniFact`.
- `copyright`: current year.
- Do not add comment or genre tags, and do not add unsupported facts.
- For Branch B write `meta.json` with exactly these three keys and no others: `{"title": ..., "description": ..., "copyright": ...}` (UTF-8). Do not add the transcript or any other key.
- Description layout: the Hindi paragraph(s) first, then one line of English search terms, then the hashtags last. Write every Hindi word completely in Devanagari; never mix Latin letters into a Hindi word.
- Example description shape:
  `<150-250 Hindi words, from the transcript>`
  `English search terms: father daughter first period, parenting tips, puberty education, family support`
  `#Shorts #पिता #बेटी #परिवार`
- Check it before upload: `python3 scripts/check_meta.py <JOB>/meta.json`. It must print `RESULT PASS`. Fix every FAIL line and run it again.

## 6. Integrity failure and salvage

If a render or downloaded MP4 fails `ffprobe` (for example `moov atom not found`), do not deliver it. Its filename, size, or partial playback prove nothing. Keep it as a failed artifact.

1. Check the source master on its own: `ffmpeg -v error -i <SOURCE> -f null -`.
2. If the video is valid and only audio loudness or container settings are wrong, create a new file: `-map 0:v:0 -map 1:a:0 -map_metadata 0 -c:v copy -af volume=<-14 minus measured LUFS>dB -c:a aac -b:a 320k -ar 48000 -t <VO duration> -movflags +faststart`. Re-running loudnorm can repeat the same -14.7 result, so use the volume gain.
3. Run full `ffprobe`, a full decode, and a loudness measurement on the new file.
4. Report the branch actually used. A local remux does not fix a failed remote render.
5. If the video itself is invalid, go back to the last verified step. Never remux or deliver corrupt video.
