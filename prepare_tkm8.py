"""Filter dataset Roboflow v5 (45 kelas) -> 8 dominan, remap id 0-7.
Val digabung valid+test (split asli valid cuma 9 gambar)."""
import shutil
from pathlib import Path

BASE = Path("/home/ubuntu-no-25/tkm-new-fllstck/datasets")
SRC = BASE / "montessori-v5"
DST = BASE / "tkm8"

# old_id -> (new_id, nama)
KEEP = {1: (0, "bantal"), 20: (1, "lemari"), 19: (2, "kursi"), 42: (3, "tas ransel"),
        10: (4, "hp"), 37: (5, "remote AC"), 24: (6, "meja"), 31: (7, "piring")}
NAMES = ["bantal", "lemari", "kursi", "tas ransel", "hp", "remote AC", "meja", "piring"]

if DST.exists():
    shutil.rmtree(DST)

splits = {"train": ["train"], "valid": ["valid", "test"]}
total = {}
for out_split, in_splits in splits.items():
    n_img = 0
    per_class = {i: 0 for i in range(8)}
    for s in in_splits:
        for img in (SRC / s / "images").glob("*.jpg"):
            lab = SRC / s / "labels" / (img.stem + ".txt")
            kept = []
            if lab.exists():
                for line in lab.read_text().splitlines():
                    p = line.split()
                    if not p:
                        continue
                    old = int(float(p[0]))
                    if old in KEEP:
                        new_id, _ = KEEP[old]
                        kept.append(str(new_id) + " " + " ".join(p[1:]))
                        per_class[new_id] += 1
            if not kept:
                continue  # buang gambar tanpa 8 dominan
            di = DST / out_split / "images"
            dl = DST / out_split / "labels"
            di.mkdir(parents=True, exist_ok=True)
            dl.mkdir(parents=True, exist_ok=True)
            shutil.copy(img, di / img.name)
            (dl / (img.stem + ".txt")).write_text("\n".join(kept) + "\n")
            n_img += 1
    total[out_split] = (n_img, per_class)
    print(out_split + ": " + str(n_img) + " images")
    for i in range(8):
        print("  %-10s %d" % (NAMES[i], per_class[i]))

(DST / "tkm_8.yaml").write_text(
    "train: " + str(DST / "train" / "images") + "\n"
    "val: " + str(DST / "valid" / "images") + "\n"
    "nc: 8\nnames: " + str(NAMES) + "\n"
)
print("yaml ok ->", DST / "tkm_8.yaml")
