# RadTwin - Synthetic dataset generator (Module M5)
# For each frame: random patient + exam + pose offset + camera jitter
#   -> autonomous positioning -> RGB capture -> labels + metadata
# Then writes a versioned manifest (splits, counts, file hashes) and the labelling rules.
# Run in RadTwin Composer: Window > Script Editor > paste > Run  (physics stopped, save first)
# Output: <folder of your .usd>/datasets/radtwin_xray_v<version>_<time>/

NUM_FRAMES = 30            # keep small on a 16 GB laptop; raise later
SEED = 42                  # same seed = same dataset (reproducible)
DATASET_VERSION = "0.1.0"
RESOLUTION = (1024, 576)
CAPTURE_IMAGES = True

import asyncio, hashlib, json, math, os, random, time
from pxr import Usd, UsdGeom, Sdf, Gf

try:
    import omni.usd, omni.kit.app
    stage = omni.usd.get_context().get_stage()
    IN_OMNIVERSE = True
except ImportError:  # testing outside Omniverse
    import sys
    stage = Usd.Stage.Open(sys.argv[1])
    IN_OMNIVERSE = False
    CAPTURE_IMAGES = False

R = "/World/ExamRoom"
CAM_PATH = "/World/Cameras/DatasetCam"
PATIENTS = ["child", "adult_small", "adult_medium", "adult_large"]
PROTOCOLS = {
    "skull_ap":   {"body_cm": 11,  "table_cm": 82, "sid_cm": 100, "kVp": 75},
    "chest_ap":   {"body_cm": 54,  "table_cm": 80, "sid_cm": 100, "kVp": 85},
    "abdomen_ap": {"body_cm": 89,  "table_cm": 78, "sid_cm": 100, "kVp": 80},
    "pelvis_ap":  {"body_cm": 107, "table_cm": 78, "sid_cm": 100, "kVp": 80},
    "knee_ap":    {"body_cm": 154, "table_cm": 82, "sid_cm": 100, "kVp": 65},
}
SID_MAX, HEAD_TOP_X = 120, -99.0
DETECTOR_BELOW_TABLE, COLLIMATOR_DROP = 5.7, 27.4
MATTRESS_ABOVE_TABLE, BODY_THICKNESS, MIN_CLEARANCE = 9.0, 35.0, 15

TABLE_TOP = [f"{R}/PatientTable/{n}" for n in
             ["TableTop", "Mattress", "RailFront", "RailBack", "Pillow", "PedestalCap"]] + ["/World/Patient"]
TRAY = [f"{R}/TableDetector/Tray", f"{R}/TableDetector/ActiveArea"]
TUBE_SLIDE = [f"{R}/XrayTube/{n}" for n in ["Carriage", "ColumnOuter"]]
TUBE_HEAD = [f"{R}/XrayTube/{n}" for n in
             ["ColumnInner", "TubeHousing", "TubeCapA", "TubeCapB", "Collimator", "CollimatorLight",
              "ControlPanel", "HandleL", "HandleR", "HandleBarL", "HandleBarR"]]

# What gets a bounding box: class name -> prims that make up the object
CLASSES = {
    "patient":    ["/World/Patient"],
    "table":      [f"{R}/PatientTable"],
    "xray_tube":  TUBE_HEAD,
    "detector":   [f"{R}/TableDetector"],
    "wall_stand": [f"{R}/WallStand"],
}

LABELLING_RULES = """# RadTwin labelling rules (dataset v{version})

Every label is generated from the simulation's ground truth, never drawn by hand.

## Classes
| id | class | what it covers |
|---|---|---|
| 0 | patient | the whole patient body (all body parts) |
| 1 | table | table top, mattress, rails, pedestal |
| 2 | xray_tube | tube housing, collimator, handles, inner column (not the ceiling rails) |
| 3 | detector | the detector tray under the table top |
| 4 | wall_stand | chest wall stand |

## Boxes
- Format: `bbox_xyxy` = [x_min, y_min, x_max, y_max] in pixels, origin top-left.
- Boxes are **amodal**: they cover the full object even where it is hidden behind something
  (e.g. the detector under the table). `visible_fraction` is not estimated in v0.1.
- Boxes are clipped to the image; objects fully outside the image are omitted.
- Boxes are projections of each object's 3D axis-aligned bounds, so they can be a few pixels
  looser than a hand-drawn box (most visible on rounded shapes such as the patient).

## Keypoints
- `target_px`: centre of the body part the exam protocol targets.
- `beam_px`: where the X-ray beam centre meets the patient surface.

## Regression target
- `beam_offset_cm` = [along table, across table]: how far the beam centre is from the target.
  Non-zero because the patient lies slightly off the nominal position (`pose_offset_cm`).
  A model that predicts this from the image can correct autonomous positioning.

## Privacy
- All patients are synthetic. No real patient data, no PHI. `contains_phi` is always false.
"""


# ---------------- helpers ----------------
def get_xf(path):
    return UsdGeom.XformCommonAPI(stage.GetPrimAtPath(path)).GetXformVectors(Usd.TimeCode.Default())


def shift(path, dx, dy, dz=0.0):
    prim = stage.GetPrimAtPath(path)
    if prim:
        t = get_xf(path)[0]
        UsdGeom.XformCommonAPI(prim).SetTranslate(Gf.Vec3d(t[0] + dx, t[1] + dy, t[2] + dz))


def set_twin(path, name, value, typ=Sdf.ValueTypeNames.Float):
    stage.GetPrimAtPath(path).CreateAttribute(f"radtwin:{name}", typ).Set(value)


def select_patient(variant):
    p = stage.GetPrimAtPath("/World/Patient")
    p.GetVariantSets().GetVariantSet("bodyType").SetVariantSelection(variant)
    scale = get_xf("/World/Patient/Anchor/Body")[2]
    return scale, {"variant": variant,
                   "massKg": p.GetAttribute("radtwin:massKg").Get(),
                   "heightCm": p.GetAttribute("radtwin:heightCm").Get(),
                   "ageGroup": p.GetAttribute("radtwin:ageGroup").Get()}


def current_state():
    h = stage.GetPrimAtPath(f"{R}/PatientTable/TableTop").GetAttribute("radtwin:heightCm").Get() or 80.0
    t = get_xf(f"{R}/XrayTube/TubeHousing")[0]
    return h, t[0], t[1]


def plan(exam, scale):
    p = PROTOCOLS[exam]
    h1 = p["table_cm"]
    tx1 = HEAD_TOP_X + p["body_cm"] * scale[0]
    patient_top = h1 + MATTRESS_ABOVE_TABLE + BODY_THICKNESS * scale[1]
    sid = p["sid_cm"]
    clearance = (h1 - DETECTOR_BELOW_TABLE + sid - COLLIMATOR_DROP) - patient_top
    status = "READY"
    if clearance < MIN_CLEARANCE:
        sid = min(SID_MAX, sid + (MIN_CLEARANCE - clearance))
        clearance = (h1 - DETECTOR_BELOW_TABLE + sid - COLLIMATOR_DROP) - patient_top
        status = "READY_SID_ADJUSTED" if clearance >= MIN_CLEARANCE - 1e-6 else "BLOCKED_COLLISION_RISK"
    return h1, tx1, h1 - DETECTOR_BELOW_TABLE + sid, sid, clearance, status, patient_top


def move_now(h1, tx1, ty1):
    h0, tx0, ty0 = current_state()
    dh, dx, dy = h1 - h0, tx1 - tx0, ty1 - ty0
    for p in TABLE_TOP: shift(p, 0, dh)
    for p in TRAY: shift(p, dx, dh)
    for p in TUBE_SLIDE: shift(p, dx, 0)
    for p in TUBE_HEAD: shift(p, dx, dy)
    set_twin(f"{R}/PatientTable/TableTop", "heightCm", float(h1))


def setup_camera(width, height):
    UsdGeom.Xform.Define(stage, "/World/Cameras")
    cam = UsdGeom.Camera.Define(stage, CAM_PATH)
    cam.CreateFocalLengthAttr(18.0)
    cam.CreateHorizontalApertureAttr(20.955)
    cam.CreateVerticalApertureAttr(20.955 * height / width)   # same aspect as the image
    cam.CreateClippingRangeAttr(Gf.Vec2f(1.0, 10000.0))
    return cam


def place_camera(cam, eye, target):
    view = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 1, 0))
    xf = UsdGeom.Xformable(cam)
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(view.GetInverse())


def projector(cam, width, height):
    fr = cam.GetCamera(Usd.TimeCode.Default()).frustum
    m = fr.ComputeViewMatrix() * fr.ComputeProjectionMatrix()
    def to_px(p):
        n = m.Transform(Gf.Vec3d(*p))
        return ((n[0] + 1) * 0.5 * width, (1 - n[1]) * 0.5 * height)
    return to_px


bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_], useExtentsHint=False)


def bbox_2d(paths, to_px, width, height):
    bbox_cache.Clear()
    rng = Gf.Range3d()
    for path in paths:
        prim = stage.GetPrimAtPath(path)
        if prim:
            rng.UnionWith(bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange())
    if rng.IsEmpty():
        return None
    lo, hi = rng.GetMin(), rng.GetMax()
    pts = [to_px((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    x0, y0 = max(0.0, min(p[0] for p in pts)), max(0.0, min(p[1] for p in pts))
    x1, y1 = min(width, max(p[0] for p in pts)), min(height, max(p[1] for p in pts))
    if x1 <= x0 or y1 <= y0:
        return None
    return [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]


async def frames(n):
    if IN_OMNIVERSE:
        for _ in range(n):
            await omni.kit.app.get_app().next_update_async()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_for(frame_id):
    b = int(hashlib.md5(frame_id.encode()).hexdigest(), 16) % 10
    return "test" if b == 0 else "val" if b == 1 else "train"


# ---------------- main ----------------
async def generate():
    rnd = random.Random(SEED)
    layer_path = stage.GetRootLayer().realPath
    base = os.path.dirname(layer_path) if layer_path else os.path.expanduser("~")
    name = f"radtwin_xray_v{DATASET_VERSION}_{time.strftime('%Y%m%d_%H%M%S')}"
    root = os.path.join(base, "datasets", name)
    os.makedirs(os.path.join(root, "rgb"), exist_ok=True)
    os.makedirs(os.path.join(root, "labels"), exist_ok=True)

    width, height = RESOLUTION
    cam = setup_camera(width, height)
    viewport = None
    if IN_OMNIVERSE:
        from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file
        viewport = get_active_viewport()
        old_cam = viewport.camera_path
        try:
            viewport.resolution = RESOLUTION
        except Exception:
            pass
        width, height = [int(v) for v in viewport.resolution]
        cam.GetVerticalApertureAttr().Set(20.955 * height / width)
        viewport.camera_path = CAM_PATH

    print(f"[RadTwin] Generating {NUM_FRAMES} frames ({width}x{height}) -> {root}")
    records = []
    for i in range(NUM_FRAMES):
        fid = f"{i:06d}"
        variant = rnd.choice(PATIENTS)
        exam = rnd.choice(list(PROTOCOLS))
        dx, dz = round(rnd.uniform(-6, 6), 1), round(rnd.uniform(-4, 4), 1)        # patient lies slightly off
        eye = (230 + rnd.uniform(-25, 25), 210 + rnd.uniform(-20, 20), 280 + rnd.uniform(-25, 25))
        target = (rnd.uniform(-15, 15), 100 + rnd.uniform(-8, 8), rnd.uniform(-10, 10))

        scale, pinfo = select_patient(variant)
        h1, tx1, ty1, sid, clearance, status, patient_top = plan(exam, scale)   # plan uses the NOMINAL pose
        if status != "BLOCKED_COLLISION_RISK":
            move_now(h1, tx1, ty1)
        shift("/World/Patient", dx, 0, dz)                                        # real pose differs a little
        place_camera(cam, eye, target)
        await frames(12)

        to_px = projector(cam, width, height)
        target_world = (HEAD_TOP_X + PROTOCOLS[exam]["body_cm"] * scale[0] + dx,
                        (h1 + MATTRESS_ABOVE_TABLE + patient_top) / 2, dz)
        beam_world = (tx1, patient_top, 0.0)
        annotations = []
        for cid, (cname, paths) in enumerate(CLASSES.items()):
            box = bbox_2d(paths, to_px, width, height)
            if box:
                annotations.append({"class_id": cid, "class": cname, "bbox_xyxy": box})

        image_rel = f"rgb/{fid}.png"
        if CAPTURE_IMAGES:
            capture_viewport_to_file(viewport, os.path.join(root, image_rel))
            await frames(6)

        rec = {
            "frame_id": fid, "dataset_version": DATASET_VERSION, "seed": SEED, "split": split_for(fid),
            "image": {"file": image_rel if CAPTURE_IMAGES else None, "width": width, "height": height},
            "patient": {**pinfo, "pose_offset_cm": [dx, dz]},
            "exam": {"protocol": exam, "kVp": PROTOCOLS[exam]["kVp"], "sid_cm": round(sid, 1),
                     "clearance_cm": round(clearance, 1), "status": status},
            "equipment": {"table_height_cm": h1, "tube_x_cm": round(tx1, 1)},
            "camera": {"path": CAM_PATH, "eye_cm": [round(v, 1) for v in eye],
                       "target_cm": [round(v, 1) for v in target], "focal_length": 18.0},
            "annotations": annotations,
            "keypoints": {"target_px": [round(v, 1) for v in to_px(target_world)],
                          "beam_px": [round(v, 1) for v in to_px(beam_world)]},
            "beam_offset_cm": [round(tx1 - target_world[0], 1), round(0.0 - dz, 1)],
            "synthetic": True, "contains_phi": False,
        }
        with open(os.path.join(root, "labels", f"{fid}.json"), "w") as f:
            json.dump(rec, f, indent=2)
        records.append(rec)
        shift("/World/Patient", -dx, 0, -dz)                                      # undo the pose offset
        print(f"[RadTwin] {i + 1:02d}/{NUM_FRAMES} {variant:<13} {exam:<11} offset {dx:+.1f},{dz:+.1f} cm "
              f"boxes {len(annotations)}  [{rec['split']}]")

    await frames(30)   # let the last captures finish writing
    if viewport is not None:
        viewport.camera_path = old_cam

    # ---------- dataset governance: manifest ----------
    files = []
    for r in records:
        entry = {"frame_id": r["frame_id"], "split": r["split"], "label": f"labels/{r['frame_id']}.json",
                 "label_sha256": sha256(os.path.join(root, "labels", f"{r['frame_id']}.json"))}
        img = os.path.join(root, r["image"]["file"]) if r["image"]["file"] else None
        if img and os.path.exists(img):
            entry["image"], entry["image_sha256"] = r["image"]["file"], sha256(img)
        files.append(entry)

    def counts(key):
        out = {}
        for r in records:
            k = key(r); out[k] = out.get(k, 0) + 1
        return out

    manifest = {
        "dataset": "radtwin_xray_positioning", "version": DATASET_VERSION, "name": name,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": {"script": "generate_dataset.py", "seed": SEED, "source_stage": layer_path or "unsaved"},
        "num_frames": len(records), "resolution": [width, height],
        "classes": [{"id": i, "name": n} for i, n in enumerate(CLASSES)],
        "splits": counts(lambda r: r["split"]),
        "distribution": {"patient": counts(lambda r: r["patient"]["variant"]),
                         "exam": counts(lambda r: r["exam"]["protocol"]),
                         "status": counts(lambda r: r["exam"]["status"])},
        "privacy": {"synthetic": True, "contains_phi": False},
        "labelling_rules": "LABELLING.md",
        "files": files,
    }
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(root, "LABELLING.md"), "w") as f:
        f.write(LABELLING_RULES.format(version=DATASET_VERSION))

    # ---------- visual QA: draw labels on the first 3 images ----------
    if CAPTURE_IMAGES:
        try:
            from PIL import Image, ImageDraw
            os.makedirs(os.path.join(root, "qa"), exist_ok=True)
            colours = ["red", "yellow", "lime", "deepskyblue", "violet"]
            for r in records[:3]:
                img_path = os.path.join(root, r["image"]["file"])
                if not os.path.exists(img_path):
                    continue
                im = Image.open(img_path).convert("RGB")
                d = ImageDraw.Draw(im)
                for a in r["annotations"]:
                    d.rectangle(a["bbox_xyxy"], outline=colours[a["class_id"]], width=3)
                    d.text((a["bbox_xyxy"][0] + 4, a["bbox_xyxy"][1] + 4), a["class"], fill=colours[a["class_id"]])
                tx, ty = r["keypoints"]["target_px"]
                d.ellipse([tx - 6, ty - 6, tx + 6, ty + 6], fill="red")
                im.save(os.path.join(root, "qa", f"{r['frame_id']}_labels.png"))
            print(f"[RadTwin] QA images with labels drawn: {os.path.join(root, 'qa')}")
        except ImportError:
            print("[RadTwin] Pillow not available in Kit: skipped QA overlay images")

    missing = sum(1 for e in files if "image" not in e) if CAPTURE_IMAGES else 0
    print(f"[RadTwin] DONE: {len(records)} frames, splits {manifest['splits']}"
          + (f", {missing} images still writing (rerun hashing later)" if missing else ""))
    print(f"[RadTwin] Dataset: {root}")


if IN_OMNIVERSE:
    asyncio.ensure_future(generate())
else:  # testing outside Omniverse
    loop = asyncio.new_event_loop()
    loop.run_until_complete(generate())
    stage.GetRootLayer().Save()
