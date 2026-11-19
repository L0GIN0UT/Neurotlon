# Турнирная арена для понга: пол, борта с надписями, задник, трибуны со зрителями.
# Запуск: blender -b --python build_arena.py   (переменная NT_OUT — папка для FBX и .blend)
# Шрифт — Inter (лицензия OFL), входит в поставку Blender. Системные шрифты не используются.
import bpy, bmesh, math, os, random, mathutils

OUT = os.environ["NT_OUT"]
FONT = os.environ.get("NT_FONT", "C:/Program Files/Blender Foundation/Blender 5.2/5.2/datafiles/fonts/Inter.woff2")
os.makedirs(OUT, exist_ok=True)
random.seed(11)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

MATS = {}


def mat(name, color, rough=0.5, metal=0.0, emit=None, strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit is not None:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*color, 1)
    MATS[name] = m
    return m


M_FLOOR = mat("AR_Floor", (0.03, 0.034, 0.045), 0.55)
M_MAT = mat("AR_Mat", (0.05, 0.17, 0.30), 0.4)
M_LINE = mat("AR_Line", (0.85, 0.88, 0.92), 0.4)
M_BOARD = mat("AR_Board", (0.02, 0.03, 0.07), 0.35)
M_CAP = mat("AR_BoardCap", (0.70, 0.74, 0.8), 0.3, 0.5)
M_STAND = mat("AR_Stand", (0.07, 0.08, 0.11), 0.7)
M_WALL = mat("AR_Wall", (0.025, 0.03, 0.05), 0.8)
M_PYLON = mat("AR_Pylon", (0.04, 0.045, 0.06), 0.4)
M_CYAN = mat("AR_LedCyan", (0.1, 0.7, 1.0), 0.3, 0.0, (0.1, 0.7, 1.0), 4.0)
M_LEDSIDE = mat("AR_LedSide", (0.03, 0.05, 0.09), 0.5)
M_WHITE = mat("AR_LedWhite", (0.95, 0.97, 1.0), 0.3, 0.0, (0.95, 0.97, 1.0), 3.0)
SHIRTS = [mat("AR_Shirt%d" % i, c, 0.8) for i, c in enumerate([
    (0.08, 0.08, 0.10), (0.55, 0.05, 0.06), (0.14, 0.14, 0.17), (0.80, 0.80, 0.84), (0.05, 0.10, 0.28), (0.20, 0.22, 0.26)])]
SKINS = [mat("AR_Skin%d" % i, c, 0.7) for i, c in enumerate([
    (0.80, 0.60, 0.47), (0.60, 0.42, 0.32), (0.45, 0.30, 0.22), (0.88, 0.70, 0.58)])]
M_PANTS = mat("AR_Pants", (0.05, 0.06, 0.09), 0.8)


def box(size, loc, material, bevel=0.0, rot=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if rot:
        o.rotation_euler = rot
        bpy.ops.object.transform_apply(rotation=True)
    if bevel > 0:
        m = o.modifiers.new("b", "BEVEL")
        m.width = bevel
        m.segments = 2
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
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
    except Exception:
        bpy.ops.object.shade_flat()
    return r


font = bpy.data.fonts.load(FONT)


def text(txt, max_w, max_h, loc, material, extrude=0.03):
    """светящаяся надпись, стоит вертикально и читается со стороны камеры (с -Y)"""
    cu = bpy.data.curves.new("t", "FONT")
    cu.body = txt
    cu.font = font
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.extrude = extrude
    cu.offset = 0.012          # утолщение букв
    cu.resolution_u = 10
    o = bpy.data.objects.new("t", cu)
    bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    o = bpy.context.active_object
    k = min(max_w / o.dimensions.x, max_h / o.dimensions.y)
    o.scale = (k, k, k)
    bpy.ops.object.transform_apply(scale=True)
    o.rotation_euler = (math.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(rotation=True)
    o.location = loc
    bpy.ops.object.transform_apply(location=True)
    o.data.materials.append(material)
    o.data.materials.append(M_LEDSIDE)
    for poly in o.data.polygons:
        poly.material_index = 0 if poly.normal.y < -0.5 else 1
    return o


static, led = [], []

# ---------------- пол и площадка ----------------
static.append(box((26, 26, 0.02), (0, 0, -0.01), M_FLOOR))
static.append(box((10.6, 7.0, 0.012), (0, 0, 0.006), M_MAT))
for sx in (-1, 1):
    static.append(box((0.07, 6.6, 0.0125), (sx * 5.0, 0, 0.0065), M_LINE))
for sy in (-1, 1):
    static.append(box((10.07, 0.07, 0.0125), (0, sy * 3.3, 0.0065), M_LINE))

# ---------------- рекламные борта ----------------
BH, BT = 0.78, 0.06
BY = 3.55          # дальний борт
board_texts = ["НЕЙРОТЛОН", "BCI SAMARA-2027"]
xs = [-4.0, -2.0, 0.0, 2.0, 4.0]
for i, x in enumerate(xs):
    static.append(box((1.96, BT, BH), (x, BY, BH / 2), M_BOARD, 0.01))
    static.append(box((1.96, BT + 0.03, 0.035), (x, BY, BH + 0.0175), M_CAP, 0.008))
    led.append(box((1.8, 0.012, 0.025), (x, BY - BT / 2 - 0.008, 0.07), M_CYAN))
    led.append(text(board_texts[i % 2], 1.7, 0.34, (x, BY - BT / 2 - 0.02, 0.43), M_WHITE if i % 2 else M_CYAN, 0.008))
for sx in (-1, 1):                      # боковые борта (вдоль площадки)
    for j, y in enumerate([-2.3, -0.3, 1.7]):
        static.append(box((BT, 1.96, BH), (sx * 5.3, y + 0.15, BH / 2), M_BOARD, 0.01))
        static.append(box((BT + 0.03, 1.96, 0.035), (sx * 5.3, y + 0.15, BH + 0.0175), M_CAP, 0.008))
        led.append(box((0.012, 1.8, 0.025), (sx * 5.3 - sx * (BT / 2 + 0.008), y + 0.15, 0.07), M_CYAN))

# ---------------- трибуны и зрители ----------------
import numpy as np

TIER_D, TIER_H = 0.95, 0.30
y0 = 4.4
rows = 4
PX_W, PX_H, SS = 140, 300, 3          # плитка одного зрителя, пикселей; суперсэмплинг
TEX_W = 4800                          # 36 зрителей в ряд

SKIN_TONES = [(0.82, 0.62, 0.50), (0.62, 0.44, 0.34), (0.46, 0.31, 0.23), (0.90, 0.72, 0.60), (0.72, 0.52, 0.40), (0.35, 0.24, 0.18)]
HAIR_TONES = [(0.05, 0.04, 0.04), (0.18, 0.11, 0.07), (0.42, 0.27, 0.11), (0.74, 0.62, 0.36), (0.55, 0.55, 0.58), (0.30, 0.16, 0.08)]
SHIRT_TONES = [(0.10, 0.10, 0.13), (0.62, 0.07, 0.09), (0.24, 0.26, 0.31), (0.82, 0.83, 0.87), (0.07, 0.16, 0.45),
               (0.03, 0.03, 0.04), (0.10, 0.50, 0.75), (0.90, 0.90, 0.92), (0.70, 0.12, 0.12), (0.14, 0.24, 0.20), (0.45, 0.30, 0.15)]
CAP_TONES = [(0.62, 0.07, 0.09), (0.03, 0.03, 0.04), (0.85, 0.85, 0.88), (0.07, 0.16, 0.45)]
ROW_DARK = [0.95, 0.84, 0.72, 0.60]   # дальние ряды темнее
ROW_BLUR = [0.7, 1.1, 1.6, 2.2]       # и мягче (глубина резкости)


def person_tile(rng):
    W, H = PX_W * SS, PX_H * SS
    ys, xs = np.mgrid[0:H, 0:W]
    px = (xs + 0.5) / SS
    py = (ys + 0.5) / SS
    tilt = rng.uniform(-0.07, 0.07)
    c, s = np.cos(tilt), np.sin(tilt)
    dx, dy = px - PX_W / 2 - rng.uniform(-3, 3), py - 190
    u = dx * c - dy * s                       # локальные координаты с наклоном
    v = dx * s + dy * c + 190

    skin = np.array(SKIN_TONES[rng.randint(len(SKIN_TONES))], dtype=np.float32)
    hair = np.array(HAIR_TONES[rng.randint(len(HAIR_TONES))], dtype=np.float32)
    shirt = np.array(SHIRT_TONES[rng.randint(len(SHIRT_TONES))], dtype=np.float32)
    sh = rng.uniform(0.92, 1.08)              # размер головы
    sw = rng.uniform(0.88, 1.15)              # ширина плеч
    hv = 84 + rng.uniform(-6, 6)
    ra, rb = 21 * sh, 26 * sh

    def ell(u0, v0, a, b, n=2.0):
        return (np.abs((u - u0) / a) ** n + np.abs((v - v0) / b) ** n) <= 1.0

    head = ell(0, hv, ra, rb, 2.2)
    ears = ell(-ra * 1.0, hv + 4, 4.2, 6.5) | ell(ra * 1.0, hv + 4, 4.2, 6.5)
    neck = (np.abs(u) < 10.5 * sh) & (v > hv + 18) & (v < hv + 42)
    sv = hv + 92
    torso = ell(0, sv, 54 * sw, 70, 2.6) | ((np.abs(u) < 52 * sw) & (v > sv))
    col = np.zeros((H, W, 3), dtype=np.float32)
    mask = np.zeros((H, W), dtype=bool)

    style = rng.randint(7)
    face_inner = ell(0, hv + 6, ra - 3, rb - 5, 2.2) & (v > hv - 6)
    back_hair = np.zeros_like(head)
    front_hair = np.zeros_like(head)
    cap = np.zeros_like(head)
    brim = np.zeros_like(head)
    if style == 0:        # короткая стрижка
        front_hair = ell(0, hv - 3, ra + 2, rb + 1, 2.2) & (v < hv - 8 + rng.uniform(0, 4))
    elif style == 1:      # средняя, закрывает уши
        front_hair = (ell(0, hv - 2, ra + 3, rb + 3, 2.2) & (v < hv - 7)) | (ell(0, hv + 4, ra + 3, rb + 3, 2.2) & (np.abs(u) > ra - 3) & (v < hv + 16))
    elif style == 2:      # длинные
        back_hair = ell(0, hv + 16, ra + 6, rb + 22, 2.2) & (v > hv - 10)
        front_hair = ell(0, hv - 3, ra + 3, rb + 2, 2.2) & (v < hv - 8)
    elif style == 3:      # пучок
        front_hair = ell(0, hv - 3, ra + 2, rb + 1, 2.2) & (v < hv - 8)
        front_hair |= ell(0, hv - rb - 6, 9, 9)
    elif style == 4:      # лысый или почти
        front_hair = ell(0, hv - 6, ra + 0.5, rb - 4, 2.2) & (v < hv - 14)
    elif style == 5:      # кепка
        cap = ell(0, hv - 6, ra + 3, rb + 1, 2.2) & (v < hv - 8)
        brim = ell(0, hv - 9, ra + 9, 4.0, 2.0)
    else:                 # кудрявые
        front_hair = ell(0, hv - 6, ra + 8, rb + 6, 2.0) & (v < hv - 7)
    hair_all = back_hair | front_hair
    # слои снизу вверх: волосы сзади, торс, шея, голова, волосы спереди, кепка
    def paint(m, color):
        nonlocal mask
        col[m] = color
        mask |= m
    paint(back_hair, hair * 0.8)
    g = (1.0 - np.clip((v - sv) / 160.0, 0, 1))[:, :, None]
    edge = 1.0 - 0.28 * (np.abs(u) / (55 * sw)) ** 2
    cloth = np.clip(shirt[None, None, :] * (0.66 + 0.34 * g) * edge[:, :, None], 0, 1).astype(np.float32)
    cloth = cloth * (1.0 + rng.normal(0, 0.025, size=(H, W, 1)).astype(np.float32) * 0.3)
    if rng.rand() < 0.28:     # полоса на груди (шарф, футболка болельщика)
        stripe = torso & (v > sv - 6 + rng.uniform(8, 30)) & (v < sv + 10 + rng.uniform(14, 40))
        sc = np.array(CAP_TONES[rng.randint(len(CAP_TONES))], dtype=np.float32)
        cloth = np.where(stripe[:, :, None], sc[None, None, :] * 0.9, cloth)
    arms_up = rng.rand() < 0.14
    if arms_up:
        for sgn in (-1, 1):
            ax, ay = sgn * 44 * sw, hv + 58
            bx, by = sgn * 50 * sw, hv + 4
            t = np.clip(((u - ax) * (bx - ax) + (v - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2), 0, 1)
            d = np.hypot(u - (ax + t * (bx - ax)), v - (ay + t * (by - ay)))
            arm = d < 9.0
            hand = np.hypot(u - bx, v - by) < 10.5
            paint(arm, shirt * 0.9)
            paint(hand, skin)
    paint(torso, 0)
    col[torso] = cloth[torso]
    # воротник: V-вырез или круглый
    if rng.rand() < 0.5:
        vneck = (v > hv + 30) & (v < hv + 62) & (np.abs(u) < (hv + 62 - v) * 0.48) & torso   # широко у шеи, остриё вниз
        col[vneck] = skin * 0.8
    else:
        collar = ell(0, hv + 40, 15, 9) & torso
        col[collar] = skin * 0.78
    paint(neck, skin * 0.82)
    shadow = np.clip(1.0 - (v - (hv + 16)) / 14.0, 0, 1) * neck          # тень под подбородком
    col[neck] = col[neck] * (1 - 0.35 * shadow[neck, None])
    paint(ears, skin * 0.9)
    face_shade = (0.86 + 0.14 * (1 - np.abs(u) / (ra + 1))) * (0.92 + 0.08 * (1 - np.clip((v - hv) / rb, -1, 1) ** 2))
    paint(head, 0)
    col[head] = np.clip(skin[None, :] * face_shade[head][:, None], 0, 1)
    # глаза и брови: слабый контраст, видны вблизи
    for sgn in (-1, 1):
        eye = ell(sgn * ra * 0.42, hv + 1, 3.2 * sh, 2.2 * sh)
        col[eye & head] = col[eye & head] * 0.32
        brow = ell(sgn * ra * 0.42, hv - 6, 5.5 * sh, 1.6 * sh) & head
        col[brow] = col[brow] * 0.55
    mouth = ell(0, hv + rb * 0.58, 5.5 * sh, 1.4 * sh) & head
    col[mouth] = col[mouth] * 0.62
    if front_hair.any():
        fh = front_hair & ~(face_inner & (v > hv - 4 + 0)) if style in (1, 2, 6) else front_hair
        paint(fh, hair)
        hshade = np.clip(1.0 - (u / (ra + 8) + 0.2) ** 2, 0.55, 1.0)
        col[fh] = col[fh] * hshade[fh][:, None]
    if cap.any():
        cc = np.array(CAP_TONES[rng.randint(len(CAP_TONES))], dtype=np.float32)
        paint(cap, cc)
        paint(brim, cc * 0.7)
    a = mask.astype(np.float32)

    def down(arr):
        return arr.reshape(PX_H, SS, PX_W, SS, *arr.shape[2:]).mean(axis=(1, 3))

    rgb, al = down(col * a[:, :, None]), down(a)
    top = np.clip(al - np.roll(al, 4, axis=0), 0, 1)                      # контровой свет сверху
    rgb = rgb + top[:, :, None] * np.array([0.30, 0.42, 0.62], dtype=np.float32) * 0.55
    return rgb, al


def gauss_blur(arr, sigma):
    r = int(max(1, round(sigma * 3)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    out = np.zeros_like(arr)
    for i, w in enumerate(k):
        out += w * np.roll(arr, i - r, axis=1)
    arr = out
    out = np.zeros_like(arr)
    for i, w in enumerate(k):
        out += w * np.roll(arr, i - r, axis=0)
    return out


def crowd_png(fname, seed, row):
    rng = np.random.RandomState(seed)
    rgb = np.zeros((PX_H, TEX_W, 3), dtype=np.float32)
    al = np.zeros((PX_H, TEX_W), dtype=np.float32)
    step = PX_W - 8
    n = TEX_W // step
    order = list(range(n))
    rng.shuffle(order)
    for i in order:
        if rng.rand() < 0.06:                    # свободное место
            continue
        c, a = person_tile(rng)
        x0 = int(i * step + rng.randint(-6, 7))
        dy = int(rng.randint(0, 22))
        xa, xb = max(0, x0), min(TEX_W, x0 + PX_W)
        if xb <= xa:
            continue
        c2 = c[: PX_H - dy, xa - x0: xb - x0]
        a2 = a[: PX_H - dy, xa - x0: xb - x0]
        rgb[dy:, xa:xb] = c2 + rgb[dy:, xa:xb] * (1 - a2[:, :, None])
        al[dy:, xa:xb] = a2 + al[dy:, xa:xb] * (1 - a2)
    pm = np.concatenate([rgb, al[:, :, None]], axis=2)
    pm = gauss_blur(pm, ROW_BLUR[row])
    pm[:, :, :3] *= ROW_DARK[row] * np.array([0.92, 0.97, 1.06], dtype=np.float32)
    grain = rng.normal(0, 0.012, size=pm.shape[:2]).astype(np.float32)
    pm[:, :, :3] = np.clip(pm[:, :, :3] + grain[:, :, None] * pm[:, :, 3:4], 0, 1)
    out = np.zeros_like(pm)
    nz = pm[:, :, 3] > 1e-4
    out[:, :, :3][nz] = pm[:, :, :3][nz] / pm[:, :, 3][nz][:, None]
    out[:, :, 3] = pm[:, :, 3]
    out = np.clip(out, 0, 1)[::-1]               # строки снизу вверх, как ждёт Blender
    im = bpy.data.images.new(fname, TEX_W, PX_H, alpha=True)
    im.alpha_mode = "STRAIGHT"
    im.pixels = np.ascontiguousarray(out).ravel().tolist()
    im.filepath_raw = os.path.join(OUT, fname)
    im.file_format = "PNG"
    im.save()
    return im


def crowd_mat(name, im):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = im
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
    b.inputs["Roughness"].default_value = 0.9
    try:
        m.surface_render_method = "BLENDED"
    except Exception:
        pass
    m.diffuse_color = (0.3, 0.3, 0.35, 1)
    return m


PLANE_W = 22.0
PLANE_H = PLANE_W * PX_H / TEX_W
crowd_rows = []
for r in range(rows):
    top = (r + 1) * TIER_H
    static.append(box((22, TIER_D, top), (0, y0 + r * TIER_D + TIER_D / 2, top / 2), M_STAND))
    yy = y0 + r * TIER_D + 0.45
    mrow = crowd_mat("AR_CrowdRow%d" % r, crowd_png("crowd_row%d.png" % r, 5 + r * 7, r))
    me = bpy.data.meshes.new("crowd%d" % r)
    z0 = top - 0.08
    verts = [(-PLANE_W / 2, yy, z0), (PLANE_W / 2, yy, z0), (PLANE_W / 2, yy, z0 + PLANE_H), (-PLANE_W / 2, yy, z0 + PLANE_H)]
    me.from_pydata(verts, [], [(0, 1, 2, 3)])
    me.update()
    uvl = me.uv_layers.new(name="UVMap")
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    for li in range(4):
        uvl.data[li].uv = uvs[li]
    o = bpy.data.objects.new("ArenaCrowdRow%d" % r, me)
    bpy.context.collection.objects.link(o)
    o.data.materials.append(mrow)
    crowd_rows.append(o)

# ---------------- задник ----------------
WY = y0 + rows * TIER_D + 0.3
static.append(box((26, 0.3, 7.0), (0, WY, 3.5), M_WALL))
# на стене место под табло со счётом (делается в Unity), надписи убраны
led.append(box((11.0, 0.05, 0.05), (0, WY - 0.18, 5.15), M_CYAN))
led.append(box((11.0, 0.05, 0.05), (0, WY - 0.18, 2.75), M_CYAN))

# ---------------- рамка вокруг надписи на стене ----------------
for sx in (-1, 1):
    led.append(box((0.05, 0.05, 2.45), (sx * 5.5, WY - 0.18, 3.95), M_CYAN))

arena = join(static, "ArenaStatic")
ledobj = join(led, "ArenaLed")
for o in (arena, ledobj):
    print("OBJ", o.name, "tris", sum(len(p.vertices) - 2 for p in o.data.polygons))


def export(obj, fname):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, fname), use_selection=True, object_types={"MESH"},
                             apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                             bake_space_transform=True, path_mode="STRIP", embed_textures=False)


export(arena, "ArenaStatic.fbx")
export(ledobj, "ArenaLed.fbx")
bpy.ops.object.select_all(action="DESELECT")
for o in crowd_rows:
    o.select_set(True)
bpy.context.view_layer.objects.active = crowd_rows[0]
bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, "ArenaCrowd.fbx"), use_selection=True, object_types={"MESH"},
                         apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                         bake_space_transform=True, path_mode="STRIP", embed_textures=False)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "arena_scene.blend"))
print("DONE")
