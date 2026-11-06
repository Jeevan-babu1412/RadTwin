# RadTwin - Autonomous positioning (Module M3)
# Run in RadTwin Composer: Window > Script Editor > paste > Run  (physics stopped)
# Change EXAM and run again. Works with every patient variant (child ... adult_large).

EXAM = "chest_ap"   # try: skull_ap, chest_ap, abdomen_ap, pelvis_ap, knee_ap

import asyncio
from pxr import Usd, UsdGeom, Sdf, Gf

try:
    import omni.usd, omni.kit.app
    stage = omni.usd.get_context().get_stage()
    IN_OMNIVERSE = True
except ImportError:  # testing outside Omniverse
    import sys
    stage = Usd.Stage.Open(sys.argv[1])
    EXAM = sys.argv[2] if len(sys.argv) > 2 else EXAM
    IN_OMNIVERSE = False

R = "/World/ExamRoom"

# ---- Exam protocols ----
# body_cm = centre of the body part, measured from the top of the head (adult_medium)
PROTOCOLS = {
    "skull_ap":   {"body_cm": 11,  "table_cm": 82, "sid_cm": 100, "kVp": 75},
    "chest_ap":   {"body_cm": 54,  "table_cm": 80, "sid_cm": 100, "kVp": 85},
    "abdomen_ap": {"body_cm": 89,  "table_cm": 78, "sid_cm": 100, "kVp": 80},
    "pelvis_ap":  {"body_cm": 107, "table_cm": 78, "sid_cm": 100, "kVp": 80},
    "knee_ap":    {"body_cm": 154, "table_cm": 82, "sid_cm": 100, "kVp": 65},
}
SID_MAX = 120                # the tube may back off up to this distance for large patients
HEAD_TOP_X = -99.0           # where the patient's head top lies on the table
DETECTOR_BELOW_TABLE = 5.7
COLLIMATOR_DROP = 27.4
MATTRESS_ABOVE_TABLE = 9.0
BODY_THICKNESS = 35.0        # adult_medium, scaled by the variant
MIN_CLEARANCE = 10

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


def patient_info():
    patient = stage.GetPrimAtPath("/World/Patient")
    vs = patient.GetVariantSets()
    variant = vs.GetVariantSet("bodyType").GetVariantSelection() if vs.HasVariantSet("bodyType") else "adult_medium"
    body = stage.GetPrimAtPath("/World/Patient/Anchor/Body")
    scale = UsdGeom.XformCommonAPI(body).GetXformVectors(Usd.TimeCode.Default())[2] if body else Gf.Vec3f(1, 1, 1)
    return variant, scale


def current_state():
    h = stage.GetPrimAtPath(f"{R}/PatientTable/TableTop").GetAttribute("radtwin:heightCm").Get() or 80.0
    tube = get_pos(f"{R}/XrayTube/TubeHousing")
    return h, tube[0], tube[1]


def plan(exam, scale):
    p = PROTOCOLS[exam]
    h1 = p["table_cm"]
    tx1 = HEAD_TOP_X + p["body_cm"] * scale[0]                  # body part moves with patient length
    patient_top = h1 + MATTRESS_ABOVE_TABLE + BODY_THICKNESS * scale[1]
    sid = p["sid_cm"]
    clearance = (h1 - DETECTOR_BELOW_TABLE + sid - COLLIMATOR_DROP) - patient_top
    if clearance < MIN_CLEARANCE:                               # back the tube off for a thicker patient
        sid = min(SID_MAX, sid + (MIN_CLEARANCE - clearance))
        clearance = (h1 - DETECTOR_BELOW_TABLE + sid - COLLIMATOR_DROP) - patient_top
    ty1 = h1 - DETECTOR_BELOW_TABLE + sid
    return h1, tx1, ty1, sid, clearance


async def next_frame():
    if IN_OMNIVERSE:
        await omni.kit.app.get_app().next_update_async()


async def run_exam(exam, seconds=2.5):
    if exam not in PROTOCOLS:
        print(f"Unknown exam '{exam}'. Choose from: {', '.join(PROTOCOLS)}")
        return
    variant, scale = patient_info()
    print(f"[RadTwin] Exam ordered: {exam} for patient '{variant}'  -> state: SCHEDULED")
    h0, tx0, ty0 = current_state()
    h1, tx1, ty1, sid, clearance = plan(exam, scale)

    if clearance < MIN_CLEARANCE:
        print(f"[RadTwin] BLOCKED: only {clearance:.1f} cm between collimator and patient even at SID {sid:.0f} cm.")
        set_twin("/World/Patient", "examState", "BLOCKED_COLLISION_RISK", Sdf.ValueTypeNames.String)
        return
    if sid != PROTOCOLS[exam]["sid_cm"]:
        print(f"[RadTwin] Patient is thicker than standard: SID increased to {sid:.0f} cm for safe clearance.")

    print(f"[RadTwin] state: POSITIONING  table {h0:.0f}->{h1:.0f} cm, tube x {tx0:.0f}->{tx1:.0f} cm, "
          f"SID {sid:.0f} cm, clearance {clearance:.0f} cm")

    steps = max(1, int(seconds * 60))
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

    set_twin(f"{R}/PatientTable/TableTop", "heightCm", float(h1))
    set_twin(f"{R}/XrayTube/TubeHousing", "positionXCm", float(tx1))
    set_twin(f"{R}/XrayTube/TubeHousing", "sidCm", float(sid))
    set_twin(f"{R}/XrayTube/TubeHousing", "kVp", float(PROTOCOLS[exam]["kVp"]))
    set_twin("/World/Patient", "examProtocol", exam, Sdf.ValueTypeNames.String)
    set_twin("/World/Patient", "examState", "READY_TO_ACQUIRE", Sdf.ValueTypeNames.String)
    print(f"[RadTwin] state: READY_TO_ACQUIRE  ({exam}, {variant})")


if IN_OMNIVERSE:
    asyncio.ensure_future(run_exam(EXAM))
else:  # testing outside Omniverse
    loop = asyncio.new_event_loop()
    loop.run_until_complete(run_exam(EXAM, seconds=0.05))
    stage.GetRootLayer().Save()
