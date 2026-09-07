"""Ekstrak dataset Roboflow v5 + hitung distribusi kelas per split."""
import collections
import zipfile
from pathlib import Path

BASE = Path("/home/ubuntu-no-25/tkm-new-fllstck/datasets")
z = zipfile.ZipFile(BASE / "montessori-v5-train-ke-5.yolov8.zip")
z.extractall(BASE / "montessori-v5")
print("extract ok")

names = [
    "AC", "bantal", "blok kayu", "botol minum", "box", "brownstair", "buku",
    "gelas", "globe", "gunting", "hp", "jam", "jam dinding", "kelender",
    "kemoceng", "keranjang", "kertas", "keset", "knobbedcylinders", "kursi",
    "lemari", "mainan blok", "mangkok", "matras", "meja", "pena", "penggaris",
    "penghapus", "pensil", "pink tower", "pintu", "piring", "pisau", "plastik",
    "rak", "rautan", "red rods", "remote AC", "sapu", "sendok",
    "serokan sampah", "spidol", "tas ransel", "tas sandang", "tikar",
]
for split in ("train", "valid", "test"):
    labdir = BASE / "montessori-v5" / split / "labels"
    imgdir = BASE / "montessori-v5" / split / "images"
    n_img = len(list(imgdir.glob("*.jpg"))) if imgdir.exists() else 0
    cnt = collections.Counter()
    n_lab = 0
    if labdir.exists():
        for f in labdir.glob("*.txt"):
            n_lab += 1
            for line in f.read_text().splitlines():
                p = line.split()
                if p:
                    cnt[int(float(p[0]))] += 1
    print("=== " + split + ": " + str(n_img) + " images, " + str(n_lab) + " labels, " + str(sum(cnt.values())) + " instances")
    for cid, c in cnt.most_common():
        print("  %2d %-15s %d" % (cid, names[cid], c))
