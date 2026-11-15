#!/usr/bin/env python3
"""Detached Colab T4 worker: Practical-RIFE -> 60fps -> spline 1440x2560 -> NVENC master.

Upload to /content with: src.mp4 (source video), vo_norm.wav (loudness-normalized 48k stereo
voiceover), meta.json ({title, description, copyright}). Edit the CONFIG block per job.
Launch detached via scripts/colab_launch.py; poll via scripts/colab_check.py.
Writes RUN/status.json each stage; final stage is DONE with size/sha256, or FAILED with error.
"""
import glob, hashlib, json, os, shutil, subprocess, sys, time

# ---- CONFIG (set per job from local ffprobe) ----
RUN = "/content/run_short"
SRC = "/content/src.mp4"
VO = "/content/vo_norm.wav"
VO_DUR = 48.11        # voiceover seconds
VID_DUR = 48.466667   # source video seconds
SRC_FRAMES = 1454     # source nb_frames, for progress only
SRC_FPS = 30
CQ = "22"             # 22 default, 18 for higher quality
# -------------------------------------------------
F = VO_DUR / VID_DUR
EXP = 1
while (SRC_FPS / F) * (2 ** EXP) < 60:
    EXP += 1
PARTIAL = f"{RUN}/master.partial.mp4"
FINAL = f"{RUN}/master.mp4"
STATUS = f"{RUN}/status.json"
META = json.load(open("/content/meta.json", encoding="utf-8"))


def status(stage, **kw):
    tmp = STATUS + ".tmp"
    json.dump({"stage": stage, "ts": time.time(), **kw}, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, STATUS)
    print(f"[status] {stage} {kw}", flush=True)


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def setup():
    status("setup")
    if not os.path.isdir("/content/RIFE"):
        run(["git", "clone", "--depth", "1", "https://github.com/hzwer/Practical-RIFE", "/content/RIFE"])
    run([sys.executable, "-m", "pip", "install", "-q", "gdown", "sk-video"])
    if not os.path.exists("/content/RIFE/train_log/flownet.pkl"):
        run(["gdown", "1ZKjcbmt1hypiFprJPIKW0Tt0lr_2i7bg", "-O", "/content/rife_w.zip"])
        run(["unzip", "-o", "-q", "/content/rife_w.zip", "-d", "/content/RIFE"])
        nested = "/content/RIFE/train_log/train_log"
        if os.path.isdir(nested):
            for f in os.listdir(nested):
                shutil.move(os.path.join(nested, f), "/content/RIFE/train_log/" + f)
    assert os.path.exists("/content/RIFE/train_log/flownet.pkl"), "RIFE weights missing"
    import site
    for sp in site.getsitepackages():
        for py in glob.glob(f"{sp}/skvideo/**/*.py", recursive=True):
            s = open(py).read()
            n = (s.replace("np.float(", "float(").replace("np.int(", "int(")
                  .replace("np.fromstring(", "np.frombuffer("))
            if n != s:
                open(py, "w").write(n)
    iv = "/content/RIFE/inference_video.py"
    s = open(iv).read()
    if "Queue(maxsize=500)" in s:
        shutil.copy(iv, iv + ".bak")
        open(iv, "w").write(s.replace("Queue(maxsize=500)", "Queue(maxsize=8)"))
    run([sys.executable, "-m", "py_compile", iv])


def rife():
    wd = f"{RUN}/rife_{int(time.time())}"
    os.makedirs(wd, exist_ok=False)
    log = open(f"{wd}.log", "w")
    p = subprocess.Popen([sys.executable, "/content/RIFE/inference_video.py", f"--video={SRC}",
                          "--model=/content/RIFE/train_log", f"--exp={EXP}", "--fp16", "--png"],
                         cwd=wd, stdout=log, stderr=subprocess.STDOUT)
    while p.poll() is None:
        status("rife", exp=EXP, frames=len(glob.glob(f"{wd}/vid_out/*.png")),
               expected=SRC_FRAMES * 2 ** EXP)
        time.sleep(15)
    if p.returncode != 0:
        raise RuntimeError(f"RIFE exit {p.returncode}; see {wd}.log")
    frames = sorted(os.listdir(f"{wd}/vid_out"))
    nd = len(frames[0].replace(".png", ""))
    return f"{wd}/vid_out/%0{nd}d.png", len(frames)


def render(pattern):
    status("render")
    in_fps = SRC_FPS * 2 ** EXP
    vf = (f"setpts={F:.6f}*PTS,fps=60,hqdn3d=1.5:1.5:3:3,scale=1440:2560:flags=spline,"
          "unsharp=3:3:0.15:3:3:0.0,eq=saturation=1.05:contrast=1.02,"
          "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
          "text='@IshaniFact':fontcolor=white:fontsize=46:"
          "shadowcolor=black@0.6:shadowx=2:shadowy=2:x=(w-text_w)/2:y=h-360,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-framerate", str(in_fps), "-i", pattern, "-i", VO,
           "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
           "-c:v", "h264_nvenc", "-preset", "p4", "-cq", CQ, "-b:v", "0", "-pix_fmt", "yuv420p",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-r", "60", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
           "-t", str(VO_DUR), "-movflags", "+faststart",
           "-metadata", f"title={META['title']}", "-metadata", f"description={META['description']}",
           "-metadata", "artist=@IshaniFact", "-metadata", f"copyright={META['copyright']}", PARTIAL]
    open(f"{RUN}/encoder_cmd.txt", "w").write(" ".join(cmd))
    with open(f"{RUN}/render.log", "w") as log:
        subprocess.run(cmd, check=True, stdout=log, stderr=subprocess.STDOUT)


def verify():
    status("verify")
    run(["ffmpeg", "-v", "error", "-xerror", "-i", PARTIAL, "-f", "null", "-"])
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                    PARTIAL], capture_output=True, text=True, check=True).stdout)
    v = [s for s in pr["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in pr["streams"] if s["codec_type"] == "audio"][0]
    dur = float(pr["format"]["duration"])
    assert (v["codec_name"], v["width"], v["height"], v["pix_fmt"], v["r_frame_rate"]) == \
        ("h264", 1440, 2560, "yuv420p", "60/1"), v
    assert (a["codec_name"], a["sample_rate"], a["channels"]) == ("aac", "48000", 2), a
    assert abs(dur - VO_DUR) <= 0.10, dur
    os.replace(PARTIAL, FINAL)
    h = hashlib.sha256()
    with open(FINAL, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return {"size": os.path.getsize(FINAL), "sha256": h.hexdigest(), "duration": dur,
            "nb_frames": v.get("nb_frames")}


def main():
    os.makedirs(RUN, exist_ok=True)
    try:
        setup()
        pattern, n = rife()
        status("rife_done", frames=n)
        render(pattern)
        status("DONE", **verify())
    except Exception as e:
        status("FAILED", error=repr(e)[:800])
        raise


if __name__ == "__main__":
    main()
