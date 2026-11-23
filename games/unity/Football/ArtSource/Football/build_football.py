# Футбольная полоса: мяч, конус, мини-ворота, мишень; экспорт FBX под Unity и предпросмотр сцены в трёх вариантах.
# Запуск:
#   NT_OUT=<папка> NT_TEX=<папка с make_textures.py> NT_PH=<папка с файлами Poly Haven> blender -b --python build_football.py
# Размеры настоящие (метры): мяч ⌀ 0,22, конус 0,30, ворота 2,4 × 1,4 × 1,0 (рама с сеткой и отдельный чехол), круглая мишень ⌀ 1,6.
# Трава — Poly Haven leafy_grass (CC0), небо и деревья — Poly Haven HDRI suburban_football_field и orlando_stadium (CC0).
# Остальное моделируется здесь; текстуры конуса, сетки и печати мишени — make_textures.py.
import bpy, bmesh, math, os, mathutils, random

OUT = os.environ["NT_OUT"]
TEX = os.environ["NT_TEX"]
PH = os.environ["NT_PH"]
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
rnd = random.Random(7)


# ---------------- материалы ----------------
def image(path, srgb=True):
    im = bpy.data.images.load(path, check_existing=True)
    im.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    return im


def pbr(name, color=(0.8, 0.8, 0.8), rough=0.5, metal=0.0, diff=None, normal=None, rough_map=None, scale=(1, 1), alpha=False,
        normal_strength=1.0, stripes=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*color, 1)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale[0], scale[1], 1)
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])

    def tex(path, srgb):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = image(path, srgb)
        nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        return n

    if diff:
        t = tex(diff, True)
        if stripes:                                                        # полосы покоса: один раз на всю плоскость
            st = nt.nodes.new("ShaderNodeTexImage")
            st.image = image(stripes, True)
            nt.links.new(coord.outputs["UV"], st.inputs["Vector"])
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs[0].default_value = 1.0
            nt.links.new(t.outputs["Color"], mix.inputs[6])
            nt.links.new(st.outputs["Color"], mix.inputs[7])
            nt.links.new(mix.outputs[2], b.inputs["Base Color"])
        else:
            nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if alpha:
            nt.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
    if rough_map:
        t = tex(rough_map, False)
        nt.links.new(t.outputs["Color"], b.inputs["Roughness"])
    if normal:
        t = tex(normal, False)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = normal_strength
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    if alpha:
        m.surface_render_method = "DITHERED"
        m.use_backface_culling = False
    return m


def make_obj(name, bm, materials):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in materials:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


def select(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o


def smooth(o, angle=40):
    select(o)
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle))
    except Exception:
        bpy.ops.object.shade_smooth()


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    r = bpy.context.active_object
    r.name = name
    return r


def box(name, size, loc, material, rot=(0, 0, 0), bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    if bevel:
        mod = o.modifiers.new("b", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        bpy.ops.object.modifier_apply(modifier="b")
    o.data.materials.append(material)
    return o


def tube(a, b, radius, material, verts=16):
    """цилиндр между двумя точками"""
    a, b = mathutils.Vector(a), mathutils.Vector(b)
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=d.length, location=(a + b) / 2)
    o = bpy.context.active_object
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = mathutils.Vector((0, 0, 1)).rotation_difference(d.normalized())
    bpy.ops.object.transform_apply(rotation=True)
    o.data.materials.append(material)
    return o


def ball_joint(p, radius, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=p)
    o = bpy.context.active_object
    o.data.materials.append(material)
    return o


# ---------------- мяч: гладкая сфера и текстура панелей (make_textures.py) ----------------
def build_ball():
    R = 0.11
    m = pbr("FB_Ball", diff=os.path.join(TEX, "ball_albedo.png"), normal=os.path.join(TEX, "ball_normal.png"), rough=0.34, normal_strength=1.0)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=R, location=(0, 0, R))
    o = bpy.context.active_object
    o.name = "Ball"
    o.data.materials.append(m)
    bpy.ops.object.shade_smooth()
    return o


# ---------------- UV вокруг оси Z ----------------
def cyl_uv(o, zmax):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    uv = (bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap"))
    for f in bm.faces:
        us = [math.atan2(l.vert.co.y, l.vert.co.x) / (2 * math.pi) + 0.5 for l in f.loops]
        if max(us) - min(us) > 0.5:
            us = [u + 1.0 if u < 0.5 else u for u in us]
        for l, u in zip(f.loops, us):
            l[uv].uv = (u, l.vert.co.z / zmax)
    bm.to_mesh(o.data)
    bm.free()


# ---------------- конус ----------------
def build_cone():
    H = 0.30
    orange = pbr("FB_Cone", diff=os.path.join(TEX, "cone_albedo.png"), normal=os.path.join(TEX, "cone_normal.png"), rough=0.42,
                 normal_strength=0.8)
    base_m = pbr("FB_ConeBase", color=(0.93, 0.21, 0.02), rough=0.5)
    bm = bmesh.new()
    prof = [(0.118, 0.024), (0.104, 0.060), (0.082, 0.112), (0.060, 0.170), (0.040, 0.230), (0.026, 0.275), (0.019, 0.297),
            (0.013, H), (0.010, H - 0.002), (0.010, H - 0.030)]                          # плавный конус с отверстием наверху
    verts = [bm.verts.new((r, 0, z)) for (r, z) in prof]
    for a, b in zip(verts, verts[1:]):
        bm.edges.new((a, b))
    bmesh.ops.spin(bm, geom=list(bm.verts) + list(bm.edges), axis=(0, 0, 1), cent=(0, 0, 0), angle=math.pi * 2, steps=64)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    body = make_obj("body", bm, [orange])
    cyl_uv(body, H)
    # настоящий конус полый: у стенки есть толщина, снизу он открыт (видно внутри, когда конус лежит)
    select(body)
    solid = body.modifiers.new("wall", "SOLIDIFY")
    solid.thickness = 0.0045
    solid.offset = -1.0                                                                    # внутрь: наружный размер не меняется
    bpy.ops.object.modifier_apply(modifier="wall")
    # основание — квадратная площадка с круглым проёмом под корпус (в проём видна трава и внутренность конуса)
    base = box("base", (0.26, 0.26, 0.024), (0, 0, 0.012), base_m, bevel=0.016)
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.109, depth=0.2, location=(0, 0, 0.012))
    hole = bpy.context.active_object
    select(base)
    cut = base.modifiers.new("hole", "BOOLEAN")
    cut.operation = "DIFFERENCE"
    cut.object = hole
    cut.solver = "EXACT"
    bpy.ops.object.modifier_apply(modifier="hole")
    bpy.data.objects.remove(hole, do_unlink=True)
    o = join([body, base], "Cone")
    smooth(o, 35)
    return o


# ---------------- сетка по четырём углам ----------------
def net_panel(name, c00, c10, c11, c01, nx, ny, sag, net_m, cell=0.32):
    """сетка по четырём углам с провисанием (sag вдоль нормали); UV в метрах (ячейка плитки cell, по умолчанию 0,32 м)"""
    c00, c10, c11, c01 = (mathutils.Vector(c) for c in (c00, c10, c11, c01))
    bm = bmesh.new()
    uvl = (bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap"))
    w = (c10 - c00).length
    h = (c01 - c00).length
    nrm = (c10 - c00).cross(c01 - c00).normalized()
    grid = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            u, v = i / nx, j / ny
            p = c00.lerp(c10, u).lerp(c01.lerp(c11, u), v)
            p += nrm * sag * math.sin(math.pi * u) * math.sin(math.pi * v) * (1.0 + 0.15 * math.sin(7 * u + 3 * v))
            row.append(bm.verts.new(p))
        grid.append(row)
    for j in range(ny):
        for i in range(nx):
            quad = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            f = bm.faces.new([grid[b][a] for (a, b) in quad])
            for l, (a, b) in zip(f.loops, quad):
                l[uvl].uv = (a / nx * w / cell, b / ny * h / cell)
    return make_obj(name, bm, [net_m])


# ---------------- ворота 2,4 × 1,4 м с сеткой и чехлом ----------------
# Чехол (goal_tarp.png) закрывает проём; в нём четыре отверстия — цели передач (положения те же, что в FootballTuning).
def build_goal():
    W, H, DB, DT = 2.4, 1.4, 1.0, 0.55                                              # ширина, высота, глубина внизу и вверху
    r = 0.038
    tube_m = pbr("FB_GoalTube", color=(0.93, 0.93, 0.94), rough=0.38, metal=0.15)
    rubber = pbr("FB_Rubber", color=(0.03, 0.03, 0.03), rough=0.8)
    parts = []
    hw = W / 2
    pts = {
        "fl": (-hw, 0, 0), "fr": (hw, 0, 0), "tl": (-hw, 0, H), "tr": (hw, 0, H),                       # передняя рама
        "bl": (-hw, DB, r), "br": (hw, DB, r), "ul": (-hw, DT, H), "ur": (hw, DT, H),                    # задняя нижняя и верхняя
    }
    lines = [("fl", "tl"), ("fr", "tr"), ("tl", "tr"), ("fl", "bl"), ("fr", "br"), ("bl", "br"), ("tl", "ul"), ("tr", "ur"),
             ("ul", "ur"), ("bl", "ul"), ("br", "ur")]
    for a_, b_ in lines:
        parts.append(tube(pts[a_], pts[b_], r, tube_m))
    for p_ in pts.values():
        parts.append(ball_joint(p_, r * 1.15, tube_m))
    for x in (-hw, hw):                                                             # опорные «башмаки» на полу
        parts.append(box("shoe", (0.09, 0.13, 0.014), (x, 0.0, 0.007), rubber, bevel=0.004))
    frame = join(parts, "GoalFrame")
    net_m = pbr("FB_Net", color=(0.92, 0.92, 0.93), rough=0.7, diff=os.path.join(TEX, "net.png"), alpha=True)
    nets = []

    nets.append(net_panel("net_top", pts["tl"], pts["tr"], pts["ur"], pts["ul"], 44, 12, 0.03, net_m))
    nets.append(net_panel("net_back", pts["ul"], pts["ur"], pts["br"], pts["bl"], 44, 24, -0.05, net_m))
    nets.append(net_panel("net_left", pts["fl"], pts["bl"], pts["ul"], pts["tl"], 18, 24, 0.04, net_m))
    nets.append(net_panel("net_right", pts["fr"], pts["br"], pts["ur"], pts["tr"], 18, 24, -0.04, net_m))
    # чехол — отдельная подробная сетка (48 × 28), чтобы игра могла прогибать её при ударе мяча; лежит чуть впереди рамы, лицом к игроку (−Y)
    tarp_m = pbr("FB_GoalTarp", diff=os.path.join(TEX, "goal_tarp.png"), rough=0.7, alpha=True)
    bm = bmesh.new()
    uvl = (bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap"))
    tw, th = W - 0.05, H - 0.05
    gx, gz = 48, 28
    grid = [[bm.verts.new((-tw / 2 + tw * i / gx, -0.014, H / 2 - th / 2 + th * j / gz)) for i in range(gx + 1)] for j in range(gz + 1)]
    for j in range(gz):
        for i in range(gx):
            quad = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            f = bm.faces.new([grid[b_][a_] for (a_, b_) in quad])
            for l, (a_, b_) in zip(f.loops, quad):
                l[uvl].uv = (a_ / gx, b_ / gz)
    tarp_o = make_obj("tarp", bm, [tarp_m])
    o = frame                                                                              # рама отдельно: сетка прогибается в игре, рама нет
    o.name = "Goal"
    smooth(o, 50)
    net_o = join(nets, "GoalNet")
    smooth(net_o, 50)
    return o, tarp_o, net_o


# ---------------- ловящая сетка за зоной остановки: низкий оранжевый барьер 4,2 × 1,4 м на двух мачтах ----------------
# Не похожа на ворота (нет рамы и перекладины): две невысокие мачты с оттяжками и сетка с грузом по нижнему краю, как ограждающий барьер.
# Нижний край сетки свободный (в игре не пристёгнут), поэтому мяч у земли заметно прогибает полотно.
def build_stop_net():
    W, H = 4.2, 1.4
    hw = W / 2
    pole_m = pbr("FB_StopPole", color=(0.10, 0.11, 0.12), rough=0.5, metal=0.7)
    rubber = bpy.data.materials.get("FB_Rubber") or pbr("FB_Rubber", color=(0.03, 0.03, 0.03), rough=0.8)
    net_m = pbr("FB_StopNet", color=(0.95, 0.50, 0.08), rough=0.8, diff=os.path.join(TEX, "stop_net.png"), alpha=True)    # сигнальный оранжевый
    parts = []
    for x in (-hw, hw):
        parts.append(tube((x, 0, 0), (x, 0, H + 0.12), 0.035, pole_m))                     # мачта
        parts.append(ball_joint((x, 0, H + 0.12), 0.05, pole_m))
        parts.append(tube((x, 0, H), (x * 1.12, 1.3, 0.02), 0.01, pole_m))                 # оттяжка к земле назад и наружу
        parts.append(box("anchor", (0.16, 0.16, 0.04), (x * 1.12, 1.3, 0.02), rubber, bevel=0.01))
        parts.append(box("foot", (0.3, 0.3, 0.03), (x, 0.0, 0.015), rubber, bevel=0.01))
    parts.append(tube((-hw, 0, H), (hw, 0, H), 0.012, pole_m))                             # верхний тросик
    frame = join(parts, "StopNetFrame")
    # полотно провисает назад (−sag: в сторону +Y, от игрока); плитка 0,15 м с канатом (stop_net.png), у земли
    cloth = net_panel("cloth", (-hw, 0, 0.03), (hw, 0, 0.03), (hw, 0, H), (-hw, 0, H), 70, 24, -0.12, net_m, cell=0.15)
    o = join([frame, cloth], "StopNet")
    smooth(o, 50)
    return o


# ---------------- круглая мишень ⌀ 1,6 м на стойках ----------------
def build_target():
    D = 1.6
    zc = 1.25
    metal = pbr("FB_TargetMetal", color=(0.16, 0.17, 0.19), rough=0.5, metal=0.7)
    board_m = pbr("FB_TargetBoard", color=(0.08, 0.08, 0.09), rough=0.8)
    face_m = pbr("FB_TargetFace", diff=os.path.join(TEX, "target_rings.png"), rough=0.5, alpha=True)
    rubber = pbr("FB_Rubber2", color=(0.03, 0.03, 0.03), rough=0.8)
    parts = []
    bpy.ops.mesh.primitive_cylinder_add(vertices=72, radius=D / 2 + 0.02, depth=0.04, location=(0, 0.02, zc), rotation=(math.pi / 2, 0, 0))
    back = bpy.context.active_object
    bpy.ops.object.transform_apply(rotation=True)
    back.data.materials.append(board_m)
    parts.append(back)
    bm = bmesh.new()
    uvl = (bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap"))
    vs = [bm.verts.new((x, -0.0015, zc + z)) for (x, z) in ((-D / 2, -D / 2), (D / 2, -D / 2), (D / 2, D / 2), (-D / 2, D / 2))]
    f = bm.faces.new(vs)
    for l, uv in zip(f.loops, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        l[uvl].uv = uv
    face = make_obj("face", bm, [face_m])
    for fc in face.data.polygons:
        if fc.normal.y > 0:                                                              # лицом к игроку (−Y)
            fc.flip()
    parts.append(face)
    top, bot = zc + D / 2, zc - D / 2
    for x in (-D * 0.30, D * 0.30):                                                      # опоры
        parts.append(tube((x, 0.07, 0.03), (x, 0.07, top - 0.15), 0.028, metal))
        parts.append(tube((x, 0.07, 0.03), (x, 0.60, 0.03), 0.024, metal))
        parts.append(tube((x, 0.07, 0.03), (x, -0.42, 0.03), 0.024, metal))
        parts.append(box("pad", (0.10, 0.10, 0.014), (x, 0.60, 0.007), rubber, bevel=0.004))
        parts.append(box("pad", (0.10, 0.10, 0.014), (x, -0.42, 0.007), rubber, bevel=0.004))
    parts.append(tube((-D * 0.30, 0.07, bot + 0.2), (D * 0.30, 0.07, bot + 0.2), 0.02, metal))
    o = join(parts, "Target")
    smooth(o, 35)
    return o


# ---------------- экспорт ----------------
def export(obj, fname):
    select(obj)
    loc = obj.location.copy()
    obj.location = (0, 0, 0 if fname != "FootBall.fbx" else obj.location.z)
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, fname), use_selection=True, object_types={"MESH"},
                             apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                             bake_space_transform=True, path_mode="STRIP", embed_textures=False)
    obj.location = loc


ball = build_ball()
cone = build_cone()
goal, goal_tarp, goal_net = build_goal()
stop_net = build_stop_net()
target = build_target()
print("TRIS", {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in (ball, cone, goal, goal_tarp, goal_net, stop_net, target)})
export(ball, "FootBall.fbx")
export(cone, "TrainingCone.fbx")
export(goal, "MiniGoal.fbx")
export(goal_tarp, "GoalTarp.fbx")
export(goal_net, "GoalNet.fbx")
export(stop_net, "StopNet.fbx")
export(target, "TargetPanel.fbx")


# ---------------- предпросмотр: футбольное поле ----------------
# Поле 48 × 30 м. Станции расставлены по полю: змейка из конусов перед мячом, мини-ворота справа, зона остановки слева,
# мишень в дальнем конце. Камера стоит сзади мяча. Небо, деревья и свет — HDRI Poly Haven (CC0).
FIELD_W, FIELD_H = 48.0, 30.0
BALL_START = (0.0, -10.0)
CONES = [(-1.3, -6.6), (1.3, -4.4), (-1.3, -2.2), (1.3, 0.0), (-1.3, 2.2)]
GOAL_POS, GOAL_ROT = (9.5, 2.0), -90.0                 # справа, проём смотрит в центр поля
ZONE_POS, ZONE_SIZE = (-8.0, 4.5), 2.6                 # зона остановки слева
TARGET_POS = (0.0, 12.5)                               # мишень в дальнем конце

scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1600
scene.render.resolution_y = 900
scene.view_settings.view_transform = "AgX" if "AgX" in [v.identifier for v in scene.view_settings.bl_rna.properties["view_transform"].enum_items] else "Standard"
scene.eevee.taa_render_samples = 64

to_remove = []


def plane(name, size_x, size_y, loc, rot, material):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size_x, size_y, 1)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(material)
    return o


def hdri_world(path, rotation_deg, strength):
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value = (0, 0, math.radians(rotation_deg))
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(path, check_existing=True)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    scene.world = w


def line(name, x0, y0, x1, y1, width, material):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    length = math.hypot(x1 - x0, y1 - y0)
    ang = math.atan2(y1 - y0, x1 - x0)
    return plane(name, length, width, (cx, cy, 0.004), (0, 0, ang), material)


def ring_line(name, cx, cy, r, width, material, steps=72):
    out = []
    for i in range(steps):
        a0, a1 = 2 * math.pi * i / steps, 2 * math.pi * (i + 1) / steps
        out.append(line(name, cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1), width, material))
    return out


def corner_flag(x, y):
    pole = pbr("FlagPole", color=(0.95, 0.95, 0.95), rough=0.4)
    parts = [tube((x, y, 0), (x, y, 1.55), 0.018, pole)]
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, 1.55)), bm.verts.new((x, y, 1.18)), bm.verts.new((x + (0.34 if x < 0 else -0.34), y, 1.365))]
    bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    fl = make_obj("flag", bm, [pbr("FlagCloth", color=(1.0, 0.78, 0.05), rough=0.8)])
    fl.data.materials[0].use_backface_culling = False
    parts.append(fl)
    return parts


def ad_boards():
    objs = []
    blue = pbr("BoardBlue", color=(0.05, 0.20, 0.58), rough=0.55)
    white = pbr("BoardWhite", color=(0.92, 0.92, 0.94), rough=0.55)
    post = pbr("BoardPost", color=(0.12, 0.13, 0.15), rough=0.6, metal=0.5)
    y = FIELD_H / 2 + 1.2
    xs = [-22 + 3.2 * i for i in range(int(44 / 3.2) + 1)]
    for i, x in enumerate(xs):
        m = blue if i % 2 == 0 else white
        objs.append(box("board", (3.0, 0.08, 0.9), (x, y, 0.55), m, bevel=0.01))
        objs.append(box("post", (0.08, 0.08, 1.0), (x - 1.6, y + 0.06, 0.5), post))
    cu = bpy.data.fonts.load(os.environ.get("NT_FONT", "C:/Program Files/Blender Foundation/Blender 5.2/5.2/datafiles/fonts/Inter.woff2"))
    for i, x in enumerate(xs):
        if i % 2 != 0:
            continue
        cv = bpy.data.curves.new("t", "FONT")
        cv.body = "НЕЙРОТЛОН"
        cv.font = cu
        cv.align_x = "CENTER"
        cv.align_y = "CENTER"
        cv.size = 0.34
        cv.extrude = 0.004
        to = bpy.data.objects.new("t", cv)
        bpy.context.collection.objects.link(to)
        to.rotation_euler = (math.pi / 2, 0, 0)
        to.location = (x, y - 0.045, 0.55)
        to.data.materials.append(pbr("BoardText", color=(0.95, 0.95, 0.97), rough=0.5))
        objs.append(to)
    for sx in (-24.0, 24.0):                                          # боковые борта
        for j in range(8):
            yy = -13.5 + 3.4 * j
            objs.append(box("sb", (0.08, 3.2, 0.9), (sx, yy, 0.55), blue if j % 2 == 0 else white, bevel=0.01))
    return objs


def build_field():
    objs = []
    grass_m = pbr("Pitch", diff=os.path.join(TEX, "grass_albedo.png"), normal=os.path.join(TEX, "grass_normal.png"),
                  rough=0.85, scale=(FIELD_W / 1.4, FIELD_H / 1.4), normal_strength=1.0,
                  stripes=os.path.join(TEX, "stripes.png"))
    objs.append(plane("pitch", FIELD_W + 14, FIELD_H + 12, (0, 0, 0), (0, 0, 0), grass_m))
    white = pbr("Line", color=(0.93, 0.93, 0.92), rough=0.9)
    hw, hh = FIELD_W / 2 - 1.5, FIELD_H / 2 - 1.5
    for (x0, y0, x1, y1) in ((-hw, -hh, hw, -hh), (hw, -hh, hw, hh), (hw, hh, -hw, hh), (-hw, hh, -hw, -hh)):
        objs.append(line("ln", x0, y0, x1, y1, 0.14, white))
    yellow = pbr("LineY", color=(1.0, 0.78, 0.08), rough=0.9)
    zx, zy = ZONE_POS
    z = ZONE_SIZE / 2
    for (x0, y0, x1, y1) in ((zx - z, zy - z, zx + z, zy - z), (zx + z, zy - z, zx + z, zy + z), (zx + z, zy + z, zx - z, zy + z), (zx - z, zy + z, zx - z, zy - z)):
        objs.append(line("zone", x0, y0, x1, y1, 0.14, yellow))
    objs += ring_line("zonec", zx, zy, 0.35, 0.1, yellow, 24)
    mark = pbr("Mark", color=(0.93, 0.93, 0.92), rough=0.9)                       # метка старта мяча
    bx, by = BALL_START
    objs.append(line("st1", bx - 0.3, by - 0.3, bx + 0.3, by + 0.3, 0.07, mark))
    objs.append(line("st2", bx - 0.3, by + 0.3, bx + 0.3, by - 0.3, 0.07, mark))
    for (x, y) in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        objs += corner_flag(x, y)
    objs += ad_boards()
    return objs


def layout():
    ball.location = (BALL_START[0], BALL_START[1], 0.11)
    cone.location = (CONES[0][0], CONES[0][1], 0)
    for (x, y) in CONES[1:]:
        c = cone.copy()
        bpy.context.collection.objects.link(c)
        c.location = (x, y, 0)
    goal.location = (GOAL_POS[0], GOAL_POS[1], 0)
    goal.rotation_euler = (0, 0, math.radians(GOAL_ROT))
    goal_tarp.location = goal.location
    goal_tarp.rotation_euler = goal.rotation_euler
    target.location = (TARGET_POS[0], TARGET_POS[1], 0)


def add_sun(strength, loc, target_pt):
    bpy.ops.object.light_add(type="SUN", location=loc)
    l = bpy.context.active_object
    l.data.energy = strength
    l.data.angle = math.radians(1.2)
    l.data.color = (1.0, 0.95, 0.86)
    l.rotation_euler = (mathutils.Vector(target_pt) - mathutils.Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return l


def render(name, cam_loc, look, lens, ortho=None):
    bpy.ops.object.camera_add(location=cam_loc)
    cam = bpy.context.active_object
    cam.rotation_euler = (mathutils.Vector(look) - mathutils.Vector(cam_loc)).to_track_quat("-Z", "Y").to_euler()
    if ortho:
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = ortho
    else:
        cam.data.lens = lens
    scene.camera = cam
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)


layout()
field_objs = build_field()
HDRI = {"park": os.path.join(PH, "suburban_football_field_2k.hdr"), "stadium": os.path.join(PH, "orlando_stadium_2k.hdr")}
for tag, rot, strength in (("park", 200, 1.0), ("stadium", 120, 1.0)):
    hdri_world(HDRI[tag], rot, strength)
    render("field_%s.png" % tag, (0.0, -14.2, 1.6), (0.0, 2.0, 0.45), 30)
    if tag == "park":
        render("field_%s_goal.png" % tag, (3.5, -3.0, 1.2), (GOAL_POS[0], GOAL_POS[1], 0.6), 32)
        render("field_%s_ball.png" % tag, (0.5, -11.1, 0.42), (0.0, -9.0, 0.12), 45)

# план поля сверху с подписями станций
labels = []
for text, (x, y) in (("1  ЗМЕЙКА", (-4.2, -2.2)), ("2  ВОРОТА", (GOAL_POS[0], GOAL_POS[1] - 3.2)), ("3  ЗОНА ОСТАНОВКИ", (ZONE_POS[0], ZONE_POS[1] - 3.0)),
                     ("4  МИШЕНЬ", (TARGET_POS[0], TARGET_POS[1] - 3.2)), ("СТАРТ", (BALL_START[0], BALL_START[1] - 1.6))):
    cv = bpy.data.curves.new("lab", "FONT")
    cv.body = text
    cv.font = bpy.data.fonts.load(os.environ.get("NT_FONT", "C:/Program Files/Blender Foundation/Blender 5.2/5.2/datafiles/fonts/Inter.woff2"))
    cv.align_x = "CENTER"
    cv.size = 1.1
    cv.extrude = 0.02
    lo = bpy.data.objects.new("lab", cv)
    bpy.context.collection.objects.link(lo)
    lo.location = (x, y, 0.2)
    lo.data.materials.append(pbr("Lab", color=(1, 1, 1), rough=0.5))
    labels.append(lo)
hdri_world(HDRI["park"], 200, 1.0)
render("field_plan.png", (0, 0, 60), (0, 0, 0), 0, ortho=46)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "football_scene.blend"))
print("DONE")
