#!/usr/bin/env python3
"""Plan a Shorts voiceover render from probed facts. Prints a JSON plan; never renders.

Usage:
  preflight.py --video SRC.mp4 --voiceover VO.(wav|mp3) [--cq 22] [--job-dir DIR]

With --job-dir it also writes plan.json and a copy of colab_rife_worker.py whose CONFIG
block (VO_DUR, VID_DUR, SRC_FRAMES, SRC_FPS, CQ) is filled from the probe, then py_compiles it.
Exit code 0 = plan ready, 2 = plan printed but a human decision is needed (see "stop_and_ask").
"""
import argparse, json, os, py_compile, re, shutil, subprocess, sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"ffprobe failed for {path}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def first(streams, kind):
    for s in streams:
        if s.get("codec_type") == kind and s.get("disposition", {}).get("attached_pic", 0) == 0:
            return s
    return None


def num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def build_plan(video, voiceover, cq):
    pv, pa = probe(video), probe(voiceover)
    v = first(pv["streams"], "video")
    if v is None:
        sys.exit("source has no real video stream")
    a = first(pa["streams"], "audio")
    if a is None:
        sys.exit("voiceover has no audio stream")
    w, h = int(v["width"]), int(v["height"])
    fps = Fraction(v["r_frame_rate"])
    # Use the VIDEO stream duration: format duration can follow the audio stream and skew F.
    vid_dur = num(v.get("duration")) or num(pv["format"].get("duration"))
    vo_dur = num(pa["format"].get("duration")) or num(a.get("duration"))
    frames = int(v["nb_frames"]) if str(v.get("nb_frames", "")).isdigit() else round(vid_dur * float(fps))
    F = vo_dur / vid_dur

    is_4k = max(w, h) >= 3840 or min(w, h) >= 2160
    reasons, warnings, stop = [], [], []
    if is_4k and F <= 1.0:
        branch = "A_local_4k"
        reasons.append("4K-class source and F<=1: local libx264 render is allowed; keep native dimensions")
        out_w, out_h, out_fps = w, h, str(fps)
    else:
        branch = "B_colab_t4_rife"
        if F > 1.0:
            reasons.append(f"F={F:.4f}>1: video is slowed to match the voiceover, so Colab T4 + RIFE is required")
        if min(w, h) < 1080:
            reasons.append(f"short side {min(w, h)}<1080: Colab T4 + RIFE is required")
        if not reasons:
            reasons.append("non-4K source: the VPS has no GPU, so use Colab T4 + RIFE (user decision)")
        out_w, out_h, out_fps = 1440, 2560, "60/1"
        if is_4k:
            stop.append("4K-class source with F>1: the Colab worker is fixed to 1440x2560, which would downscale "
                        "a 4K source. Ask the user how to proceed before rendering.")
    exp = 1
    while float(fps) / F * (2 ** exp) < 60:
        exp += 1
    if abs(w / h - 9 / 16) > 0.02:
        warnings.append(f"aspect {w}x{h} is not 9:16: inspect framing so scaling hides nothing important")
    if any(s.get("disposition", {}).get("attached_pic") for s in pv["streams"]):
        warnings.append("source has a cover-art stream: map only 0:v:0 and strip it (-an video-only src.mp4 for RIFE)")
    audio_ok = a.get("codec_name", "").startswith("pcm") and a.get("sample_rate") == "48000"
    return {
        "source": {"path": video, "width": w, "height": h, "fps": str(fps), "video_duration": vid_dur,
                   "nb_frames": frames, "is_4k_class": is_4k},
        "voiceover": {"path": voiceover, "duration": vo_dur, "codec": a.get("codec_name"),
                      "sample_rate": a.get("sample_rate"), "needs_48k_wav_conversion": not audio_ok},
        "F": round(F, 6),
        "branch": branch,
        "why": reasons,
        "rife_exp": exp if branch == "B_colab_t4_rife" else None,
        "expected_output": {"width": out_w, "height": out_h, "fps": out_fps, "duration": vo_dur,
                            "video": "h264 yuv420p", "audio": "aac 48000 Hz stereo"},
        "encoder": ("libx264 preset medium crf 16, 2 threads" if branch == "A_local_4k"
                    else f"h264_nvenc -preset p4 -cq {cq} -b:v 0 -pix_fmt yuv420p"),
        "cq": cq,
        "warnings": warnings,
        "stop_and_ask": stop,
    }


def write_job(plan, job_dir):
    os.makedirs(job_dir, exist_ok=True)
    json.dump(plan, open(os.path.join(job_dir, "plan.json"), "w"), indent=2)
    if plan["branch"] != "B_colab_t4_rife":
        return None
    dst = os.path.join(job_dir, "colab_rife_worker.py")
    src = open(os.path.join(HERE, "colab_rife_worker.py"), encoding="utf-8").read()
    fps = Fraction(plan["source"]["fps"])
    values = {"VO_DUR": plan["voiceover"]["duration"], "VID_DUR": plan["source"]["video_duration"],
              "SRC_FRAMES": plan["source"]["nb_frames"],
              "SRC_FPS": int(fps) if fps.denominator == 1 else float(fps),
              "CQ": f'"{plan["cq"]}"'}
    for key, val in values.items():
        src, n = re.subn(rf"^({key}\s*=\s*)\S+", lambda m, val=val: f"{m.group(1)}{val}", src, count=1, flags=re.M)
        if n != 1:
            sys.exit(f"worker CONFIG line {key} not found; refusing to write a half-configured worker")
    open(dst, "w", encoding="utf-8").write(src)
    py_compile.compile(dst, doraise=True)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--voiceover", required=True)
    ap.add_argument("--cq", default="22")
    ap.add_argument("--job-dir")
    args = ap.parse_args()
    for p in (args.video, args.voiceover):
        if not os.path.isfile(p):
            sys.exit(f"missing file: {p}")
    if shutil.which("ffprobe") is None:
        sys.exit("ffprobe not found")
    plan = build_plan(args.video, args.voiceover, args.cq)
    if args.job_dir:
        plan["configured_worker"] = write_job(plan, args.job_dir)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    sys.exit(2 if plan["stop_and_ask"] else 0)


if __name__ == "__main__":
    main()
