import time
import os
from pathlib import Path

build_dir = Path("build")
print("Monitoring build directory...")

for _ in range(20):
    time.sleep(5)
    if build_dir.exists():
        baserom_imgs = build_dir / "baserom/extracted/images"
        if baserom_imgs.exists():
            files = list(baserom_imgs.iterdir())
            print(f"BaseROM Images: {len(files)} files")
            if files:
                print(f"Sample: {[f.name for f in files[:3]]}")
        else:
            print("BaseROM images dir not created yet.")
    else:
        print("Build dir not created yet.")
