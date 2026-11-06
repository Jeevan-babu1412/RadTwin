# RadTwin - Model benchmark on the synthetic dataset (Module M7)
# Trains a light model to predict the beam offset (how far the X-ray beam misses the target)
# from the image, and scores it against a "no correction" baseline:
#   overall, per patient type (population fairness) and per exam.
# Run in RadTwin Composer Script Editor (or any Python with numpy + Pillow).
# Output: <dataset>/benchmark/results.json and BENCHMARK.md

DATASET_DIR = ""        # leave empty = newest dataset next to your .usd file
IMAGE_SIZE = (64, 36)   # images are shrunk to this before learning
TOLERANCE_CM = 2.0      # "good enough" threshold used in the report (illustrative, not clinical)

import glob, json, os, time

try:
    import omni.usd
    _layer = omni.usd.get_context().get_stage().GetRootLayer().realPath
    BASE = os.path.dirname(_layer) if _layer else os.path.expanduser("~")
except ImportError:
    import sys
    BASE = None
    DATASET_DIR = sys.argv[1] if len(sys.argv) > 1 else DATASET_DIR


def need(module, package):
    try:
        return __import__(module)
    except ImportError:
        import omni.kit.pipapi
        omni.kit.pipapi.install(package, module=module)
        return __import__(module)


np = need("numpy", "numpy")
need("PIL", "Pillow")
from PIL import Image

# ---------------- load ----------------
if not DATASET_DIR:
    found = sorted(glob.glob(os.path.join(BASE, "datasets", "radtwin_xray_*")))
    if not found:
        raise SystemExit("[RadTwin] No dataset found. Run generate_dataset.py first.")
    DATASET_DIR = found[-1]

manifest = json.load(open(os.path.join(DATASET_DIR, "manifest.json")))
rows = []
for entry in manifest["files"]:
    image_rel = entry.get("image", f"rgb/{entry['frame_id']}.png")      # images may finish after the manifest
    if not os.path.exists(os.path.join(DATASET_DIR, image_rel)):
        continue
    label = json.load(open(os.path.join(DATASET_DIR, entry["label"])))
    img = Image.open(os.path.join(DATASET_DIR, image_rel)).convert("L").resize(IMAGE_SIZE)
    rows.append((label, np.asarray(img, dtype=np.float32).ravel() / 255.0))

if len(rows) < 20:
    raise SystemExit(f"[RadTwin] Only {len(rows)} images found; generate at least ~150 frames for a meaningful benchmark.")

labels = [r[0] for r in rows]
X = np.stack([r[1] for r in rows])
Y = np.array([l["beam_offset_cm"] for l in labels], dtype=np.float32)       # [along, across] in cm
split = np.array([l["split"] for l in labels])
print(f"[RadTwin] Benchmark on {os.path.basename(DATASET_DIR)}: {len(rows)} frames "
      f"(train {sum(split == 'train')}, val {sum(split == 'val')}, test {sum(split == 'test')})")

# ---------------- models ----------------
tr, va, te = split == "train", split == "val", split == "test"
if va.sum() == 0:           # tiny datasets may have no val frames: borrow some train frames
    idx = np.where(tr)[0][: max(2, tr.sum() // 8)]
    va = np.zeros_like(tr); va[idx] = True; tr = tr & ~va

mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6
Xs = (X - mu) / sd
ym = Y[tr].mean(0)


def ridge_fit(Xa, ya, lam):
    K = Xa @ Xa.T                                            # dual form: fast when pixels >> samples
    alpha = np.linalg.solve(K + lam * np.eye(len(K)), ya - ym)
    return Xa.T @ alpha


best = None
for lam in [1, 10, 100, 1000, 10000]:
    W = ridge_fit(Xs[tr], Y[tr], lam)
    mae = np.abs(Xs[va] @ W + ym - Y[va]).mean()
    if best is None or mae < best[0]:
        best = (mae, lam, W)
_, LAMBDA, W = best
W = ridge_fit(Xs[tr | va], Y[tr | va], LAMBDA)               # refit on train + val

predictions = {
    "no_correction (baseline)": np.zeros_like(Y),            # trust the nominal plan
    f"ridge_pixels (lambda={LAMBDA})": Xs @ W + ym,         # learned from the image
}

# ---------------- metrics ----------------
def score(pred, mask):
    if mask.sum() == 0:
        return None
    err = np.linalg.norm(pred[mask] - Y[mask], axis=1)       # 2D miss distance in cm
    return {"n": int(mask.sum()), "mae_cm": round(float(err.mean()), 2),
            "p90_cm": round(float(np.percentile(err, 90)), 2),
            f"within_{TOLERANCE_CM:g}cm": round(float((err <= TOLERANCE_CM).mean()), 2)}


groups = {
    "patient": sorted({l["patient"]["variant"] for l in labels}),
    "exam": sorted({l["exam"]["protocol"] for l in labels}),
}
results = {"dataset": manifest["name"], "dataset_version": manifest["version"], "frames": len(rows),
           "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "target": "beam_offset_cm (along, across table)", "split_used": "test", "models": {}}
for name, pred in predictions.items():
    res = {"test": score(pred, te)}
    for key, values in groups.items():
        for v in values:
            m = te & np.array([(l["patient"]["variant"] if key == "patient" else l["exam"]["protocol"]) == v
                               for l in labels])
            res[f"{key}:{v}"] = score(pred, m)
    results["models"][name] = res

# ---------------- report ----------------
out = os.path.join(DATASET_DIR, "benchmark")
os.makedirs(out, exist_ok=True)
json.dump(results, open(os.path.join(out, "results.json"), "w"), indent=2)

names = list(predictions)
lines = [f"# RadTwin benchmark: beam-offset prediction",
         "", f"Dataset `{manifest['name']}` (v{manifest['version']}), {len(rows)} frames, scored on the **test split**.",
         "Error = distance between predicted and true beam offset, in cm. Lower is better.", "",
         "| Group | n | " + " | ".join(f"{n} MAE (cm)" for n in names) + f" | learned within {TOLERANCE_CM:g} cm |",
         "|---|---|" + "---|" * len(names) + "---|"]
for key in ["test"] + [f"patient:{v}" for v in groups["patient"]] + [f"exam:{v}" for v in groups["exam"]]:
    s0 = results["models"][names[0]][key]
    if not s0:
        continue
    s1 = results["models"][names[1]][key]
    lines.append(f"| {'all' if key == 'test' else key} | {s0['n']} | "
                 + " | ".join(str(results['models'][n][key]['mae_cm']) for n in names)
                 + f" | {int(s1[f'within_{TOLERANCE_CM:g}cm'] * 100)}% |")
lines += ["", "Notes:",
          "- Groups with very few test frames are indicative only; generate more frames for firm numbers.",
          "- `ridge_pixels` is a deliberately simple baseline. The same data contract (images + labels/*.json",
          "  + manifest splits) feeds a PyTorch / MONAI model in production.",
          "- A gap between patient groups is a population-fairness finding to act on (more data, re-balancing)."]
open(os.path.join(out, "BENCHMARK.md"), "w").write("\n".join(lines))

print("\n".join(lines[5:5 + 2 + 1 + len(groups['patient']) + len(groups['exam'])]))
print(f"[RadTwin] Report: {os.path.join(out, 'BENCHMARK.md')}")
