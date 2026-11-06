# RadTwin - Patient variants (Module M1: virtual patient population)
# Rebuilds /World/Patient as ONE asset with a USD variant set "bodyType".
# Run in RadTwin Composer: Window > Script Editor > paste > Run  (physics stopped)
# Switch variants later in the "Variant Presenter" tab, or change BODY_TYPE and run again.

BODY_TYPE = "adult_medium"   # child, adult_small, adult_medium, adult_large

from pxr import Usd, UsdGeom, UsdShade, UsdPhysics, Sdf, Gf

try:
    import omni.usd
    stage = omni.usd.get_context().get_stage()
    IN_OMNIVERSE = True
except ImportError:  # testing outside Omniverse
    import sys
    stage = Usd.Stage.Open(sys.argv[1])
    BODY_TYPE = sys.argv[2] if len(sys.argv) > 2 else BODY_TYPE
    IN_OMNIVERSE = False

# ---- The patient population: each variant = one body type ----
VARIANTS = {
    #               scale (length, thickness, width)   mass   height  age group
    "child":        {"scale": (0.62, 0.60, 0.62), "massKg": 22.0,  "heightCm": 110.0, "ageGroup": "child"},
    "adult_small":  {"scale": (0.92, 0.90, 0.90), "massKg": 55.0,  "heightCm": 160.0, "ageGroup": "adult"},
    "adult_medium": {"scale": (1.00, 1.00, 1.00), "massKg": 70.0,  "heightCm": 175.0, "ageGroup": "adult"},
    "adult_large":  {"scale": (1.05, 1.25, 1.30), "massKg": 110.0, "heightCm": 180.0, "ageGroup": "adult"},
}

PT = "/World/Patient"
ANCHOR = f"{PT}/Anchor"     # head-end of the mattress; body scales from here
BODY = f"{ANCHOR}/Body"     # scale lives only inside the variants

# keep the patient on the table at its current height
tabletop = stage.GetPrimAtPath("/World/ExamRoom/PatientTable/TableTop")
table_h = (tabletop.GetAttribute("radtwin:heightCm").Get() if tabletop else None) or 80.0

if stage.GetPrimAtPath(PT):
    stage.RemovePrim(PT)

patient_x = UsdGeom.Xform.Define(stage, PT)
UsdGeom.XformCommonAPI(patient_x).SetTranslate(Gf.Vec3d(0, table_h - 80.0, 0))
anchor = UsdGeom.Xform.Define(stage, ANCHOR)
UsdGeom.XformCommonAPI(anchor).SetTranslate(Gf.Vec3d(-99.0, 89.0, 0))   # head top, mattress surface
UsdGeom.Xform.Define(stage, BODY)

skin = UsdShade.Material.Get(stage, "/World/Looks/Mannequin")
gown = UsdShade.Material.Get(stage, "/World/Looks/PatientGown")

def bind(prim, mat):
    if mat:
        UsdShade.MaterialBindingAPI.Apply(prim)
        UsdShade.MaterialBindingAPI(prim).Bind(mat)

def part(name, kind, pos, mat, **dims):
    path = f"{BODY}/{name}"
    if kind == "sphere":
        g = UsdGeom.Sphere.Define(stage, path); g.GetRadiusAttr().Set(dims["r"])
    elif kind == "capsule":
        g = UsdGeom.Capsule.Define(stage, path)
        g.GetRadiusAttr().Set(dims["r"]); g.GetHeightAttr().Set(dims["h"]); g.GetAxisAttr().Set("X")
    else:
        g = UsdGeom.Cube.Define(stage, path); g.GetSizeAttr().Set(1.0)
    api = UsdGeom.XformCommonAPI(g)
    api.SetTranslate(Gf.Vec3d(*pos))
    if kind == "box":
        api.SetScale(Gf.Vec3f(*dims["size"]))
    bind(g.GetPrim(), mat)
    UsdPhysics.CollisionAPI.Apply(g.GetPrim())

# positions are relative to the head top on the mattress (x along the body, y up)
part("Head",   "sphere",  (11, 19.5, 0),   skin, r=11)
part("Neck",   "capsule", (26, 17.5, 0),   skin, r=5, h=4)
part("Torso",  "capsule", (62, 17.5, 0),   gown, r=17, h=40)
part("Pelvis", "capsule", (104, 15.5, 0),  gown, r=15, h=10)
part("ArmL",   "capsule", (69, 10.5, 25),  skin, r=5.5, h=48)
part("ArmR",   "capsule", (69, 10.5, -25), skin, r=5.5, h=48)
part("LegL",   "capsule", (159, 10.5, 10), gown, r=7.5, h=72)
part("LegR",   "capsule", (159, 10.5, -10), gown, r=7.5, h=72)
part("FootL",  "box",     (205, 15.5, 10), skin, size=(6, 14, 9))
part("FootR",  "box",     (205, 15.5, -10), skin, size=(6, 14, 9))

# ---- physics: the whole patient is one rigid body ----
patient = stage.GetPrimAtPath(PT)
UsdPhysics.RigidBodyAPI.Apply(patient)
mass_api = UsdPhysics.MassAPI.Apply(patient)

# ---- the variant set: only the differences are authored inside each variant ----
vset = patient.GetVariantSets().AddVariantSet("bodyType")
for name, v in VARIANTS.items():
    vset.AddVariant(name)
    vset.SetVariantSelection(name)
    with vset.GetVariantEditContext():
        UsdGeom.XformCommonAPI(stage.GetPrimAtPath(BODY)).SetScale(Gf.Vec3f(*v["scale"]))
        mass_api.CreateMassAttr().Set(v["massKg"])
        patient.CreateAttribute("radtwin:heightCm", Sdf.ValueTypeNames.Float).Set(v["heightCm"])
        patient.CreateAttribute("radtwin:massKg", Sdf.ValueTypeNames.Float).Set(v["massKg"])
        patient.CreateAttribute("radtwin:ageGroup", Sdf.ValueTypeNames.String).Set(v["ageGroup"])
vset.SetVariantSelection(BODY_TYPE)

print(f"[RadTwin] Patient rebuilt with variant set 'bodyType' {list(VARIANTS)}; selected: {BODY_TYPE}")

if not IN_OMNIVERSE:
    stage.GetRootLayer().Save()
