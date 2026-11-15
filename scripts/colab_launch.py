# Run with: colab exec -s <SESSION> -f <LOCAL_PATH>/colab_launch.py --timeout 60
# Starts /content/colab_rife_worker.py detached so it survives exec timeouts.
import os, subprocess
RUN = "/content/run_short"
os.makedirs(RUN, exist_ok=True)
log = open(f"{RUN}/worker.log", "w")
p = subprocess.Popen(["python3", "/content/colab_rife_worker.py"], stdout=log, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True)
open(f"{RUN}/worker.pid", "w").write(str(p.pid))
print("launched pid", p.pid)
