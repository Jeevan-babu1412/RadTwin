# RadTwin - Exam Room v2 (realistic shapes + materials)
# Run in RadTwin Composer: Window > Script Editor > paste > Run
# Units: centimetres, Y is up.

from pxr import Usd, UsdGeom, UsdShade, UsdPhysics, Sdf, Gf

try:
    import omni.usd
    stage = omni.usd.get_context().get_stage()
    IN_OMNIVERSE = True
except ImportError:
    IN_OMNIVERSE = False  # lets the script also run outside Omniverse for testing
    import sys
    stage = Usd.Stage.CreateNew(sys.argv[1] if len(sys.argv) > 1 else "exam_room_v2.usda")
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)

# ---------- clean up the old placeholder version ----------
for old in ["/World/ExamRoom", "/World/Patient", "/World/Looks"]:
    if stage.GetPrimAtPath(old):
        stage.RemovePrim(old)

UsdGeom.Xform.Define(stage, "/World")
UsdGeom.Xform.Define(stage, "/World/ExamRoom")
UsdGeom.Scope.Define(stage, "/World/Looks")

# ---------- materials (UsdPreviewSurface works in RTX) ----------
def make_mat(name, color, rough=0.5, metal=0.0, opacity=1.0, emissive=None):
    mat = UsdShade.Material.Define(stage, f"/World/Looks/{name}")
    sh = UsdShade.Shader.Define(stage, f"/World/Looks/{name}/Shader")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(rough)
    sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metal)
    sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
    if emissive:
        sh.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emissive))
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    return mat

M = {
    "floor":    make_mat("FloorVinyl",   (0.62, 0.66, 0.68), rough=0.45),
    "wall":     make_mat("WallPaint",    (0.80, 0.87, 0.89), rough=0.85),
    "white":    make_mat("MedicalWhite", (0.92, 0.93, 0.94), rough=0.30),
    "grey":     make_mat("CoverGrey",    (0.55, 0.58, 0.62), rough=0.40),
    "dark":     make_mat("DarkTrim",     (0.12, 0.13, 0.15), rough=0.50),
    "metal":    make_mat("BrushedMetal", (0.75, 0.76, 0.78), rough=0.25, metal=1.0),
    "mattress": make_mat("Mattress",     (0.10, 0.28, 0.45), rough=0.70),
    "panel":    make_mat("DetectorFace", (0.20, 0.22, 0.25), rough=0.35),
    "glass":    make_mat("LeadGlass",    (0.55, 0.70, 0.75), rough=0.05, opacity=0.35),
    "light":    make_mat("CollimatorLight", (1.0, 0.95, 0.70), rough=0.2, emissive=(1.0, 0.9, 0.6)),
    "screen":   make_mat("Screen",       (0.05, 0.10, 0.18), rough=0.1, emissive=(0.05, 0.25, 0.45)),
    "skin":     make_mat("Mannequin",    (0.78, 0.68, 0.60), rough=0.60),
    "gown":     make_mat("PatientGown",  (0.55, 0.72, 0.85), rough=0.80),
    "accent":   make_mat("AccentBlue",   (0.10, 0.45, 0.80), rough=0.35),
}

def bind(prim, mat):
    UsdShade.MaterialBindingAPI.Apply(prim)
    UsdShade.MaterialBindingAPI(prim).Bind(mat)

def place(geom, pos, rot=(0, 0, 0), scale=None):
    api = UsdGeom.XformCommonAPI(geom)
    api.SetTranslate(Gf.Vec3d(*pos))
    if rot != (0, 0, 0):
        api.SetRotate(Gf.Vec3f(*rot))
    if scale:
        api.SetScale(Gf.Vec3f(*scale))

def box(path, size, pos, mat, rot=(0, 0, 0)):
    g = UsdGeom.Cube.Define(stage, path)
    g.GetSizeAttr().Set(1.0)
    place(g, pos, rot, size)
    bind(g.GetPrim(), mat)
    return g

def cyl(path, radius, height, pos, mat, axis="Y"):
    g = UsdGeom.Cylinder.Define(stage, path)
    g.GetRadiusAttr().Set(radius); g.GetHeightAttr().Set(height); g.GetAxisAttr().Set(axis)
    place(g, pos); bind(g.GetPrim(), mat)
    return g

def capsule(path, radius, height, pos, mat, axis="X"):
    g = UsdGeom.Capsule.Define(stage, path)
    g.GetRadiusAttr().Set(radius); g.GetHeightAttr().Set(height); g.GetAxisAttr().Set(axis)
    place(g, pos); bind(g.GetPrim(), mat)
    return g

def sphere(path, radius, pos, mat):
    g = UsdGeom.Sphere.Define(stage, path)
    g.GetRadiusAttr().Set(radius)
    place(g, pos); bind(g.GetPrim(), mat)
    return g

R = "/World/ExamRoom"

# ---------- 1. ROOM ----------
UsdGeom.Xform.Define(stage, f"{R}/Room")
floor = box(f"{R}/Room/Floor", (600, 2, 500), (0, -1, 0), M["floor"])
box(f"{R}/Room/BackWall", (600, 300, 6), (0, 150, -253), M["wall"])
box(f"{R}/Room/LeftWall", (6, 300, 500), (-303, 150, 0), M["wall"])
box(f"{R}/Room/SkirtingBack", (600, 10, 2), (0, 5, -249), M["grey"])
box(f"{R}/Room/SkirtingLeft", (2, 10, 500), (-299, 5, 0), M["grey"])
box(f"{R}/Room/LeadGlassWindow", (1, 90, 140), (-299.5, 150, 150), M["glass"])
box(f"{R}/Room/WindowFrameTop", (4, 4, 148), (-299, 197, 150), M["grey"])
box(f"{R}/Room/WindowFrameBottom", (4, 4, 148), (-299, 103, 150), M["grey"])
box(f"{R}/Room/WindowFrameL", (4, 98, 4), (-299, 150, 78), M["grey"])
box(f"{R}/Room/WindowFrameR", (4, 98, 4), (-299, 150, 222), M["grey"])

# ---------- 2. CEILING-MOUNTED X-RAY TUBE ----------
T = f"{R}/XrayTube"
UsdGeom.Xform.Define(stage, T)
TX = 20  # tube sits over the detector
box(f"{T}/RailA", (320, 4, 6), (0, 294, -45), M["metal"])
box(f"{T}/RailB", (320, 4, 6), (0, 294, 45), M["metal"])
box(f"{T}/Carriage", (50, 12, 100), (TX, 286, 0), M["white"])
cyl(f"{T}/ColumnOuter", 11, 70, (TX, 245, 0), M["white"])
cyl(f"{T}/ColumnInner", 8, 40, (TX, 195, 0), M["metal"])
tube = cyl(f"{T}/TubeHousing", 15, 52, (TX, 165, 0), M["white"], axis="Z")
cyl(f"{T}/TubeCapA", 15.5, 4, (TX, 165, 27), M["grey"], axis="Z")
cyl(f"{T}/TubeCapB", 15.5, 4, (TX, 165, -27), M["grey"], axis="Z")
box(f"{T}/Collimator", (28, 18, 28), (TX, 147, 0), M["grey"])
box(f"{T}/CollimatorLight", (22, 1, 22), (TX, 137.6, 0), M["light"])
box(f"{T}/ControlPanel", (2, 10, 16), (TX + 15, 149, 0), M["accent"])
cyl(f"{T}/HandleL", 1.6, 16, (TX - 22, 147, 0), M["dark"])
cyl(f"{T}/HandleR", 1.6, 16, (TX + 22, 147, 0), M["dark"])
box(f"{T}/HandleBarL", (8, 2, 2), (TX - 18, 155, 0), M["dark"])
box(f"{T}/HandleBarR", (8, 2, 2), (TX + 18, 155, 0), M["dark"])

# ---------- 3. PATIENT TABLE ----------
P = f"{R}/PatientTable"
UsdGeom.Xform.Define(stage, P)
box(f"{P}/FootPlate", (85, 4, 70), (-50, 2, 0), M["grey"])
box(f"{P}/Pedestal", (45, 70, 55), (-50, 39, 0), M["white"])
box(f"{P}/PedestalStripe", (46, 3, 56), (-50, 60, 0), M["accent"])
box(f"{P}/PedestalCap", (60, 3, 62), (-50, 75.5, 0), M["grey"])
tabletop = box(f"{P}/TableTop", (220, 6, 72), (0, 80, 0), M["white"])
mattress = box(f"{P}/Mattress", (200, 6, 62), (0, 86, 0), M["mattress"])
box(f"{P}/RailFront", (220, 2.5, 2), (0, 80, 37), M["metal"])
box(f"{P}/RailBack", (220, 2.5, 2), (0, 80, -37), M["metal"])
box(f"{P}/Pillow", (30, 8, 40), (-85, 92, 0), M["white"])

# Detector (bucky tray) under the table top
D = f"{R}/TableDetector"
UsdGeom.Xform.Define(stage, D)
detector = box(f"{D}/Tray", (48, 4, 48), (TX, 72, 0), M["dark"])
box(f"{D}/ActiveArea", (43, 0.5, 43), (TX, 74.3, 0), M["panel"])

# ---------- 4. WALL STAND (chest X-ray) ----------
W = f"{R}/WallStand"
UsdGeom.Xform.Define(stage, W)
box(f"{W}/Base", (50, 4, 40), (200, 2, -228), M["grey"])
box(f"{W}/Column", (14, 220, 12), (200, 110, -240), M["white"])
box(f"{W}/DetectorHousing", (58, 58, 10), (200, 140, -228), M["white"])
box(f"{W}/DetectorFace", (50, 50, 0.5), (200, 140, -222.8), M["panel"])
box(f"{W}/HandGripL", (3, 18, 3), (164, 150, -226), M["dark"])
box(f"{W}/HandGripR", (3, 18, 3), (236, 150, -226), M["dark"])

# ---------- 5. OPERATOR CONSOLE ----------
C = f"{R}/Console"
UsdGeom.Xform.Define(stage, C)
box(f"{C}/Desk", (60, 4, 120), (-255, 75, 150), M["white"])
box(f"{C}/DeskSide", (56, 73, 4), (-255, 36.5, 92), M["grey"])
box(f"{C}/DeskSide2", (56, 73, 4), (-255, 36.5, 208), M["grey"])
box(f"{C}/Monitor", (3, 32, 52), (-270, 105, 150), M["dark"], rot=(0, 0, -8))
box(f"{C}/MonitorScreen", (0.5, 28, 48), (-268.2, 105, 150), M["screen"], rot=(0, 0, -8))
box(f"{C}/MonitorStand", (3, 14, 6), (-272, 84, 150), M["dark"])
box(f"{C}/Keyboard", (16, 1.5, 40), (-245, 77.7, 150), M["dark"])

# ---------- 6. PATIENT (simple mannequin, one rigid body) ----------
PT = "/World/Patient"
UsdGeom.Xform.Define(stage, PT)
Y0 = 112  # starts slightly above the mattress so it settles under physics
sphere(f"{PT}/Head", 11, (-88, Y0, 0), M["skin"])
capsule(f"{PT}/Neck", 5, 4, (-73, Y0 - 2, 0), M["skin"])
capsule(f"{PT}/Torso", 17, 40, (-37, Y0 - 2, 0), M["gown"])
capsule(f"{PT}/Pelvis", 15, 10, (5, Y0 - 4, 0), M["gown"])
capsule(f"{PT}/ArmL", 5.5, 48, (-30, Y0 - 9, 25), M["skin"])
capsule(f"{PT}/ArmR", 5.5, 48, (-30, Y0 - 9, -25), M["skin"])
capsule(f"{PT}/LegL", 7.5, 72, (60, Y0 - 9, 10), M["gown"])
capsule(f"{PT}/LegR", 7.5, 72, (60, Y0 - 9, -10), M["gown"])
box(f"{PT}/FootL", (6, 14, 9), (106, Y0 - 4, 10), M["skin"])
box(f"{PT}/FootR", (6, 14, 9), (106, Y0 - 4, -10), M["skin"])

# ---------- 7. TWIN DATA (custom attributes) ----------
def attr(prim, name, typ, val):
    prim.CreateAttribute(f"radtwin:{name}", typ).Set(val)

attr(tabletop.GetPrim(), "heightCm", Sdf.ValueTypeNames.Float, 80.0)
attr(tabletop.GetPrim(), "maxLoadKg", Sdf.ValueTypeNames.Float, 250.0)
attr(tube.GetPrim(), "angleDeg", Sdf.ValueTypeNames.Float, 0.0)
attr(tube.GetPrim(), "kVp", Sdf.ValueTypeNames.Float, 70.0)
attr(detector.GetPrim(), "sizeCm", Sdf.ValueTypeNames.Float, 43.0)
attr(stage.GetPrimAtPath(PT), "variant", Sdf.ValueTypeNames.String, "adult_medium")

# ---------- 8. PHYSICS ----------
if not stage.GetPrimAtPath("/World/PhysicsScene"):
    scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(0, -1, 0))
    scene.CreateGravityMagnitudeAttr().Set(981.0)

for p in [floor, tabletop, mattress]:
    UsdPhysics.CollisionAPI.Apply(p.GetPrim())
UsdPhysics.CollisionAPI.Apply(stage.GetPrimAtPath(f"{P}/Pedestal"))

patient = stage.GetPrimAtPath(PT)
UsdPhysics.RigidBodyAPI.Apply(patient)
UsdPhysics.MassAPI.Apply(patient).CreateMassAttr(70.0)
for child in patient.GetChildren():
    UsdPhysics.CollisionAPI.Apply(child)

if not IN_OMNIVERSE:
    stage.GetRootLayer().Save()

print("RadTwin exam room v2 built: room, ceiling X-ray tube, table, detector, wall stand, console, patient")
