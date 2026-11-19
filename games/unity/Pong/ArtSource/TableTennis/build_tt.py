import bpy, bmesh, math, os, mathutils

OUT = os.environ["NT_OUT"]
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"


def mat(name, color, rough=0.5, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*color, 1)
    return m


M_TOP = mat("TT_Top", (0.012, 0.09, 0.30), 0.35)
M_LINE = mat("TT_Line", (0.9, 0.9, 0.9), 0.4)
M_EDGE = mat("TT_Edge", (0.02, 0.025, 0.04), 0.5)
M_FRAME = mat("TT_Frame", (0.55, 0.57, 0.6), 0.35, 0.8)
M_NETTAPE = mat("TT_NetTape", (0.95, 0.95, 0.95), 0.6)
M_WOOD = mat("TT_Wood", (0.62, 0.42, 0.22), 0.55)
M_RUBBER = mat("TT_Rubber", (0.75, 0.05, 0.05), 0.7)  # перекрашивается в игре
M_RUBBER_BACK = mat("TT_RubberBack", (0.02, 0.02, 0.02), 0.7)
M_TAPE = mat("TT_Tape", (0.02, 0.02, 0.02), 0.6)   # кайма: контрастна цвету накладки
M_BALL = mat("TT_Ball", (0.97, 0.95, 0.9), 0.3)


def box(name, size, loc, material, bevel=0.0, segments=2):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if bevel > 0:
        m = o.modifiers.new("b", "BEVEL")
        m.width = bevel
        m.segments = segments
        m.limit_method = "ANGLE"
        bpy.ops.object.modifier_apply(modifier="b")
    o.data.materials.append(material)
    return o


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    r = bpy.context.active_object
    r.name = name
    bpy.ops.object.shade_smooth()
    return r


# ---------------- стол (ITTF) ----------------
L, W, H, T = 2.74, 1.525, 0.76, 0.025
parts = []
# столешница
parts.append(box("top", (L, W, T), (0, 0, H - T / 2), M_TOP, bevel=0.004))
# боковые кромки (тёмный борт)
parts.append(box("rim", (L + 0.012, W + 0.012, 0.012), (0, 0, H - T - 0.006 + 0.0), M_EDGE, bevel=0.004))
# разметка 20 мм по периметру и центральная линия 3 мм
z = H + 0.0006
lw = 0.02
parts.append(box("l1", (L, lw, 0.0012), (0, W / 2 - lw / 2, z), M_LINE))
parts.append(box("l2", (L, lw, 0.0012), (0, -W / 2 + lw / 2, z), M_LINE))
parts.append(box("l3", (lw, W, 0.0012), (L / 2 - lw / 2, 0, z), M_LINE))
parts.append(box("l4", (lw, W, 0.0012), (-L / 2 + lw / 2, 0, z), M_LINE))
parts.append(box("lc", (L, 0.014, 0.0012), (0, 0, z), M_LINE))   # центральная линия шире ITTF (3 мм), чтобы читалась в перспективе
# каркас: два продольных швеллера и поперечины под столешницей
fz = H - T - 0.045
parts.append(box("rail1", (L - 0.5, 0.04, 0.07), (0, 0.55, fz), M_FRAME, bevel=0.004))
parts.append(box("rail2", (L - 0.5, 0.04, 0.07), (0, -0.55, fz), M_FRAME, bevel=0.004))
for sx in (-1, 1):
    parts.append(box("cross%d" % sx, (0.04, 1.15, 0.07), (sx * (L / 2 - 0.35), 0, fz), M_FRAME, bevel=0.004))
    # ножки
    for sy in (-1, 1):
        lx, ly = sx * (L / 2 - 0.35), sy * 0.55
        parts.append(box("leg", (0.055, 0.055, fz - 0.02), (lx, ly, (fz - 0.035) / 2 + 0.0), M_FRAME, bevel=0.006))
        parts.append(box("foot", (0.09, 0.09, 0.012), (lx, ly, 0.006), M_EDGE, bevel=0.004))
    # поперечная Н-связка между ногами одного торца
    parts.append(box("brace", (0.035, 1.1, 0.035), (sx * (L / 2 - 0.35), 0, 0.28), M_FRAME, bevel=0.004))
table = join(parts, "Table")

# ---------------- сетка (отдельный объект: стойки + лента + полотно) ----------------
NH = 0.1525
net_parts = []
for sy in (-1, 1):
    net_parts.append(box("post", (0.02, 0.02, NH + 0.02), (0, sy * (W / 2 + 0.07), H + (NH + 0.02) / 2 - 0.005), M_FRAME, bevel=0.003))
    net_parts.append(box("clamp", (0.05, 0.05, 0.03), (0, sy * (W / 2 + 0.025), H + 0.015), M_EDGE, bevel=0.004))
net_parts.append(box("tape", (0.012, W + 0.14, 0.014), (0, 0, H + NH - 0.007), M_NETTAPE, bevel=0.002))
# полотно: тонкая решётка из проволочек
step = 0.012
nx = int((W + 0.12) / step)
for i in range(nx + 1):
    y = -W / 2 - 0.06 + i * step
    net_parts.append(box("v", (0.0012, 0.0012, NH - 0.014), (0, y, H + (NH - 0.014) / 2), M_NETTAPE))
nz = int((NH - 0.014) / step)
for j in range(nz + 1):
    zz = H + 0.004 + j * step
    net_parts.append(box("h", (0.0012, W + 0.12, 0.0012), (0, 0, zz), M_NETTAPE))
net = join(net_parts, "Net")

# ---------------- ракетка: контур снят с фото (paddle_front.jpg) ----------------
import numpy as np
M_BLADE = mat("TT_Blade", (0.05, 0.05, 0.06), 0.5)           # дерево лопасти и ручка
M_SPONGE = mat("TT_Sponge", (0.95, 0.82, 0.55), 0.8)
M_ACCENT = mat("TT_Accent", (0.85, 0.15, 0.08), 0.5)

img = bpy.data.images.load(os.environ["NT_PADDLE_REF"])
iw, ih = img.size
pix = np.array(img.pixels[:], dtype=np.float32).reshape(ih, iw, 4)[::-1, :, :3]
nonwhite = pix.min(axis=2) < 0.88
red = (pix[:, :, 0] > 0.55) & (pix[:, :, 1] < 0.35) & (pix[:, :, 2] < 0.35)
rows = np.where(nonwhite.any(axis=1))[0]
r_top, r_bot = int(rows[0]), int(rows[-1])
SCALE = 26.0 / (r_bot - r_top)         # см на пиксель (длина ракетки ~26 см)
# накладка: строки, где красная полоса шире 250 px
red_w = np.array([ (np.where(red[y])[0][-1] - np.where(red[y])[0][0]) if red[y].any() else 0 for y in range(ih)])
rub_rows = np.where(red_w > 250)[0]
rr0, rr1 = int(np.where(red.any(axis=1))[0][0]), int(rub_rows[-1])   # накладка с самой верхней красной строки
cx = float(np.mean([np.where(nonwhite[y])[0][0] + np.where(nonwhite[y])[0][-1] for y in range(r_top + 5, r_bot - 5)]) / 2)
zc_row = (rr0 + rr1) / 2.0           # начало координат: центр накладки

def row_half(mask, y):
    xs = np.where(mask[y])[0]
    return 0.0 if len(xs) == 0 else max(cx - xs[0], xs[-1] - cx)

def outline_rows(mask, y0, y1, inset_px=0, fine=3, coarse=10, fine_span=90):
    ys = []
    y = y0
    while y <= y1:
        ys.append(y)
        near_end = (y - y0) < fine_span or (y1 - y) < fine_span
        y += fine if near_end else coarse
    if ys[-1] != y1:
        ys.append(y1)
    right = [(max(0.2, row_half(mask, y) - inset_px) * SCALE, (zc_row - y) * SCALE) for y in ys]
    left = [(-x, z) for (x, z) in reversed(right)]
    return right + left

def smooth(pts, passes, window=2):
    n = len(pts)
    for _ in range(passes):
        out = []
        for i in range(n):
            c = 2 * window + 1
            out.append((sum(pts[(i + k) % n][0] for k in range(-window, window + 1)) / c,
                        sum(pts[(i + k) % n][1] for k in range(-window, window + 1)) / c))
        pts = out
    return pts

def extrude_outline(name, pts_cm, thick_cm, y_cm, material, bevel_cm=0.0, seg=2, thick_fn=None):
    verts = [(x / 100.0, y_cm / 100.0, z / 100.0) for (x, z) in pts_cm]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [list(range(len(verts)))])
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    s = o.modifiers.new("s", "SOLIDIFY")
    s.thickness = thick_cm / 100.0
    s.offset = 0
    bpy.ops.object.modifier_apply(modifier="s")
    if thick_fn is not None:
        for v in me.vertices:
            v.co.y = y_cm / 100.0 + (v.co.y - y_cm / 100.0) * thick_fn(v.co.z * 100.0)
    if bevel_cm > 0:
        b = o.modifiers.new("b", "BEVEL")
        b.width = bevel_cm / 100.0
        b.segments = seg
        b.limit_method = "ANGLE"
        bpy.ops.object.modifier_apply(modifier="b")
    o.data.materials.append(material)
    return o

def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)

# --- дерево: текстуры волокон, слои ручки, обкладка кромки ---
def make_wood_png(fname, base, dark, freq, seed):
    n = 256
    rng = np.random.RandomState(seed)
    xs = np.linspace(0, 1, n, dtype=np.float32)[None, :]
    ys = np.linspace(0, 1, n, dtype=np.float32)[:, None]
    warp = np.zeros((n, n), dtype=np.float32)
    for k in range(1, 5):                       # низкочастотная «волна» волокон, замкнутая по краям
        warp += (rng.rand() - 0.5) * 0.006 / k * np.sin(2 * math.pi * (k * ys + rng.rand()))
    grain = 0.5 + 0.5 * np.sin(2 * math.pi * (xs * freq + warp * freq))
    fine = (rng.rand(1, n).astype(np.float32) * 0.5 + 0.5) * np.ones((n, 1), dtype=np.float32)   # тонкие продольные прожилки
    t = np.clip(grain * fine, 0, 1)
    rgb = np.array(base)[None, None, :] * (1 - t[:, :, None]) + np.array(dark)[None, None, :] * t[:, :, None]
    px = np.concatenate([rgb, np.ones((n, n, 1), dtype=np.float32)], axis=2)
    im = bpy.data.images.new(fname, n, n, alpha=False)
    im.pixels = px.ravel().tolist()
    im.filepath_raw = os.path.join(OUT, fname)
    im.file_format = "PNG"
    im.save()
    return im

def mat_tex(name, image, rough=0.55):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = image
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    m.diffuse_color = (*[sum(image.pixels[i::4]) / (len(image.pixels) / 4) for i in range(3)], 1)
    return m

img_maple = make_wood_png("wood_maple.png", (0.86, 0.68, 0.44), (0.62, 0.44, 0.24), 22, 3)
img_ash = make_wood_png("wood_ash.png", (0.47, 0.42, 0.38), (0.22, 0.19, 0.17), 14, 7)
M_MAPLE = mat_tex("TT_WoodMaple", img_maple)
M_ASH = mat_tex("TT_WoodAsh", img_ash)
M_PLY = mat("TT_Ply", (0.10, 0.07, 0.05), 0.6)

def planar_uv(o, tile_cm=6.0):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for l in f.loops:
            l[uv].uv = (l.vert.co.x * 100.0 / tile_cm, l.vert.co.z * 100.0 / tile_cm)
    bm.to_mesh(o.data)
    bm.free()

def extrude_layer(name, pts, thick, y_center, pivot, material, bevel=0.0, wedge=None):
    verts = [(x / 100.0, y_center / 100.0, z / 100.0) for (x, z) in pts]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [list(range(len(verts)))])
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me); bm.free()
    s = o.modifiers.new("s", "SOLIDIFY"); s.thickness = thick / 100.0; s.offset = 0
    bpy.ops.object.modifier_apply(modifier="s")
    if wedge is not None:
        for v in me.vertices:
            v.co.y = pivot / 100.0 + (v.co.y - pivot / 100.0) * wedge(v.co.z * 100.0)
    if bevel > 0:
        b = o.modifiers.new("b", "BEVEL"); b.width = bevel / 100.0; b.segments = 2; b.limit_method = "ANGLE"
        bpy.ops.object.modifier_apply(modifier="b")
    planar_uv(o)
    o.data.materials.append(material)
    return o

def edge_tape(name, pts, y0, y1, width, material):
    """лента по кромке: боковая стенка контура высотой 2*half_h и толщиной width (см)"""
    me = bpy.data.meshes.new(name)
    n = len(pts)
    verts = [(x / 100.0, y0 / 100.0, z / 100.0) for (x, z) in pts] + [(x / 100.0, y1 / 100.0, z / 100.0) for (x, z) in pts]
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    me.from_pydata(verts, [], faces); me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.select_all(action="DESELECT"); o.select_set(True)
    s = o.modifiers.new("s", "SOLIDIFY"); s.thickness = width / 100.0; s.offset = 1
    bpy.ops.object.modifier_apply(modifier="s")
    o.data.materials.append(material)
    return o

TW = 0.6   # центральная фанера, см
z_a = (zc_row - 835) * SCALE
z_b = (zc_row - 985) * SCALE
def wedge(z):                              # накладки ручки нарастают клином от шейки
    return 0.03 + 0.97 * smoothstep(z_a, z_b, z)

core_out = smooth(outline_rows(nonwhite, r_top, r_bot, inset_px=0), 2, 2)
core = extrude_layer("core", core_out, TW, 0, 0, M_MAPLE, bevel=0.1)
hand_out = smooth(outline_rows(nonwhite, 815, r_bot, inset_px=0), 2, 2)
PLY, OUTER = 0.05, 0.45
c0 = TW / 2
layers = []
for sgn in (1, -1):
    layers.append(extrude_layer("ply%d" % sgn, hand_out, PLY, sgn * (c0 + PLY / 2), sgn * c0, M_PLY, 0.0, wedge))
    layers.append(extrude_layer("ash%d" % sgn, hand_out, OUTER, sgn * (c0 + PLY + OUTER / 2), sgn * (c0 + PLY), M_ASH, 0.08, wedge))

rub_out = smooth(outline_rows(red, rr0, rr1, inset_px=0), 2, 2)
sponge_t, rubber_t = 0.2, 0.17
front_sponge = extrude_layer("sp_f", rub_out, sponge_t, c0 + sponge_t / 2, c0, M_SPONGE, 0.03)
front_rubber = extrude_layer("rb_f", rub_out, rubber_t, c0 + sponge_t + rubber_t / 2, c0 + sponge_t, M_RUBBER, 0.05)
back_sponge = extrude_layer("sp_b", rub_out, sponge_t, -c0 - sponge_t / 2, -c0, M_SPONGE, 0.03)
back_rubber = extrude_layer("rb_b", rub_out, rubber_t, -c0 - sponge_t - rubber_t / 2, -c0 - sponge_t, M_RUBBER, 0.05)
tape_pts = [(x * 1.004, z * 1.002) for (x, z) in rub_out]
edge_h = c0 + sponge_t + rubber_t - 0.02
# обе стороны одного цвета (материал TT_Rubber), кайма контрастная (материал TT_Tape)
tape_f = edge_tape("tape_f", tape_pts, 0.0, edge_h, 0.12, M_TAPE)
tape_b = edge_tape("tape_b", tape_pts, -edge_h, 0.0, 0.12, M_TAPE)
paddle = join([core, *layers, front_sponge, front_rubber, back_sponge, back_rubber, tape_f, tape_b], "Paddle")
bpy.ops.object.shade_smooth()
print("PADDLE size cm", [round(v * 100, 1) for v in paddle.dimensions], "tris", sum(len(p.vertices) - 2 for p in paddle.data.polygons))

# ---------------- мяч ----------------
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.02, location=(0, 0, 0))
ball = bpy.context.active_object
ball.name = "Ball"
bpy.ops.object.shade_smooth()
ball.data.materials.append(M_BALL)

# ---------------- экспорт ----------------
def export(obj, fname):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    loc = obj.location.copy()
    obj.location = (0, 0, 0)
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, fname), use_selection=True, object_types={"MESH"},
                             apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                             bake_space_transform=True, path_mode="STRIP", embed_textures=False)
    obj.location = loc

# Table и Net с общим началом координат: центр стола, пол — z=0 (одинаковые координаты у обоих)
table.location = (0, 0, 0)
net.location = (0, 0, 0)
export(table, "Table.fbx")
export(net, "Net.fbx")
export(paddle, "Paddle.fbx")
export(ball, "Ball.fbx")

# ---------------- превью-рендер ----------------
# расставляем для кадра
paddle.location = (-L / 2 - 0.12, 0.25, H + 0.12)
paddle.rotation_euler = (0, 0, 0)
paddle.name = "PaddleA"
bpy.ops.object.select_all(action="DESELECT")
paddle.select_set(True)
bpy.context.view_layer.objects.active = paddle
bpy.ops.object.duplicate()
p2 = bpy.context.active_object
p2.location = (L / 2 + 0.12, -0.2, H + 0.12)
p2.rotation_euler = (0, 0, math.pi)
ball.location = (0.3, 0.1, H + 0.05)

# пол
bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
floor = bpy.context.active_object
floor.data.materials.append(mat("Floor", (0.18, 0.2, 0.24), 0.7))

bpy.ops.object.light_add(type="AREA", location=(0, 0, 3.2))
bpy.context.active_object.data.energy = 350
bpy.context.active_object.data.size = 4
bpy.ops.object.light_add(type="SUN", location=(2, -3, 4))
bpy.context.active_object.data.energy = 1.2
bpy.context.active_object.rotation_euler = (math.radians(50), 0, math.radians(30))

scene.world = bpy.data.worlds.new("w")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.06, 0.09, 1)
scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.6

def shot(name, loc, target):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.active_object
    d = mathutils.Vector(target) - mathutils.Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 38
    scene.camera = cam
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 640
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)

shot("preview_side.png", (0.0, -3.9, 1.55), (0, 0, 0.78))
shot("preview_close.png", (-1.1, -1.6, 1.25), (0, 0, 0.8))
shot("preview_paddle.png", (-1.25, -0.55, 1.05), (-L / 2 - 0.12, 0.25, H + 0.1))
shot("preview_paddle_red.png", (-L / 2 - 0.12, 1.25, H + 0.12), (-L / 2 - 0.12, 0.25, H + 0.12))
# сохраняем исходник сцены с упакованными текстурами
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "table_tennis_scene.blend"))
print("DONE")
