# Colab GPU Shorts Enhancement & End-to-End Master Render Reference

This guide details how to leverage the Google Colab T4 GPU (16GB VRAM) via `colab-cli` for heavy compute tasks in the Shorts Voiceover Pipeline:
1. **AI Video Upscaling & Super-Resolution** (Real-ESRGAN / Compact)
2. **AI Frame Interpolation & Smooth 60 FPS** (Practical-RIFE)
3. **End-to-End Master Rendering inside Colab** (zero intermediate file transfer, GPU-accelerated encoding)

---

## 1. Core Architecture & Session Rules

- **Orchestrator:** Oracle Cloud VPS (ARM64 CPU, headless, runs `colab-cli`).
- **Worker:** Google Colab VM with Nvidia T4 GPU (free tier runtime).
- **Multi-Account Profile Isolation:**
  - `colab-cli` caches credentials at `~/.config/colab-cli/token.json`.
  - To support multiple Google accounts without clobbering credentials, isolate each account's home:
    `HOME=/home/ubuntu/.config/colab-accounts/account_<N> colab <command>`
  - When an account hits `503 Service Unavailable`, it frequently indicates a rolling usage cooldown on that specific account. Switching to a fresh/idle account profile (`account_2`, `account_3`) often secures an immediate T4 assignment.
- **Quota Safety Rule:** Free GPU quota is strictly capped (~4-6 hours per rolling 24h). 
  - **Always** terminate the session immediately upon task completion or failure:
    ```bash
    colab stop -s <SESSION_NAME>
    ```
  - Verify with `colab sessions` that no hanging sessions remain.

### Long-Running Execution, Transfer, and Recovery (Verified with CLI v0.7.5)

**Root cause found:** `colab exec` defaults to a 30-second timeout. A Jupyter execution can continue remotely after the local CLI times out or loses its WebSocket; the error is not proof that the render stopped. Re-running the stage, downloading immediately, or stopping the VM at that point can race the original render and produce an incomplete MP4 (e.g. `moov atom not found`). A controlled T4 test confirmed a 35-second quiet interval succeeds with explicit `--timeout 120`; NVENC output and download also passed hash and full-decode checks.

1. **Set the timeout explicitly on every exec call.** Use a measured ceiling, such as `--timeout 1800` for bounded AI/render stages; do not treat a timeout as job cancellation.
2. **Make long stages independently observable.** Launch the remote stage as a detached subprocess with `start_new_session=True`, `stdin=DEVNULL`, and stdout/stderr redirected to a per-run log. Save its PID, unique run ID, start time, and output path/status. Poll with short, separate `colab exec` calls. Never launch a second writer for the same output.
3. **Publish the remote output atomically.** Render to a unique `.partial.mp4`; wait for process exit code 0; run remote `ffprobe` and a full decode; check required streams, resolution, FPS, duration, and nonzero size; compute SHA-256. Only then atomically rename to the completed remote filename and write a `DONE` record. On any failure write a failure record and preserve logs.
4. **Gate download on `DONE`.** Require the remote record to contain byte size and SHA-256. Download to a unique local `.part` path, never the final filename; immediately stop the session and verify `colab sessions` shows no active session. Then compare local size/hash with the record and run local `ffprobe` plus full `ffmpeg -v error -i <PART> -f null -`. Promote with atomic rename only if every check passes. Missing `moov`, hash mismatch, missing streams, or decode error means preserve as failed and do not deliver.
5. **Recover without racing.** After timeout/disconnect, query the run record, PID, and log. If it is still active, keep polling; if it exited, inspect its exit code and outputs. Retry only after proving the prior writer stopped and use a new output path/run ID.
6. **Always tear down.** On failure, stop the session only after stopping/confirming no remote writer remains; verify `colab sessions` shows no active session. If teardown fails, report it and keep checking status rather than claiming cleanup.

Keep the steps modular; use NVENC on T4, and do not transfer intermediate frames to the VPS.

### colab-cli Exact Syntax Reference
- `colab new -s <SESSION_NAME> --gpu T4` (never bare `--gpu` or `--session-name`).
- `colab stop -s <SESSION_NAME>` (always pass `-s`; positional argument fails).
- `colab upload <LOCAL_PATH> <REMOTE_PATH> -s <SESSION_NAME>`
- `colab download <REMOTE_PATH> <LOCAL_PATH> -s <SESSION_NAME>`
- `colab exec -s <SESSION_NAME> -f <LOCAL_FILE_PATH> [--timeout <SECONDS>]`
  - `-f` accepts a file located on the local VPS; the CLI reads it locally and transmits it to the remote Colab kernel. Do not pass remote `/content/...` paths or `-` to `-f`.
  - `-c` flag does not exist in `colab exec`. Run shell/system tasks via Python `subprocess.run(...)` or `os.system(...)` in a script file.
  - After a hang, inspect the remote PID, status, and log first. Restart the kernel only after confirming no render is actively writing; use `colab restart-kernel -s <SESSION_NAME>`.

---


## 2. T4 Runtime Fixes and Mandatory Verification Gates

Apply these observed safeguards before running any Colab render stage:

1. Resolve Python modules with `site.getsitepackages()[0]`; do not build paths from `sys.prefix` (on the observed Python 3.13 runtime, `sys.prefix=/usr` while packages live under `/usr/local/lib/python3.13/dist-packages`). Verify imports after copying modules.
1b. After running `pip install` in a Jupyter kernel cell, newly installed packages may not be importable until the kernel is restarted. Run the setup script (cloning, pip install, patching) in one `colab exec` call, then `colab restart-kernel -s <SESSION>`, then verify imports in a separate `colab exec` call before starting any render stage. Installed packages and cloned repos survive the kernel restart because they live on disk.
2. Run `python3 -m py_compile <LOCAL_RUNNER.py>` before upload/execute. A syntax error in the runner previously failed before work began and left misleading partial job state.
3. On T4, omit Real-ESRGAN's `--fp32` unless specifically required. The CLI's `--fp32` flag selects full precision; default is half precision. Benchmark a short representative sample first and record elapsed seconds, frames/second, GPU, and output probe before starting the full source.
4. Real-ESRGAN's stock `Writer` hard-codes `libx264` in both branches. Before running it on T4, back up `inference_realesrgan_video.py`, assert exactly two expected occurrences, and patch both writer branches to `h264_nvenc` with the selected T4 quality setting (`preset=p4,cq=22,b=0,pix_fmt=yuv420p` by default; CQ18 only when higher quality is justified). Compile the patched source and inspect the actual FFmpeg process command; require `h264_nvenc` before accepting the run.
5. Practical-RIFE's stock video writer uses OpenCV `mp4v`, not NVENC. To avoid intermediate CPU encoding, run RIFE with `--png --fp16` in a clean isolated working directory, then encode its numbered PNG sequence with final FFmpeg NVENC. Keep frames in Colab only.
6. RIFE's stock `read_buffer` and `write_buffer` each use `Queue(maxsize=500)`. At 1440×2560, full-resolution arrays can fill the 11.78 GiB Colab cgroup and OOM-kill Python. Before PNG mode, back up `inference_video.py`, assert one occurrence of each queue declaration, cap both at `8`, and run `python3 -m py_compile`. Use a unique run directory; monitor RAM/PNG count and preserve failed runs.
7. Keep a detached PID, unique run ID, status JSON, and log for every long stage. A live PID is not completion. Do not probe/promote/download until the process has exited and the completion record says `DONE`.

### Fail-closed verification checker

For each final master, record a JSON report and require every gate to pass:

- Output is non-empty; `ffprobe` reports one H.264 `yuv420p` video stream at the intended dimensions/FPS, AAC stereo 48 kHz audio, and duration within 0.10 s of the voiceover.
- `ffmpeg -v error -xerror -i <OUTPUT> -f null -` exits 0 (full decode).
- Measure integrated loudness with FFmpeg `loudnorm=I=-14:TP=-1.5:LRA=7:print_format=json`; verify target tolerance and record measured LUFS.
- Record the executed encoder command and require `h264_nvenc -preset p4 -cq 22 -b:v 0 -pix_fmt yuv420p` by default (or the explicitly selected CQ18 quality variant). File metadata alone does not prove encoder selection.
- Compute SHA-256 and byte size remotely. Download only after remote DONE to a unique local `.part`; stop the Colab session immediately after transfer, then compare local size/hash and rerun local probe/full-decode checks before atomic promotion.
- Inspect representative beginning, middle, and end frames for crop/bars, visible artifacts, and floating watermark placement. Preserve logs/report for any failed gate; do not promote or deliver.
- Run the bundled `references/verify_short_master.py` checker with expected voiceover duration, exact embedded title/description/artist/copyright, remote byte size/SHA-256, and the executed encoder command; require all checks to pass, including that genre/comment tags are absent, and save its JSON report.

## 3. Feature 1: AI Video Upscaling (Real-ESRGAN)

### When to Use
- Do not choose AI upscaling solely because the source is below 1080p. First compare several representative source frames with the normal spline-scaled result.
- Use Real-ESRGAN only when it produces a clearly useful visible improvement without temporal flicker/texture instability, and the benchmarked runtime is acceptable. If the improvement is subtle, keep spline scaling.

### Environment & Python 3.13 Compatibility Recovery
Colab runtimes using Python 3.13 fail on `pip install basicsr` and `pip install gfpgan` with `KeyError: '__version__'`. Never install `gfpgan`. Install `ffmpeg-python` explicitly (`pip install ffmpeg-python`) because `inference_realesrgan_video.py` imports it and it is not pre-installed on the Colab runtime. Install Real-ESRGAN manually:
1. Clone `BasicSR`, copy module to site-packages, and unconditionally create `basicsr/version.py` in both the clone and site-packages:
   `__version__ = "1.4.2"\n__gitsha__ = "8d56e3a"\nversion_info = ("1", "4", "2")`
2. Patch `basicsr/data/degradations.py`: replace `from torchvision.transforms.functional_tensor import rgb_to_grayscale` with `from torchvision.transforms.functional import rgb_to_grayscale`.
3. Clone `Real-ESRGAN`, copy `realesrgan` to site-packages, and unconditionally create `realesrgan/version.py` in both the clone and site-packages:
   `__version__ = "0.3.0"\n__gitsha__ = "unknown"`
   (Without this file, importing `realesrgan` fails with `ModuleNotFoundError: No module named 'realesrgan.version'`).
4. Download weights `realesr-animevideov3.pth` into `/content/Real-ESRGAN/weights/`.

### Colab Execution Commands
```python
import os, subprocess

cmd = [
    "python3", "/content/Real-ESRGAN/inference_realesrgan_video.py",
    "-i", "/content/input.mp4",
    "-o", "/content/upscaled",
    "-n", "realesr-animevideov3",
    "-s", "2"
    # On T4, omit --fp32 (default half precision); patch both Writer branches to NVENC first.
]
subprocess.run(cmd, check=True)
# Output file is created as: /content/upscaled/input_out.mp4
```

---

## 4. Feature 2: Frame Interpolation & Super Slow-Motion (RIFE 60 FPS)

### When to Use
- Audio duration is noticeably longer than video ($F = \text{duration}_{\text{audio}} / \text{duration}_{\text{video}} > 1.0$), which stretches video playback (`setpts = F * PTS`). Normal frame dupe causes visual jitter/stutter.
- Slow-motion shots or target 60 FPS cinematic smoothness is requested.

### Environment & Weights Recovery
1. The legacy Google Drive model ID (`11IqGl3EnOoTX2Z2mNFgkSmWFws4iS03m`) is blocked. Use active ID `1ZKjcbmt1hypiFprJPIKW0Tt0lr_2i7bg` (v4.25 HD).
2. Unzipping creates nested `train_log/train_log/`; move files (`flownet.pkl`, `RIFE_HDv3.py`, etc.) directly into `/content/RIFE/train_log/`.
3. Install `pip install -q gdown sk-video`. On Python 3.13/NumPy 2, patch every `.py` under `skvideo` (find it via `site.getsitepackages()`): replace `np.float(` -> `float(`, `np.int(` -> `int(`, and `np.fromstring(` -> `np.frombuffer(`. Without the last one RIFE dies on the first frame with `The binary mode of fromstring is removed`.
4. Pass `--model=/content/RIFE/train_log` (not `--modelDir`).

### Colab Execution Commands
```python
import os, subprocess

# Choose the smallest exp that supplies enough temporal samples
# after the F speed change: (source_fps / F) * (2 ** exp) >= target_fps.
# Example: 30 fps, F=1.327, target=60 => exp=2 (4x); exp=1 is insufficient.
exp = 2
cmd = [
    "python3", "/content/RIFE/inference_video.py",
    "--video=/content/upscaled/input_out.mp4",
    "--model=/content/RIFE/train_log",
    f"--exp={exp}",
    "--fp16",
    "--png"
]
workdir = "/content/rife_png_run_<UNIQUE_ID>"
os.makedirs(workdir, exist_ok=False)
subprocess.run(cmd, cwd=workdir, check=True)
# RIFE writes numbered frames to <workdir>/vid_out; FFmpeg NVENC encodes this sequence later.
# RIFE outputs 7-digit zero-padded filenames (0000000.png, 0000001.png, …).
# Detect the actual digit count from the first output file before building the FFmpeg
# command; do not hardcode %08d or assume an img prefix. Example detection:
#   first = sorted(os.listdir(vid_out))[0]  # e.g. '0000000.png'
#   ndigits = len(first.replace('.png',''))   # 7
#   pattern = os.path.join(vid_out, f'%0{ndigits}d.png')
```

---


### Observed T4 Stage Timing (Estimate from a Verified Run, Not a Guarantee)

A recent 935-frame 720p source took about 12m30s for Real-ESRGAN 2× (roughly 1.28 input frames/s), 6m29s for RIFE 2× PNG output with capped queues, and about 5m for final render plus remote verification. A 689-frame run completed Real-ESRGAN 2× in 574s (1.20 frames/s), RIFE exp=2 fp16 PNG in 660s, and FFmpeg NVENC render plus full verification in 214s. NVENC speeds up encoding, but does not remove neural inference, PNG disk I/O, CPU filter, loudness, or full-decode costs. Benchmark representative input, record elapsed time/throughput, and report progress at least every minute; never promise a fixed end-to-end time based on encoder FPS alone.

## 5. Feature 3: Staged Master Render inside Colab

Keep intermediate video data in Colab. Run dependencies, upscale, RIFE when requested, final render, verification, and download as separate observable stages; do not combine setup and rendering into one opaque call.

### Encode Integrity and Transfer Gate
Never download while a writer is active. A stage is complete only after exit code 0, remote ffprobe, full decode, required stream/spec checks, nonzero size, and a recorded SHA-256. Render to a unique partial path, then atomically promote it and write a DONE record. A timeout/disconnect is not proof that remote work stopped; follow the long-running recovery section above, inspect PID/status/log, and never start a second writer for the same output.

### Workflow
1. **Preflight locally:** probe source/voiceover and normalize audio as required.
2. **Upload inputs:** create the T4 session and upload only source assets and normalized voiceover; keep large intermediates on Colab.
3. **Run stages independently:** use a local script for each operation and an explicit bounded colab exec timeout. For stages that may exceed the caller's window, detach the remote process, save PID/run ID/log/status, and poll with short exec calls. Use the T4 NVENC settings for final render; do not use CPU libx264 on Colab.
4. **Verify remotely before download:** require DONE, expected streams/resolution/FPS/duration, a clean ffprobe and full decode, and recorded byte size/SHA-256.
5. **Download then release quota immediately:** download only the completed master to a unique local .part path; immediately stop the Colab session and verify no active sessions remain.
6. **Verify locally after teardown:** compare .part size and SHA-256 with the remote record; run local ffprobe and full decode; check duration/specs and representative frames. Promote .part to the final .mp4 name only after all checks pass. Otherwise preserve it as a failed artifact and do not deliver it.



### RIFE dimensions and final frame rate

Practical-RIFE may require each input dimension to be a multiple of 64. Before interpolation, pad only the model input to the next multiple of 64 (for example, width 1440 -> 1472 with 16 pixels on each side). After frame generation, crop away that temporary border before scaling/encoding; verify final dimensions and inspect the edges so no padding is visible. Set the final output rate explicitly to 60 fps. Derive the RIFE exponent from probed source FPS and measured speed factor F; do not assume 2x is sufficient after slowdown.