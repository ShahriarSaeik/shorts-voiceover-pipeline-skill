# Branch B: Colab T4 + Practical-RIFE run procedure

Use for every render that is not Branch A. Deeper background and fixes: `references/colab-gpu-pipeline.md` (Real-ESRGAN, Python 3.13 fixes, OOM caps) and `references/detached-colab-supervision.md` (checking a worker that looks idle).

## colab-cli syntax (exact)

- New session: `colab new -s <S> --gpu T4`. Never use a bare `--gpu` or `--session-name`.
- Stop: `colab stop -s <S>`. Always pass `-s`.
- Upload: `colab upload <LOCAL> <REMOTE> -s <S>`. Download: `colab download <REMOTE> <LOCAL> -s <S>`.
- Run code: `colab exec -s <S> -f <LOCAL_FILE.py> --timeout <SECONDS>`. `-f` takes a local VPS path (a `/content/...` path fails with FileNotFoundError), and `-c` does not exist. The file is sent as a Python cell, so write steps as a `.py` that calls `subprocess.run([...], check=True)` with an argument list.
- Always set `--timeout`: the default is 30 s. A timeout or WebSocket disconnect does not prove the remote work stopped; check the remote PID, status and log before retrying.
- A `503 Service Unavailable` is usually an account cooldown. Use another account profile: `HOME=/home/ubuntu/.config/colab-accounts/account_<N> colab <command>`.
- Free GPU quota is small (about 4-6 h per rolling 24 h). Stop the session as soon as the job ends or fails, then confirm with `colab sessions` that none is active.

## Steps

1. **Plan and configure.** Run `python3 scripts/preflight.py --video SRC --voiceover VO --job-dir <JOB>`. It writes `<JOB>/plan.json` and `<JOB>/colab_rife_worker.py` with VO_DUR, VID_DUR, SRC_FRAMES, SRC_FPS and CQ filled in and py_compiled. If it exits 2, stop and ask the user.
2. **Normalize the voiceover** to `<JOB>/vo_norm.wav` (render-spec section 1) and measure it. Continue only when it reads -14.0 LUFS with true peak below -1.5.
3. **Make `src.mp4` video-only:** `ffmpeg -i <SOURCE> -map 0:v:0 -c copy -an <JOB>/src.mp4`. This keeps cover-art streams and source audio out of RIFE.
4. **Write `<JOB>/meta.json`** with only the keys `title`, `description` and `copyright`, in Hindi from the user's transcript (render-spec section 5). Then run `python3 scripts/check_meta.py <JOB>/meta.json`. Do not go on until it prints `RESULT PASS`; fix each FAIL line and rerun.
5. **Start the session and upload:** `colab new -s <S> --gpu T4`, then upload `src.mp4`, `vo_norm.wav`, `meta.json`, and the configured worker as `/content/colab_rife_worker.py`.
6. **Launch the worker detached:** `colab exec -s <S> -f scripts/colab_launch.py --timeout 60`.
7. **Poll every ~30 s:** `colab exec -s <S> -f scripts/colab_check.py --timeout 30 | grep -o '"stage": "[A-Za-z_]*"' | tail -1`. The RIFE progress bar floods the log, so read only the stage. Stages: setup, rife, rife_done, render, verify, then DONE or FAILED. Report the stage you observed. A live PID alone is not completion. Every `colab` call prints an update-check banner; append `2>&1 | grep -v -E 'new version|colab update|silence this'` so the output stays readable. Wrap each poll in `timeout 60` so a hung call cannot stall the turn. Expect about 7 minutes end to end for a 28 s, 30 fps source (RIFE about 3 min, render and verify about 3 min); it scales with frame count, so poll at the same pace and do not relaunch.
8. **On FAILED:** read the printed RIFE log tail, fix the cause, re-upload the worker, and relaunch (it uses a fresh `rife_<ts>` directory). Never start a second writer while the first is alive.
9. **On DONE:** download `/content/run_short/master.mp4` to a local `.part` file and `/content/run_short/encoder_cmd.txt`. Stop the session and confirm `colab sessions` shows none. Compare size and sha256 with the DONE record in `status.json`.
10. **Verify** with `references/verify_short_master.py` (see SKILL.md, Step 4). Load the exact metadata strings from `meta.json` instead of retyping them: write `T=...`, `D=...`, `C=...` lines with `python3 -c "import json,shlex;m=json.load(open('<JOB>/meta.json',encoding='utf-8'));print('T=%s\nD=%s\nC=%s'%tuple(shlex.quote(m[k]) for k in ('title','description','copyright')))" > <JOB>/args.sh`, run `. <JOB>/args.sh`, then pass `--expect-title "$T" --expect-description "$D" --expect-copyright "$C"`. If only loudness fails, remux per render-spec section 6.
11. **Deliver:** rename the `.part` to the final name only after every check passes, then copy it to `/home/ubuntu/Downloads/<name>.mp4`.

To look at frames with `view_image`, write them under `/home/ubuntu/.openclaw/workspace/`; other paths are rejected.

## RIFE facts the worker already handles

- Frame interpolation is Practical-RIFE `inference_video.py`; ffmpeg has no `rife` filter. A plain ffmpeg setpts + NVENC run at 30 fps is not this branch.
- `exp` is the smallest value with `(source_fps / F) x 2^exp >= 60` (`preflight.py` prints it).
- If an input side is not a multiple of 64, pad only the RIFE input and crop the padding back out before the final scale; the deliverable must show no padding.
- Intermediate frames stay on Colab. Only the source, the normalized voiceover and the finished master cross the network.
