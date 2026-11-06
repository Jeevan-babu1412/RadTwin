# RadTwin - Scenario runner (autonomous imaging validation)
# Runs EVERY patient variant x EVERY exam automatically:
#   select patient -> plan positions -> safety check -> move -> capture -> log
# Run in RadTwin Composer: Window > Script Editor > paste > Run  (physics stopped)
# Results: <folder of your .usd>/scenario_runs/run_<time>/results.csv (+ one image per scenario)

PATIENTS = ["child", "adult_small", "adult_medium", "adult_large"]
EXAMS = ["skull_ap", "chest_ap", "abdomen_ap", "pelvis_ap", "knee_ap"]
MOVE_SECONDS = 1.0
CAPTURE_IMAGES = True          # set False if the laptop runs short of memory

import asyncio, csv, os, time
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
PROTOCOLS = {
    "skull_ap":   {"body_cm": 11,  "table_cm": 82, "sid_cm": 100, "kVp": 75},
    "chest_ap":   {"body_cm": 54,  "table_cm": 80, "sid_cm": 100, "kVp": 85},
    "abdomen_ap": {"body_cm": 89,  "table_cm": 78, "sid_cm": 100, "kVp": 80},
    "pelvis_ap":  {"body_cm": 107, "table_cm": 78, "sid_cm": 100, "kVp": 80},
    "knee_ap":    {"body_cm": 154, "table_cm": 82, "sid_cm": 100, "kVp": 65},
}
SID_MAX = 120
HEAD_TOP_X = -99.0
DETECTOR_BELOW_TABLE = 5.7
COLLIMATOR_DROP = 27.4
MATTRESS_ABOVE_TABLE = 9.0
BODY_THICKNESS = 35.0
MIN_CLEARANCE = 15

TABLE_TOP = [f"{R}/PatientTable/{n}" for n in
             ["TableTop", "Mattress", "RailFront", "RailBack", "Pillow", "PedestalCap"]] + ["/World/Patient"]
TRAY = [f"{R}/TableDetector/Tray", f"{R}/TableDetector/ActiveArea"]
TUBE_SLIDE = [f"{R}/XrayTube/{n}" for n in ["Carriage", "ColumnOuter"]]
TUBE_HEAD = [f"{R}/XrayTube/{n}" for n in
             ["ColumnInner", "TubeHousing", "TubeCapA", "TubeCapB", "Collimator", "CollimatorLight",
              "ControlPanel", "HandleL", "HandleR", "HandleBarL", "HandleBarR"]]


def get_pos(path):
    return UsdGeom.XformCommonAPI(stage.GetPrimAtPath(path)).GetXformVectors(Usd.TimeCode.Default())[0]


def shift(path, dx, dy):
    prim = stage.GetPrimAtPath(path)
    if prim:
        t = get_pos(path)
        UsdGeom.XformCommonAPI(prim).SetTranslate(Gf.Vec3d(t[0] + dx, t[1] + dy, t[2]))


def set_twin(path, name, value, typ=Sdf.ValueTypeNames.Float):
    stage.GetPrimAtPath(path).CreateAttribute(f"radtwin:{name}", typ).Set(value)


def select_patient(variant):
    stage.GetPrimAtPath("/World/Patient").GetVariantSets().GetVariantSet("bodyType").SetVariantSelection(variant)
    body = stage.GetPrimAtPath("/World/Patient/Anchor/Body")
    return UsdGeom.XformCommonAPI(body).GetXformVectors(Usd.TimeCode.Default())[2]


def current_state():
    h = stage.GetPrimAtPath(f"{R}/PatientTable/TableTop").GetAttribute("radtwin:heightCm").Get() or 80.0
    tube = get_pos(f"{R}/XrayTube/TubeHousing")
    return h, tube[0], tube[1]


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
    return h1, tx1, h1 - DETECTOR_BELOW_TABLE + sid, sid, clearance, status


async def next_frame():
    if IN_OMNIVERSE:
        await omni.kit.app.get_app().next_update_async()


async def move(h0, tx0, ty0, h1, tx1, ty1, seconds):
    steps = max(1, int(seconds * 60)) if IN_OMNIVERSE else 1
    ph, px, py = h0, tx0, ty0
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)
        h, x, y = h0 + (h1 - h0) * e, tx0 + (tx1 - tx0) * e, ty0 + (ty1 - ty0) * e
        dh, dx, dy = h - ph, x - px, y - py
        for p in TABLE_TOP: shift(p, 0, dh)
        for p in TRAY: shift(p, dx, dh)
        for p in TUBE_SLIDE: shift(p, dx, 0)
        for p in TUBE_HEAD: shift(p, dx, dy)
        ph, px, py = h, x, y
        await next_frame()


async def capture(path):
    try:
        from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file
        for _ in range(10):                      # let RTX settle for a few frames
            await next_frame()
        capture_viewport_to_file(get_active_viewport(), path)
        for _ in range(5):
            await next_frame()
        return os.path.basename(path)
    except Exception as e:
        print(f"[RadTwin] image capture skipped: {e}")
        return ""


def output_folder():
    layer_path = stage.GetRootLayer().realPath
    base = os.path.dirname(layer_path) if layer_path else os.path.expanduser("~")
    folder = os.path.join(base, "scenario_runs", time.strftime("run_%Y%m%d_%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    return folder


async def run_all():
    folder = output_folder()
    rows, n = [], 0
    total = len(PATIENTS) * len(EXAMS)
    print(f"[RadTwin] Scenario run started: {total} scenarios -> {folder}")
    start = time.time()
    for variant in PATIENTS:
        scale = select_patient(variant)
        await next_frame()
        for exam in EXAMS:
            n += 1
            h0, tx0, ty0 = current_state()
            h1, tx1, ty1, sid, clearance, status = plan(exam, scale)
            if status != "BLOCKED_COLLISION_RISK":
                await move(h0, tx0, ty0, h1, tx1, ty1, MOVE_SECONDS)
                set_twin(f"{R}/PatientTable/TableTop", "heightCm", float(h1))
            set_twin("/World/Patient", "examProtocol", exam, Sdf.ValueTypeNames.String)
            set_twin("/World/Patient", "examState", status, Sdf.ValueTypeNames.String)
            image = await capture(os.path.join(folder, f"{n:02d}_{variant}_{exam}.png")) if CAPTURE_IMAGES else ""
            rows.append({"scenario": n, "patient": variant, "exam": exam, "table_cm": round(h1, 1),
                         "tube_x_cm": round(tx1, 1), "sid_cm": round(sid, 1), "clearance_cm": round(clearance, 1),
                         "kVp": PROTOCOLS[exam]["kVp"], "status": status, "image": image})
            print(f"[RadTwin] {n:02d}/{total}  {variant:<13} {exam:<11} SID {sid:5.1f}  "
                  f"clearance {clearance:5.1f} cm  -> {status}")

    with open(os.path.join(folder, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    ready = sum(r["status"] == "READY" for r in rows)
    adjusted = sum(r["status"] == "READY_SID_ADJUSTED" for r in rows)
    blocked = sum(r["status"] == "BLOCKED_COLLISION_RISK" for r in rows)
    print(f"[RadTwin] DONE in {time.time() - start:.0f}s: {ready} ready, {adjusted} SID-adjusted, {blocked} blocked")
    print(f"[RadTwin] Results: {os.path.join(folder, 'results.csv')}")


if IN_OMNIVERSE:
    asyncio.ensure_future(run_all())
else:  # testing outside Omniverse
    loop = asyncio.new_event_loop()
    loop.run_until_complete(run_all())
