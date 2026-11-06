# RadTwin - Hospital standards loop (Module M6)
#   HL7 v2 order in  ->  pick patient + exam  ->  autonomous positioning  ->  capture
#   ->  DICOM out  ->  anonymised DICOM copy  ->  compliance note
# Run in RadTwin Composer: Window > Script Editor > paste > Run  (physics stopped, save first)
# First run installs pydicom + Pillow into Omniverse's Python (needs internet, about 1 minute).
# Output: <folder of your .usd>/hl7_dicom/<accession number>/

# A synthetic HL7 v2.5.1 order (ORM^O01). Edit OBR-4 (exam code) or OBX weight/height to test.
HL7_ORDER = "\r".join([
    "MSH|^~\\&|RIS|RADTWIN_HOSP|RADTWIN|XRAY_ROOM_1|20261106101500||ORM^O01|MSG00001|P|2.5.1",
    "PID|1||SYN-000123^^^RADTWIN||SYNTHETIC^PATIENT01||19880412|F",
    "PV1|1|O|XR1",
    "ORC|NW|ORD-5001",
    "OBR|1|ORD-5001||XRCHEST^Chest AP^RADTWIN|||20261106101500",
    "OBX|1|NM|29463-7^Body weight^LN||62|kg",
    "OBX|2|NM|8302-2^Body height^LN||165|cm",
])

import asyncio, copy, datetime, hashlib, os
from pxr import Usd, UsdGeom, Sdf, Gf

try:
    import omni.usd, omni.kit.app
    stage = omni.usd.get_context().get_stage()
    IN_OMNIVERSE = True
except ImportError:  # testing outside Omniverse
    import sys
    stage = Usd.Stage.Open(sys.argv[1])
    TEST_IMAGE = sys.argv[2] if len(sys.argv) > 2 else None
    IN_OMNIVERSE = False


def need(module, package):
    try:
        return __import__(module)
    except ImportError:
        import omni.kit.pipapi
        print(f"[RadTwin] Installing {package} into Omniverse Python ...")
        omni.kit.pipapi.install(package, module=module)
        return __import__(module)


pydicom = need("pydicom", "pydicom")
need("PIL", "Pillow")
from PIL import Image
import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, SecondaryCaptureImageStorage

R = "/World/ExamRoom"
EXAM_CODES = {"XRSKULL": "skull_ap", "XRCHEST": "chest_ap", "XRABD": "abdomen_ap",
              "XRPELV": "pelvis_ap", "XRKNEE": "knee_ap"}
BODY_PART = {"skull_ap": "SKULL", "chest_ap": "CHEST", "abdomen_ap": "ABDOMEN",
             "pelvis_ap": "PELVIS", "knee_ap": "KNEE"}
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


# ---------------- 1. HL7: read the order ----------------
def parse_hl7(msg):
    segs = {}
    for line in msg.replace("\n", "\r").split("\r"):
        if line.strip():
            f = line.split("|")
            segs.setdefault(f[0], []).append(f)
    pid, obr, orc = segs["PID"][0], segs["OBR"][0], segs["ORC"][0]
    obs = {o[3].split("^")[0]: float(o[5]) for o in segs.get("OBX", [])}
    return {
        "message_type": segs["MSH"][0][8],
        "patient_id": pid[3].split("^")[0],
        "patient_name": pid[5],
        "birth_date": pid[7],
        "sex": pid[8] if len(pid) > 8 else "O",
        "accession": orc[2],
        "exam_code": obr[4].split("^")[0],
        "exam_text": obr[4].split("^")[1] if "^" in obr[4] else obr[4],
        "weight_kg": obs.get("29463-7"),
        "height_cm": obs.get("8302-2"),
    }


def choose_body_type(order):
    born = datetime.datetime.strptime(order["birth_date"], "%Y%m%d").date()
    age = (datetime.date.today() - born).days // 365
    w = order["weight_kg"] or 70
    if age < 16:
        return "child", age
    return ("adult_small" if w < 60 else "adult_medium" if w < 90 else "adult_large"), age


# ---------------- 2. positioning (same logic as auto_position.py) ----------------
def get_xf(path):
    return UsdGeom.XformCommonAPI(stage.GetPrimAtPath(path)).GetXformVectors(Usd.TimeCode.Default())


def shift(path, dx, dy):
    prim = stage.GetPrimAtPath(path)
    if prim:
        t = get_xf(path)[0]
        UsdGeom.XformCommonAPI(prim).SetTranslate(Gf.Vec3d(t[0] + dx, t[1] + dy, t[2]))


def set_twin(path, name, value, typ=Sdf.ValueTypeNames.Float):
    stage.GetPrimAtPath(path).CreateAttribute(f"radtwin:{name}", typ).Set(value)


def plan(exam, scale):
    p = PROTOCOLS[exam]
    h1 = p["table_cm"]
    tx1 = HEAD_TOP_X + p["body_cm"] * scale[0]
    patient_top = h1 + MATTRESS_ABOVE_TABLE + BODY_THICKNESS * scale[1]
    sid = p["sid_cm"]
    clearance = (h1 - DETECTOR_BELOW_TABLE + sid - COLLIMATOR_DROP) - patient_top
    if clearance < MIN_CLEARANCE:
        sid = min(SID_MAX, sid + (MIN_CLEARANCE - clearance))
        clearance = (h1 - DETECTOR_BELOW_TABLE + sid - COLLIMATOR_DROP) - patient_top
    ok = clearance >= MIN_CLEARANCE - 1e-6
    return h1, tx1, h1 - DETECTOR_BELOW_TABLE + sid, sid, clearance, ok


async def frames(n):
    if IN_OMNIVERSE:
        for _ in range(n):
            await omni.kit.app.get_app().next_update_async()


async def move(h1, tx1, ty1, seconds=2.0):
    h0 = stage.GetPrimAtPath(f"{R}/PatientTable/TableTop").GetAttribute("radtwin:heightCm").Get() or 80.0
    t = get_xf(f"{R}/XrayTube/TubeHousing")[0]
    tx0, ty0 = t[0], t[1]
    steps = int(seconds * 60) if IN_OMNIVERSE else 1
    ph, px, py = h0, tx0, ty0
    for i in range(1, steps + 1):
        e = (i / steps) ** 2 * (3 - 2 * i / steps)
        h, x, y = h0 + (h1 - h0) * e, tx0 + (tx1 - tx0) * e, ty0 + (ty1 - ty0) * e
        for p in TABLE_TOP: shift(p, 0, h - ph)
        for p in TRAY: shift(p, x - px, h - ph)
        for p in TUBE_SLIDE: shift(p, x - px, 0)
        for p in TUBE_HEAD: shift(p, x - px, y - py)
        ph, px, py = h, x, y
        await frames(1)
    set_twin(f"{R}/PatientTable/TableTop", "heightCm", float(h1))


# ---------------- 3. DICOM: write the image like a real modality would ----------------
def write_dicom(path, pixels, order, exam, sid, age):
    now = datetime.datetime.now()
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    # patient (from HL7 PID / OBX)
    ds.PatientName = order["patient_name"]
    ds.PatientID = order["patient_id"]
    ds.PatientBirthDate = order["birth_date"]
    ds.PatientSex = order["sex"]
    ds.PatientAge = f"{age:03d}Y"
    if order["weight_kg"]: ds.PatientWeight = order["weight_kg"]
    if order["height_cm"]: ds.PatientSize = round(order["height_cm"] / 100, 2)
    # study / series (from HL7 ORC / OBR)
    ds.AccessionNumber = order["accession"]
    ds.StudyDate = ds.SeriesDate = ds.ContentDate = now.strftime("%Y%m%d")
    ds.StudyTime = ds.SeriesTime = ds.ContentTime = now.strftime("%H%M%S")
    ds.StudyDescription = order["exam_text"]
    ds.SeriesDescription = "RadTwin simulated acquisition view"
    ds.StudyID, ds.SeriesNumber, ds.InstanceNumber = "1", 1, 1
    ds.Modality = "OT"                       # simulated view, not a real radiograph
    ds.ConversionType = "SYN"                # synthetic image
    ds.BodyPartExamined = BODY_PART[exam]
    ds.KVP = PROTOCOLS[exam]["kVp"]
    ds.DistanceSourceToDetector = round(sid * 10, 1)   # DICOM uses mm
    ds.Manufacturer, ds.InstitutionName = "RadTwin (simulation)", "RADTWIN_HOSP"
    ds.ImageComments = "SYNTHETIC - generated by RadTwin digital twin. Not for clinical use."
    # pixels
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 8, 8, 7, 0
    ds.PixelData = pixels.astype(np.uint8).tobytes()
    save(ds, path)
    return ds


def save(ds, path):
    try:
        ds.save_as(path, enforce_file_format=True)     # pydicom 3
    except TypeError:
        ds.is_little_endian, ds.is_implicit_VR = True, False
        ds.save_as(path, write_like_original=False)    # pydicom 2


def anonymise(ds, path):
    """Basic de-identification: remove direct identifiers, pseudonymise the ID, new UIDs.
    (A production system would apply the full DICOM PS3.15 Annex E profile.)"""
    a = copy.deepcopy(ds)
    pseudo = "ANON-" + hashlib.sha256(ds.PatientID.encode()).hexdigest()[:10].upper()
    a.PatientName, a.PatientID = "ANONYMOUS", pseudo
    for tag in ["PatientBirthDate", "AccessionNumber", "InstitutionName"]:
        if tag in a:
            delattr(a, tag)
    a.StudyInstanceUID, a.SeriesInstanceUID = generate_uid(), generate_uid()
    a.SOPInstanceUID = a.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    a.PatientIdentityRemoved = "YES"
    a.DeidentificationMethod = "RadTwin basic de-identification v0.1"   # details in COMPLIANCE.md
    save(a, path)
    return a


COMPLIANCE = """# RadTwin - compliance notes (simulation platform)

This platform generates **synthetic** data. No real patient data enters it, which removes most
privacy risk by design. When it connects to real systems, these apply:

| Area | Standard / law | How RadTwin handles it |
|---|---|---|
| Patient privacy (US) | HIPAA Privacy and Security Rules | Synthetic patients only; de-identification before data leaves the platform |
| Patient privacy (India) | Digital Personal Data Protection Act, 2023 | Same: no personal data processed; purpose-limited, logged access if real data is ever used |
| Patient privacy (EU) | GDPR | Pseudonymised IDs, data minimisation, right-to-erasure path for any real data |
| Image de-identification | DICOM PS3.15 Annex E | Basic version here (name, birth date, accession, institution removed; ID pseudonymised; UIDs replaced); full profile required in production |
| Orders and workflow | HL7 v2 (ORM/ORU), IHE Scheduled Workflow (SWF) | Orders read from HL7; study links via accession number |
| Medical device software | IEC 62304 | Versioned code, traceable requirements, tested releases |
| Risk management | ISO 14971 | Collision and positioning risks checked in simulation (clearance rule, BLOCKED state) |
| Quality system | ISO 13485 | Dataset manifests, hashes and run logs as traceable evidence |
| AI-enabled devices | FDA / EU MDR guidance on AI/ML | Synthetic data documented (seed, version, distribution) for model validation |

Every simulated DICOM is marked `ConversionType = SYN` and carries
"SYNTHETIC ... Not for clinical use." in ImageComments.
"""


async def main():
    order = parse_hl7(HL7_ORDER)
    exam = EXAM_CODES.get(order["exam_code"])
    if not exam:
        print(f"[RadTwin] Unknown exam code {order['exam_code']}"); return
    body_type, age = choose_body_type(order)
    print(f"[RadTwin] HL7 {order['message_type']} received: accession {order['accession']}, "
          f"exam {order['exam_code']} -> {exam}, patient age {age}, {order['weight_kg']} kg -> {body_type}")

    patient = stage.GetPrimAtPath("/World/Patient")
    patient.GetVariantSets().GetVariantSet("bodyType").SetVariantSelection(body_type)
    scale = get_xf("/World/Patient/Anchor/Body")[2]
    h1, tx1, ty1, sid, clearance, ok = plan(exam, scale)
    if not ok:
        print(f"[RadTwin] BLOCKED: clearance {clearance:.1f} cm"); return
    print(f"[RadTwin] Positioning: table {h1} cm, tube x {tx1:.0f} cm, SID {sid:.1f} cm, clearance {clearance:.0f} cm")
    await move(h1, tx1, ty1)
    set_twin("/World/Patient", "examState", "ACQUIRED", Sdf.ValueTypeNames.String)
    set_twin("/World/Patient", "accession", order["accession"], Sdf.ValueTypeNames.String)

    layer_path = stage.GetRootLayer().realPath
    base = os.path.dirname(layer_path) if layer_path else os.path.expanduser("~")
    folder = os.path.join(base, "hl7_dicom", order["accession"])
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "order.hl7"), "w") as f:
        f.write(HL7_ORDER.replace("\r", "\n"))

    png = os.path.join(folder, "capture.png")
    if IN_OMNIVERSE:
        from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file
        await frames(10)
        capture_viewport_to_file(get_active_viewport(), png)
        for _ in range(120):                     # wait until the file is written
            await frames(1)
            if os.path.exists(png) and os.path.getsize(png) > 0:
                break
        await frames(5)
    elif TEST_IMAGE:
        Image.open(TEST_IMAGE).save(png)
    pixels = np.array(Image.open(png).convert("L"))

    ds = write_dicom(os.path.join(folder, "image.dcm"), pixels, order, exam, sid, age)
    anon = anonymise(ds, os.path.join(folder, "image_anonymised.dcm"))
    with open(os.path.join(folder, "COMPLIANCE.md"), "w") as f:
        f.write(COMPLIANCE)

    print("[RadTwin] DICOM written. Key tags:")
    for tag in ["PatientName", "PatientID", "PatientAge", "AccessionNumber", "Modality", "BodyPartExamined",
                "KVP", "DistanceSourceToDetector", "Rows", "Columns"]:
        print(f"    {tag:<26} {getattr(ds, tag, '')}")
    print(f"[RadTwin] Anonymised copy: PatientName={anon.PatientName}, PatientID={anon.PatientID}, "
          f"BirthDate={'removed' if 'PatientBirthDate' not in anon else anon.PatientBirthDate}")
    print(f"[RadTwin] Output: {folder}")


if IN_OMNIVERSE:
    asyncio.ensure_future(main())
else:  # testing outside Omniverse
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
