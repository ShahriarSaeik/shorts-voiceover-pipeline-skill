# Run with: colab exec -s <SESSION> -f <LOCAL_PATH>/colab_check.py --timeout 30
# Prints worker PID state, status.json, and log tail. Poll every ~30s until stage is DONE or FAILED.
import os, subprocess
RUN = "/content/run_short"
pid = open(f"{RUN}/worker.pid").read().strip() if os.path.exists(f"{RUN}/worker.pid") else "1"
print(subprocess.run(["ps", "-p", pid, "-o", "pid,etime,%cpu,%mem,cmd"], capture_output=True, text=True).stdout)
print(open(f"{RUN}/status.json").read() if os.path.exists(f"{RUN}/status.json") else "no status")
print(subprocess.run(["tail", "-n", "8", f"{RUN}/worker.log"], capture_output=True, text=True).stdout[-1500:])
for lg in sorted(f for f in os.listdir(RUN) if f.startswith("rife_") and f.endswith(".log"))[-1:]:
    print("--- " + lg)
    print(subprocess.run(["tail", "-n", "15", f"{RUN}/{lg}"], capture_output=True, text=True).stdout[-2000:])
