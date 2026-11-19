# Мишень и дротик для дартса: Blender, экспорт FBX под Unity, текстуры и предпросмотр.
# Запуск: NT_OUT=<папка> blender -b --python build_darts.py
# Размеры по стандарту (PDC/WDF): диаметр мишени 451 мм, кольца дабл 162–170 мм, трибл 99–107 мм;
# итоговые модели увеличены в S раз для читаемости на экране. Булл (центр) крупнее стандартного:
# границы очков игры совпадают с кольцами на мишени. Цифр на мишени нет (решение владельца).
import bpy, bmesh, math, os, mathutils
import numpy as np

OUT = os.environ["NT_OUT"]
FONT = os.environ.get("NT_FONT", "C:/Program Files/Blender Foundation/Blender 5.2/5.2/datafiles/fonts/Inter.woff2")
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

S = 1.6
R_BULL_IN = 0.025 * S         # красный центр
R_BULL_OUT = 0.050 * S        # зелёное кольцо вокруг центра: граница 2 очков
R_TREBLE_IN = 0.099 * S
R_TREBLE_OUT = 0.107 * S      # граница 1 очка
R_DOUBLE_IN = 0.162 * S
R_DOUBLE_OUT = 0.170 * S
R_BOARD = 0.2255 * S
DEPTH = 0.040 * S
NUMBERS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]


# ---------------- текстура сизаля и карта нормалей ----------------
def value_noise(n, cells, rng):
    g = rng.rand(cells, cells).astype(np.float32)
    xs = np.linspace(0, cells - 1e-3, n)
    i = xs.astype(int)
    f = xs - i
    f = f * f * (3 - 2 * f)
    i1 = (i + 1) % cells
    a = g[i][:, i] * (1 - f)[None, :] + g[i][:, i1] * f[None, :]
    b = g[i1][:, i] * (1 - f)[None, :] + g[i1][:, i1] * f[None, :]
    return a * (1 - f)[:, None] + b * f[:, None]


def make_sisal(n=1024):
    rng = np.random.RandomState(4)
    h = np.zeros((n, n), dtype=np.float32)
    for cells, w in ((16, 0.20), (64, 0.30), (256, 0.30)):
        h += w * value_noise(n, cells, rng)
    for _ in range(9000):                       # волокна: короткие штрихи в случайных направлениях
        cx, cy = rng.randint(0, n), rng.randint(0, n)
        ang = rng.uniform(0, math.pi)
        ln = rng.randint(6, 22)
        sign = 1 if rng.rand() < 0.5 else -1
        for t in range(ln):
            h[int(cy + math.sin(ang) * t) % n, int(cx + math.cos(ang) * t) % n] += sign * 0.16
    h = (h - h.min()) / (h.max() - h.min())
    grey = 0.62 + 0.38 * h                      # светлая: цвет сектора задаётся оттенком материала
    gx = np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)
    gy = np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)
    nx, ny, nz = -gx * 6.0, -gy * 6.0, np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack([nx / ln * 0.5 + 0.5, ny / ln * 0.5 + 0.5, nz / ln * 0.5 + 0.5, np.ones_like(h)], axis=2)
    rgba = np.stack([grey, grey, grey, np.ones_like(h)], axis=2)
    return rgba, normal


def save_image(name, rgba, srgb=True):
    n = rgba.shape[0]
    im = bpy.data.images.new(name, n, n, alpha=False)
    im.pixels = np.ascontiguousarray(rgba[::-1]).ravel().tolist()
    im.filepath_raw = os.path.join(OUT, name)
    im.file_format = "PNG"
    im.save()
    if not srgb:
        im.colorspace_settings.name = "Non-Color"
    return im


sisal_rgba, sisal_normal = make_sisal()
IMG_SISAL = save_image("sisal.png", sisal_rgba)
IMG_SISAL_N = save_image("sisal_normal.png", sisal_normal, srgb=False)


def mat(name, color, rough=0.6, metal=0.0, textured=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if textured:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = IMG_SISAL
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        mix.inputs[7].default_value = (*color, 1)
        nt.links.new(tex.outputs["Color"], mix.inputs[6])
        nt.links.new(mix.outputs[2], b.inputs["Base Color"])
        nrm = nt.nodes.new("ShaderNodeTexImage")
        nrm.image = IMG_SISAL_N
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(nrm.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], b.inputs["Normal"])
    else:
        b.inputs["Base Color"].default_value = (*color, 1)
    m.diffuse_color = (*color, 1)
    return m


M_BLACK = mat("DB_Black", (0.025, 0.025, 0.028), 0.9, textured=True)
M_CREAM = mat("DB_Cream", (0.86, 0.78, 0.58), 0.9, textured=True)
M_RED = mat("DB_Red", (0.70, 0.04, 0.05), 0.85, textured=True)
M_GREEN = mat("DB_Green", (0.03, 0.40, 0.15), 0.85, textured=True)
M_WIRE = mat("DB_Wire", (0.72, 0.73, 0.76), 0.28, 0.95)
M_SURROUND = mat("DB_Surround", (0.02, 0.02, 0.022), 0.85, textured=True)
M_BODY = mat("DB_Body", (0.16, 0.10, 0.05), 0.8)
M_NUMBER = mat("DB_Number", (0.92, 0.92, 0.9), 0.55)
M_RING = mat("DB_CatchRing", (0.035, 0.035, 0.04), 0.7)
M_TUNGSTEN = mat("DT_Tungsten", (0.42, 0.43, 0.47), 0.22, 0.95)
M_BRASS = mat("DT_Brass", (0.80, 0.56, 0.16), 0.3, 0.95)
M_STEEL = mat("DT_Steel", (0.78, 0.79, 0.83), 0.2, 0.95)
M_SHAFT = mat("DT_Shaft", (0.05, 0.05, 0.06), 0.45)
M_FLIGHT_RED = mat("DT_FlightRed", (0.78, 0.04, 0.05), 0.55)
M_FLIGHT_WHITE = mat("DT_FlightWhite", (0.93, 0.93, 0.95), 0.55)
M_FLIGHT_DARK = mat("DT_FlightDark", (0.05, 0.05, 0.07), 0.55)

SLOTS = [M_BLACK, M_CREAM, M_RED, M_GREEN, M_WIRE, M_SURROUND, M_BODY, M_NUMBER, M_RING]
IDX = {m.name: i for i, m in enumerate(SLOTS)}


def polar(r, theta):
    return (r * math.sin(theta), 0.0, r * math.cos(theta))     # лицо мишени в плоскости XZ, верх = +Z


def add_cell(bm, r0, r1, t0, t1, slot, steps=6):
    def v(r, t):
        x, _, z = polar(r, t)
        return bm.verts.new((x, 0.0, z))
    ring0 = [v(r0, t0 + (t1 - t0) * i / steps) for i in range(steps + 1)]
    ring1 = [v(r1, t0 + (t1 - t0) * i / steps) for i in range(steps + 1)]
    for i in range(steps):
        f = bm.faces.new((ring0[i], ring0[i + 1], ring1[i + 1], ring1[i]))
        f.material_index = slot


def build_board():
    me = bpy.data.meshes.new("Board")
    bm = bmesh.new()
    seg = math.pi * 2 / 20
    for i in range(20):
        t0, t1 = (i - 0.5) * seg, (i + 0.5) * seg
        dark = i % 2 == 0
        base = IDX["DB_Black"] if dark else IDX["DB_Cream"]
        ring = IDX["DB_Red"] if dark else IDX["DB_Green"]
        add_cell(bm, R_BULL_OUT, R_TREBLE_IN, t0, t1, base)
        add_cell(bm, R_TREBLE_IN, R_TREBLE_OUT, t0, t1, ring)
        add_cell(bm, R_TREBLE_OUT, R_DOUBLE_IN, t0, t1, base)
        add_cell(bm, R_DOUBLE_IN, R_DOUBLE_OUT, t0, t1, ring)
        add_cell(bm, R_DOUBLE_OUT, R_BOARD, t0, t1, IDX["DB_Surround"], steps=4)
        add_cell(bm, R_BULL_IN, R_BULL_OUT, t0, t1, IDX["DB_Green"], steps=4)
        add_cell(bm, 0.0001, R_BULL_IN, t0, t1, IDX["DB_Red"], steps=4)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    uv = bm.loops.layers.uv.verify()            # плоская развёртка (x, z) под текстуру сизаля
    size = 2 * R_BOARD * 0.55
    for f in bm.faces:
        for l in f.loops:
            l[uv].uv = (l.vert.co.x / size + 0.5, l.vert.co.z / size + 0.5)
    bm.to_mesh(me)
    bm.free()
    for m in SLOTS:
        me.materials.append(m)
    o = bpy.data.objects.new("Board", me)
    bpy.context.collection.objects.link(o)
    for p in me.polygons:                       # нормали лицом к зрителю (-Y)
        if p.normal.y > 0:
            p.flip()
    me.update()
    return o


def box(name, size, loc, material, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True, rotation=True)
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
    return r


def wires():
    parts = []
    w = 0.0013 * S
    for i in range(20):                         # радиальные проволоки
        t = (i - 0.5) * math.pi * 2 / 20
        r0, r1 = R_BULL_OUT, R_DOUBLE_OUT
        x, _, z = polar((r0 + r1) / 2, t)
        parts.append(box("wr", (w, w * 1.8, r1 - r0), (x, -w * 0.9, z), M_WIRE, rot=(0, t, 0)))
    for r in (R_BULL_IN, R_BULL_OUT, R_TREBLE_IN, R_TREBLE_OUT, R_DOUBLE_IN, R_DOUBLE_OUT):
        n = 96
        for k in range(n):
            t = (k + 0.5) * math.pi * 2 / n
            x, _, z = polar(r, t)
            parts.append(box("wc", (w, w * 1.8, 2 * math.pi * r / n * 1.04), (x, -w * 0.9, z), M_WIRE, rot=(0, t + math.pi / 2, 0)))
    return parts


def body():
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=R_BOARD, depth=DEPTH, location=(0, DEPTH / 2 + 0.002, 0), rotation=(math.pi / 2, 0, 0))
    o = bpy.context.active_object
    o.name = "body"
    o.data.materials.append(M_BODY)
    return o


def catch_ring():
    """толстое тёмное кольцо вокруг мишени (как у настоящих)"""
    bpy.ops.mesh.primitive_torus_add(major_radius=R_BOARD + 0.004 * S, minor_radius=0.011 * S, major_segments=96, minor_segments=14,
                                     location=(0, -0.002 * S, 0), rotation=(math.pi / 2, 0, 0))
    o = bpy.context.active_object
    o.name = "ring"
    o.data.materials.append(M_RING)
    return o


font = bpy.data.fonts.load(FONT)


def numeral(n, theta):
    cu = bpy.data.curves.new("n", "FONT")
    cu.body = str(n)
    cu.font = font
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.extrude = 0.0004
    cu.offset = 0.004
    cu.resolution_u = 5
    o = bpy.data.objects.new("n", cu)
    bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    o = bpy.context.active_object
    k = (0.024 * S) / max(o.dimensions.y, 1e-6)
    o.scale = (k, k, k)
    bpy.ops.object.transform_apply(scale=True)
    o.rotation_euler = (math.pi / 2, 0, 0)               # лицом к -Y, верх цифры = +Z
    bpy.ops.object.transform_apply(rotation=True)
    o.rotation_euler = (0, theta, 0)                      # верх цифры смотрит от центра
    bpy.ops.object.transform_apply(rotation=True)
    x, _, z = polar((R_DOUBLE_OUT + R_BOARD) / 2 + 0.002 * S, theta)
    o.location = (x, -0.0015 * S, z)
    bpy.ops.object.transform_apply(location=True)
    o.data.materials.append(M_NUMBER)
    return o


board = build_board()
parts = [board, body(), catch_ring()] + wires()
# цифры вокруг мишени не рисуем: решение владельца (NUMBERS и numeral() оставлены на случай возврата)
board_obj = join(parts, "Board")
try:
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
except Exception:
    bpy.ops.object.shade_smooth()


# ---------------- дротик (острие к +Y, начало координат в острие) ----------------
def lathe(name, profile, material, segments=40):
    """тело вращения вокруг оси Y по профилю [(y, радиус), ...]"""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    verts = [bm.verts.new((r, y, 0)) for (y, r) in profile]
    for a, b in zip(verts, verts[1:]):
        bm.edges.new((a, b))
    bmesh.ops.spin(bm, geom=list(bm.verts) + list(bm.edges), axis=(0, 1, 0), cent=(0, 0, 0), angle=math.pi * 2, steps=segments)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.data.materials.append(material)
    return o


def flight_width(t):
    """полуширина лопасти (доля от максимума) по длине t: 0 у ствола … 1 сзади; заострена спереди, закруглена сзади"""
    if t < 0.62:
        return 0.16 + 0.84 * math.sin(math.pi / 2 * (t / 0.62)) ** 1.5
    u = (t - 0.62) / 0.38
    return math.sqrt(max(0.0, 1.0 - u * u)) * 0.94 + 0.06 * (1 - u)


def flight(index, y, length, mats):
    """оперение «стандарт»: плавный контур и три продольные полосы (красная, белая, красная)"""
    n = 28
    r_max = 0.0175 * S
    bands = [(0.0, 0.34, 0), (0.34, 0.62, 1), (0.62, 1.0, 0)]
    bm = bmesh.new()
    for (lo, hi, slot) in bands:
        for i in range(n):
            t0, t1 = i / n, (i + 1) / n
            w0, w1 = flight_width(t0) * r_max, flight_width(t1) * r_max
            q = [bm.verts.new((w0 * lo, y - length * t0, 0)), bm.verts.new((w1 * lo, y - length * t1, 0)),
                 bm.verts.new((w1 * hi, y - length * t1, 0)), bm.verts.new((w0 * hi, y - length * t0, 0))]
            f = bm.faces.new(q)
            f.material_index = slot
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("flight%d" % index)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mats[0])
    me.materials.append(mats[1])
    o = bpy.data.objects.new("flight%d" % index, me)
    bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    sol = o.modifiers.new("s", "SOLIDIFY")
    sol.thickness = 0.0007 * S
    bpy.ops.object.modifier_apply(modifier="s")
    o.rotation_euler = (0, index * math.pi / 2 + math.pi / 4, 0)
    bpy.ops.object.transform_apply(rotation=True)
    return o


dart_parts = []
tip_len, barrel_len, shaft_len = 0.030 * S, 0.046 * S, 0.036 * S
dart_parts.append(lathe("tip", [(-tip_len, 0.0026 * S), (-tip_len * 0.35, 0.0016 * S), (0.0, 0.00005 * S)], M_STEEL, 28))
# вольфрамовый ствол «торпеда» с накаткой: сужение спереди и сзади, мелкие канавки
y0 = -tip_len
prof = [(y0, 0.0026 * S), (y0 - 0.004 * S, 0.0036 * S), (y0 - 0.008 * S, 0.0041 * S)]
grip_start, grip_len, notches = y0 - 0.010 * S, 0.028 * S, 22
for k in range(notches):
    ya = grip_start - grip_len * k / notches
    prof += [(ya, 0.0043 * S), (ya - 0.20 * grip_len / notches, 0.0043 * S), (ya - 0.38 * grip_len / notches, 0.0038 * S),
             (ya - 0.62 * grip_len / notches, 0.0038 * S), (ya - 0.80 * grip_len / notches, 0.0043 * S)]
prof += [(y0 - barrel_len + 0.005 * S, 0.0040 * S), (y0 - barrel_len, 0.0030 * S)]
dart_parts.append(lathe("barrel", prof, M_TUNGSTEN, 36))
for ring_y in (y0 - 0.0075 * S, y0 - barrel_len + 0.004 * S):       # латунные кольца на концах ствола
    dart_parts.append(lathe("ring", [(ring_y, 0.0044 * S), (ring_y - 0.0022 * S, 0.0044 * S)], M_BRASS, 36))
ys = y0 - barrel_len                                               # хвостовик: гладкая трубка, пара тонких канавок, кольцо
r_sh = 0.0030 * S
sprof = [(ys, r_sh * 1.15), (ys - 0.0025 * S, r_sh)]
for yy in (0.008, 0.013):                                          # две тонкие канавки у ствола
    sprof += [(ys - yy * S, r_sh), (ys - (yy + 0.0007) * S, r_sh * 0.82), (ys - (yy + 0.0014) * S, r_sh)]
sprof += [(ys - shaft_len + 0.006 * S, r_sh), (ys - shaft_len + 0.0035 * S, r_sh * 1.22),
          (ys - shaft_len, r_sh * 1.22), (ys - shaft_len - 0.002 * S, r_sh)]
dart_parts.append(lathe("shaft", sprof, M_SHAFT, 32))
fy = ys - shaft_len + 0.004 * S
for k in range(4):
    dart_parts.append(flight(k, fy, 0.034 * S, (M_FLIGHT_RED, M_FLIGHT_WHITE)))
dart_obj = join(dart_parts, "Dart")
bpy.ops.object.select_all(action="DESELECT")
dart_obj.select_set(True)
bpy.context.view_layer.objects.active = dart_obj
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
try:
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
except Exception:
    bpy.ops.object.shade_smooth()


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


export(board_obj, "Dartboard.fbx")
export(dart_obj, "Dart.fbx")
print("TRIS board", sum(len(p.vertices) - 2 for p in board_obj.data.polygons), "dart", sum(len(p.vertices) - 2 for p in dart_obj.data.polygons))

# ---------------- предпросмотр ----------------
dart_obj.location = (6.0, 0.0, 0.0)
scene.world = bpy.data.worlds.new("w")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.04, 0.05, 0.08, 1)
scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.35
scene.view_settings.view_transform = "Standard"
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1280
scene.render.resolution_y = 720


def light(loc, target, energy, size=1.5):
    bpy.ops.object.light_add(type="AREA", location=loc)
    l = bpy.context.active_object
    l.data.energy = energy
    l.data.size = size
    l.rotation_euler = (mathutils.Vector(target) - mathutils.Vector(loc)).to_track_quat("-Z", "Y").to_euler()


light((0.5, -1.4, 0.9), (0, 0, 0), 55)
light((6.9, -0.7, 0.5), (6.0, -0.14, 0), 45, 1.0)


def shot(name, loc, target, lens=50):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.active_object
    cam.rotation_euler = (mathutils.Vector(target) - mathutils.Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    scene.camera = cam
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)


shot("preview_board.png", (0, -1.7, 0.0), (0, 0, 0), 60)
shot("preview_board_close.png", (0.12, -0.55, 0.05), (0.05, 0, 0.12), 60)
shot("preview_dart.png", (6.62, -0.14, 0.0), (6.0, -0.14, 0.0), 50)
shot("preview_dart_close.png", (6.28, -0.12, 0.02), (5.82, -0.12, 0.0), 80)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "darts_scene.blend"))
print("DONE")
