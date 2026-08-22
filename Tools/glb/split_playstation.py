"""Split the Sketchfab "Sony Playstation" scene into RetroXR's per-part GLBs.

    blender --background --python Tools/glb/split_playstation.py -- \
        --in ~/Downloads/sony_playstation.glb --out <dir>

One downloaded scene carries the console, a memory card, both pad variants, two
plug ends, eight licensed game jewel cases and two baked cords. RetroXR wants
five GLBs and none of the rest.

Three things this does that are not obvious:

  * TRADEMARK SCRUB. "SONY", "PlayStation" and the PS logo are painted into the
    decal SHEETS, mixed on the same texture as the functional legends (OPEN /
    POWER / RESET / SELECT / START / ANALOG / MEMORY CARD / the port numbers).
    They cannot be deleted as geometry, so each mark is erased by rect, measured
    by ink-clustering the sheet rather than eyeballed — on Controler_Decals the
    "PlayStation" mark starts 2 px below the "SELECT" legend. The PS logo on the
    lid IS its own object, but deleting it is only half the job: it is INLAID in
    a 0.27 mm pocket, so the pocket has to be filled back in behind it or the
    mark's outline stays scribed into the lid. See fill_logo_pocket.

  * THE ARTIST'S DISC IS OVERSIZED. It measures 163 mm against a CD's 120. The
    console footprint and the memory card agree with real hardware to ~1%, so it
    is the disc that is wrong, and it is dropped: RetroDisc builds discs from
    MediaDimensions at runtime.

  * BOTH PLUGS ARE ONE MESH. Unlike the 2600, whose joystick and paddle plugs
    genuinely differ, the two here have identical triangle counts and identical
    sorted extents — they are rotated instances. One plug GLB serves both pads.
"""
import bpy
import math
import bmesh
import mathutils
import sys
import os

# The artist authored at real-world size and scaled the whole scene up by 2.2732
# for the render — every group root carries that factor. Undoing it recovers the
# authored dimensions with ONE number, which is why it beats deriving a factor
# from a spec sheet: the console lands at 264.6 x 185.7 x 52.3 mm against a real
# SCPH-1001's ~265 x 185, and the memory card at 38.2 x 56.0 x 7.4 mm, together,
# from the same constant.
#
# The disc does NOT come right at any factor (159.5 mm here against a CD's 120) —
# the artist simply drew it oversized. It is dropped rather than reconciled.
CONSOLE_SCALE = 1.0 / 2.2732

## The lid is modelled OPEN: its root sits at -140 degrees against the shell's
## -90, so the hinge swings 50 degrees and the artist's own object origin IS the
## pivot. Poses are not authoritative (the lid ships shut), but the AXIS and the
## PIVOT are measurements, and this is where they come from.
LID_OPEN_DEG = 50.0

BG = (126, 126, 126)          # the decal sheets' flat background
WHITE = (255, 255, 255)       # what replaces the licensed character sticker

## Trademark rects to erase, per texture, as (x0, y0, x1, y1) in pixels with the
## fill colour. Bounds come from ink-clustering each sheet (Tools scratch script),
## padded only where a functional legend is not adjacent.
SCRUB = {
    # Lid_Buttons_Ports_Smooth — carries OPEN/POWER/RESET/MEMORY CARD/1/2 too.
    "Lid_Buttons_Ports_Smooth": [
        (372, 133, 510, 182, BG),      # "PlayStation"
        (355, 657, 508, 707, BG),      # "SONY"
    ],
    # Lid_Decals — nothing on it BUT the two marks, so the whole sheet goes flat.
    "Lid_Decals": [(0, 0, 1024, 1024, BG)],
    # MCard — keep "MEMORY CARD", drop the marks and the licensed sticker.
    "MCard_Decals": [
        (205, 600, 555, 836, BG),      # "PlayStation" + PS logo glyph
        (1384, 997, 1734, 1703, WHITE),  # Chun-Li sticker -> blank white label
    ],
    # Controler_Decals — ANALOG/SELECT/START end at y=617, the marks start at
    # y=619. Do not raise this rect.
    "Controler_Decals": [(1040, 618, 1220, 750, BG)],
    # Controller_Standard — SELECT/START end at y=477.
    "Controller_Standard": [(1330, 500, 1560, 685, BG)],
}

## Objects whose whole subtree is dropped: licensed cover art, the baked cords
## (VerletRope draws every cord in RetroXR), the artist's oversized discs, and
## the PS logo plate on the lid.
DROP_PREFIXES = (
    "Jewl_Case", "FFVII", "Case_Legacy_of_Kain", "Case_Bushido_Blade",
    "Case_Wild_Arms", "Case_BoFIII", "Case_Jet_Moto", "Case_Resident_Evil",
    "Case_Twisted_Metal", "Case_",
    "DS_Chord", "ControlerStan_Chord", "Rubber_Band",
    "PSX|Lid.001",            # the PS logo plate
    "PSX|Disc_Blank", "PSX|Disc_ART",
)

## Which top-level group each part is built from, and what it exports as.
PARTS = {
    "ps1_console":     "PSX",
    "ps1_memory_card": "Memory_Card",
    "ps1_dualshock":   "Controller_DuelShock",
    "ps1_controller":  "Controller_Standard.001",
    "ps1_plug":        "Controller_Plug",
}

## Sketchfab's "Group|Object|Dupli|N_Material_0" names are unusable from GDScript,
## which resolves moving parts BY NAME. Map the ones the models bind.
RENAME = {
    "PSX|Lid|Dupli|10": "Lid",
    "PSX|Buttons|Dupli|1": "Buttons",
    "PSX|Power_LED|Dupli|2": "PowerLight",
    "PSX|Front_Ports|Dupli|3": "FrontPorts",
    "PSX|Disc_Craddel|Dupli|4": "DiscCradle",
    "PSX|Laser_Bed|Dupli|5": "LaserBed",
    "PSX|Disc_BallGrip|Dupli|6": "Spindle",
    "PSX|Laser_Trolly|Dupli|7": "LaserTrolley",
    "PSX|AC_IN|Dupli|8": "JackAC",
    "PSX|Parallel_Port_Cover|Dupli|9": "ParallelPortCover",
    "PSX|PSX_Bottom|Dupli|11": "ShellBottom",
    "PSX|PSX_Top|Dupli|": "ShellTop",
}


def argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default


def scrub_textures():
    """Erase the trademark rects from the decal sheets, in place."""
    import numpy as np
    for img in bpy.data.images:
        if not img.pixels or img.size[0] == 0:
            continue
        # Blender names the packed image after the material's texture; match on
        # the material that uses it instead, since glTF image names are empty.
        rects = None
        for mat_name, r in SCRUB.items():
            mat = bpy.data.materials.get(mat_name)
            if mat is None or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image == img:
                    rects = r
                    break
            if rects:
                break
        if not rects:
            continue

        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        for (x0, y0, x1, y1, col) in rects:
            # Blender's pixel buffer is bottom-up; the rects were measured on the
            # top-down PNG, so flip the row range.
            fy0, fy1 = h - y1, h - y0
            fy0, fy1 = max(0, fy0), min(h, fy1)
            x0c, x1c = max(0, x0), min(w, x1)
            px[fy0:fy1, x0c:x1c, 0] = col[0] / 255.0
            px[fy0:fy1, x0c:x1c, 1] = col[1] / 255.0
            px[fy0:fy1, x0c:x1c, 2] = col[2] / 255.0
            px[fy0:fy1, x0c:x1c, 3] = 1.0
            print("[scrub] %-28s rect (%d,%d)-(%d,%d) <- %s"
                  % (img.name, x0, y0, x1, y1, col))
        img.pixels = px.ravel().tolist()
        img.pack()


## Flat, untextured materials to repaint, by material name.
##
## The same call the Chun-Li sticker got when it became a blank white label, but
## reached a different way: that one is painted into a SHEET, so a rect in SCRUB
## covers it, while this is a material with no texture at all and a rect has
## nothing to bite on.
##
## Material.006 is the memory card's front-lip insert -- a 22.8 x 4.5 mm panel on
## the connector end, authored a saturated blue (0.046, 0.088, 0.8). It belongs to
## the memory card alone (checked against all five parts' material lists), so
## repainting it by name here cannot reach anything else.
RECOLOUR = {
    "Material.006": WHITE,
}


def recolour_materials():
    """Repaint the flat materials in RECOLOUR. Textured ones go through SCRUB."""
    for name, col in RECOLOUR.items():
        mat = bpy.data.materials.get(name)
        if mat is None:
            print("[recolour] %s not found" % name)
            continue
        rgba = (col[0] / 255.0, col[1] / 255.0, col[2] / 255.0, 1.0)
        mat.diffuse_color = rgba
        node_tree = getattr(mat, "node_tree", None)
        if node_tree is not None:
            for node in node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    node.inputs["Base Color"].default_value = rgba
        print("[recolour] %-16s -> %s" % (name, col))


## Every other imported asset in this project ships 1024-square sheets — both
## Atari 2600 parts, the NES console and pad, the SNES Mouse, the whole bedroom.
## Match that. Downscale AFTER the scrub: the trademark rects are measured in the
## full-resolution sheet's pixels.
MAX_TEX = 1024


def downscale_textures():
    for img in bpy.data.images:
        w, h = img.size
        if w <= MAX_TEX and h <= MAX_TEX:
            continue
        if w == 0 or h == 0:
            continue
        s = float(MAX_TEX) / float(max(w, h))
        img.scale(max(1, int(w * s)), max(1, int(h * s)))
        img.pack()
        print("[tex] %s %dx%d -> %dx%d" % (img.name, w, h, img.size[0], img.size[1]))


## The lid's logo plate is INLAID, not stuck on: the artist sank a pocket into
## the lid for it, so deleting the plate on its own leaves the pocket behind and
## its rim reads as a chevron scribed into the lid. Measured on the source asset,
## the pocket floor sits 0.27 mm below the surrounding dome (z 0.01130 inside the
## footprint against 0.01157 at 9-13 mm out).
##
## Both figures are FRACTIONS OF THE PLATE'S OWN FOOTPRINT rather than lengths,
## because this runs before canonicalise() and every vertex here is still at the
## artist's 2.2732x display scale — a constant in metres would mean something
## different before and after. PAD widens the footprint to catch the pocket rim;
## RING is how far out the surface used to re-derive the missing dome is sampled.
LOGO_PAD = 0.10
LOGO_RING = 0.70
## Below this fraction of the pocket's own depth a vertex is already on the dome
## and is left exactly where it is, so a skin the artist did not sink comes
## through untouched.
LOGO_MIN_STEP = 0.05


def logo_plate_objects():
    return [ob for ob in bpy.data.objects
            if ob.type == 'MESH' and ob.name.startswith("PSX|Lid.001")]


def fill_logo_pocket(lid):
    """Re-derive the lid's surface across the logo pocket and snap it flat.

    A quadratic in the lid's two long axes, fitted to the ring of vertices just
    outside the plate's footprint, which is ample for a 14 mm pocket in a 160 mm
    dome — and it cannot tear the mesh the way deleting the faces and re-filling
    the hole can, because the tessellation is left exactly as it was and only the
    heights move.

    Everything is done in the LID's frame, not each mesh child's: the plate and
    the two lid skins are separate objects with separate transforms, and mixing
    the plate's footprint with a child's raw `co` put the fit 50 mm off the
    surface it was supposed to describe. The lid's normal axis is MEASURED as the
    one the lid is thinnest in rather than assumed to be Z, for the same reason.

    Vertices move only where they actually deviate from the fit, so the inner
    skin — which the artist did not sink — comes through with nothing moved.
    """
    import numpy as np
    plate = logo_plate_objects()
    meshes = [c for c in lid.children if c.type == 'MESH'] if lid else []
    if not plate or not meshes:
        print("[warn] no logo plate or no lid meshes; pocket left as modelled")
        return

    to_lid = lid.matrix_world.inverted()
    pf = [to_lid @ (ob.matrix_world @ v.co) for ob in plate for v in ob.data.vertices]

    # The lid's own normal is whichever axis the WHOLE lid is thinnest in.
    lidpts = [to_lid @ (ob.matrix_world @ v.co) for ob in meshes for v in ob.data.vertices]
    span = [max(p[i] for p in lidpts) - min(p[i] for p in lidpts) for i in range(3)]
    n = span.index(min(span))
    u, w = [i for i in range(3) if i != n]
    print("[logo] lid spans %.1f x %.1f x %.1f mm -> normal axis %s"
          % (span[0] * 1000, span[1] * 1000, span[2] * 1000, "XYZ"[n]))

    lo = [min(p[i] for p in pf) for i in range(3)]
    hi = [max(p[i] for p in pf) for i in range(3)]
    size = max(hi[u] - lo[u], hi[w] - lo[w])
    pad, ring = size * LOGO_PAD, size * LOGO_RING
    print("[logo] plate footprint %.1f x %.1f mm, pad %.1f mm, ring %.1f mm"
          % ((hi[u] - lo[u]) * 1000, (hi[w] - lo[w]) * 1000, pad * 1000, ring * 1000))

    for ob in meshes:
        m = to_lid @ ob.matrix_world
        back = m.inverted()
        inside, ringpts = [], []
        for v in ob.data.vertices:
            p = m @ v.co
            du = max(lo[u] - p[u], p[u] - hi[u])
            dw = max(lo[w] - p[w], p[w] - hi[w])
            d = max(du, dw)
            if d <= pad:
                inside.append((v, p))
            elif d <= pad + ring:
                ringpts.append(p)
        if not inside or len(ringpts) < 12:
            print("[logo] %-46s inside=%d ring=%d - skipped"
                  % (ob.name, len(inside), len(ringpts)))
            continue
        A = np.array([[1.0, p[u], p[w], p[u] ** 2, p[u] * p[w], p[w] ** 2]
                      for p in ringpts])
        z = np.array([p[n] for p in ringpts])
        coef, *_ = np.linalg.lstsq(A, z, rcond=None)
        rms = float(np.sqrt(((A @ coef - z) ** 2).mean()))
        fit = lambda p: float(np.array([1.0, p[u], p[w], p[u] ** 2,
                                        p[u] * p[w], p[w] ** 2]) @ coef)
        depth = max(abs(fit(p) - p[n]) for _, p in inside)
        moved, worst = 0, 0.0
        for v, p in inside:
            d = fit(p) - p[n]
            if abs(d) > depth * LOGO_MIN_STEP:
                q = p.copy()
                q[n] = p[n] + d
                v.co = back @ q
                moved += 1
                worst = max(worst, abs(d))
        ob.data.update()
        print("[logo] %-46s inside=%3d ring=%4d moved=%3d max=%.3f mm "
              "(fit rms %.3f mm)"
              % (ob.name, len(inside), len(ringpts), moved, worst * 1000,
                 rms * 1000))


def drop_unwanted():
    """Delete the licensed art, the baked cords and the logo plate."""
    doomed = []
    for ob in bpy.data.objects:
        n = ob.name
        if any(n.startswith(p) for p in DROP_PREFIXES):
            doomed.append(ob)
    for ob in doomed:
        print("[drop] %s" % ob.name)
        bpy.data.objects.remove(ob, do_unlink=True)


def top_group(ob):
    """The scene-level group an object belongs to (its topmost named ancestor)."""
    cur, last = ob, ob
    while cur.parent is not None:
        cur = cur.parent
        if cur.name not in ("Sketchfab_model", "RootNode") \
                and not cur.name.endswith(".fbx"):
            last = cur
    return last.name


def mesh_objects_of(group):
    out = []
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        if top_group(ob) == group:
            out.append(ob)
    return out


def world_bounds(objs):
    lo = mathutils.Vector((1e9, 1e9, 1e9))
    hi = mathutils.Vector((-1e9, -1e9, -1e9))
    for ob in objs:
        # Measure from VERTICES, never bound_box: these nodes carry rotations and
        # the AABB of a rotated box over-reports (see the skill's trap #1).
        for v in ob.data.vertices:
            p = ob.matrix_world @ v.co
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    return lo, hi


## Triangle budget per part. The scene arrives at 1.68 M for a Quest that is
## already CPU-bound; the Atari 2600 shell was cut to 26 k on the same reasoning.
TARGETS = {
    "ps1_console": 30000,
    "ps1_memory_card": 2500,
    "ps1_dualshock": 9000,
    "ps1_controller": 8000,
    "ps1_plug": 3500,
}
MIN_TRIS = 24          # never collapse a small part (an LED, a screw) to nothing
WELD_DIST = 1e-6       # repairing float noise, not simplifying — see decimate_glb

## Parts that must keep enough geometry to still read as themselves after a 96%
## cut. The button caps are the ones that matter: they are round, they are what
## the player looks straight at, and at the shell's global ratio the three of
## them together came out at 150 triangles.
TRI_FLOOR = {"ButtonPower": 220, "ButtonReset": 180, "ButtonOpen": 220,
             "Port1": 260, "Port2": 260, "MemCard1": 200, "MemCard2": 200,
             "DPad": 400,
             "PowerLight": 12, "Lid": 1500,
             # The two rear slots are small and flat; the global ratio would take
             # a 16 mm socket down to a couple of triangles and lose the mouth a
             # link plug has to look seated in.
             "JackSerial": 60, "JackAvMulti": 60}

## The shell models POWER, RESET and OPEN as one mesh, so a VRButton handed that
## mesh would travel all three caps at once. Separate it into loose islands and
## name them, so each cap depresses on its own.
SPLIT_BUTTONS = "Buttons"


def canonicalise(root):
    """Undo the artist's display pose and scale, keeping the Y-up conversion.

    Every group root carries (-90, 0, 0) from glTF Y-up plus whatever yaw/tilt
    posed it on the render desk. -90 alone is what the exporter converts back to
    identity, so setting exactly that lands the part axis-aligned in the GLB —
    which is what stops Godot measuring the AABB of a ROTATED box later.
    """
    root.rotation_mode = 'XYZ'
    root.rotation_euler = (math.radians(-90.0), 0.0, 0.0)
    root.scale = tuple(s * CONSOLE_SCALE for s in root.scale)
    bpy.context.view_layer.update()


def shut_the_lid():
    """Author the lid CLOSED. The artist modelled it 50 degrees open to frame the
    render; RetroXR boots every console with its lid latched shut."""
    lid = bpy.data.objects.get("PSX|Lid|Dupli|10")
    if lid is None:
        print("[warn] lid object not found")
        return
    lid.rotation_mode = 'XYZ'
    e = lid.rotation_euler
    # LOCAL rotation, not world. The lid reads -140 in world against the shell's
    # -90, but that -90 comes from its PARENT; the lid's own local X is the -50
    # of swing. Zeroing local X shuts it. Writing the world figure here instead
    # drove the lid to -180 and stood a 52 mm console 210 mm tall.
    print("[lid] local swing was %.1f deg" % math.degrees(e.x))
    lid.rotation_euler = (0.0, e.y, e.z)
    bpy.context.view_layer.update()


def separate_buttons(root):
    """Split the single Buttons mesh into ButtonPower / ButtonReset / ButtonOpen.

    Classified by centroid rather than by island order, which is arbitrary: the
    console's front is +Z and OPEN is the cap on the +X half, while POWER and
    RESET share the -X half with POWER the larger and further forward. Run AFTER
    the weld — before it, glTF's per-vertex UV splitting makes every triangle its
    own island (2017 of them here) and there is nothing to classify.
    """
    parent = bpy.data.objects.get(SPLIT_BUTTONS)
    if parent is None:
        print("[warn] no Buttons node to separate")
        return
    meshes = [c for c in parent.children if c.type == 'MESH']
    if not meshes:
        return
    ob = meshes[0]
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.mesh.separate(type='LOOSE')

    parts = [c for c in parent.children if c.type == 'MESH']
    info = []
    for p in parts:
        vs = [p.matrix_world @ v.co for v in p.data.vertices]
        if not vs:
            continue
        c = sum(vs, mathutils.Vector()) / len(vs)
        span = max(max(v.x for v in vs) - min(v.x for v in vs),
                   max(v.z for v in vs) - min(v.z for v in vs))
        info.append((p, c, span))
    if len(info) < 3:
        print("[warn] Buttons separated into %d island(s); expected 3" % len(info))
        return

    info.sort(key=lambda t: -t[2])          # biggest islands are the three caps
    caps = info[:3]
    caps.sort(key=lambda t: t[1].x)         # -X ... +X
    left_two = sorted(caps[:2], key=lambda t: -t[2])
    naming = [(left_two[0][0], "ButtonPower"), (left_two[1][0], "ButtonReset"),
              (caps[2][0], "ButtonOpen")]
    for p, name in naming:
        p.name = name
    for p, c, span in info[3:]:
        p.name = "ButtonTrim"
    for p, name in naming:
        vs = [p.matrix_world @ v.co for v in p.data.vertices]
        c = sum(vs, mathutils.Vector()) / len(vs)
        print("[button] %-12s centroid=(%7.4f %7.4f %7.4f) tris=%d"
              % (name, c.x, c.y, c.z, len(p.data.polygons)))


## The two rectangular sockets on the back panel -- SERIAL I/O and AV MULTI OUT
## -- ship inside the shell's single Silver mesh, together with the three phono
## barrels and their centre pins. Nine islands, one mesh, no names.
##
## They are told apart from the phono barrels by SHAPE rather than by size alone:
## both rectangles are 4.8 mm tall and over 15 mm wide, where a barrel is 5.7 mm
## square. Then SERIAL is the one on +X, which is the half of the panel the red
## AUDIO_R jack is on -- outboard of it, 9 mm past its edge.
def separate_rear_sockets(group):
    """Name SERIAL I/O and AV MULTI OUT so a model can measure them.

    Scoped to the group being exported, and then to the WIDEST Silver mesh in it.
    Neither narrowing is optional: a bare scan of bpy.data.objects finds the
    memory card's contacts first (every part is still in the scene at this
    point), and inside the console alone the disc spindle's ball grip is Silver
    too. The rear row spans 103 mm against the spindle's 10, so picking the
    widest is unambiguous -- and it is a measurement, not a name.
    """
    target, widest = None, 0.0
    for ob in mesh_objects_of(group):
        if not ob.data.materials:
            continue
        mat = ob.data.materials[0]
        if mat is None or not mat.name.startswith("Silver"):
            continue
        vs = [ob.matrix_world @ v.co for v in ob.data.vertices]
        if not vs:
            continue
        span = max(v.x for v in vs) - min(v.x for v in vs)
        if span > widest:
            target, widest = ob, span
    if target is None:
        print("[warn] no Silver mesh to split for the rear sockets")
        return
    # What the split PRODUCES, not every Silver mesh that happens to be around:
    # the disc spindle's ball grip is Silver too, and renaming its mesh as trim
    # is a side effect with no reason behind it.
    before = set(mesh_objects_of(group))
    bpy.ops.object.select_all(action='DESELECT')
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.mesh.separate(type='LOOSE')

    pieces = [target] + [o for o in mesh_objects_of(group) if o not in before]
    print("[rear] widest Silver mesh spans %.1f mm; split into %d island(s)"
          % (widest * 1000.0, len(pieces)))
    slots = []
    for p in pieces:
        vs = [p.matrix_world @ v.co for v in p.data.vertices]
        if not vs:
            continue
        w = max(v.x for v in vs) - min(v.x for v in vs)
        h = max(v.z for v in vs) - min(v.z for v in vs)
        c = sum(vs, mathutils.Vector()) / len(vs)
        # Blender is Z-up here: h is the socket's height on the panel.
        print("[rear]   island %.1f x %.1f mm at (%7.4f %7.4f %7.4f)"
              % (w * 1000.0, h * 1000.0, c.x, c.y, c.z))
        if w > 0.012 and h < 0.008:
            slots.append((p, c, w))
        else:
            p.name = "SilverTrim"
    if len(slots) != 2:
        print("[warn] rear sockets: found %d wide-flat island(s); expected 2"
              % len(slots))
        return
    slots.sort(key=lambda t: -t[1].x)
    for p, c, w in slots:
        p.name = "JackSerial" if c.x > 0.0 else "JackAvMulti"
        print("[rear] %-12s centroid=(%7.4f %7.4f %7.4f) width=%.1f mm"
              % (p.name, c.x, c.y, c.z, w * 1000.0))


def separate_front_ports():
    """Split FrontPorts into Port1/Port2 and MemCard1/MemCard2.

    All four sockets ship as one mesh, so nothing in the geometry names them and
    the model would have to hand-write four positions. Separated, each socket can
    be measured off the shell instead.

    Classification: the memory card slot sits ABOVE its controller port on this
    hardware, so height splits the two kinds; x sign splits port 1 (-X, the LEFT
    socket as the player faces the console's +Z front) from port 2.
    """
    parent = bpy.data.objects.get("FrontPorts")
    if parent is None:
        return
    meshes = [c for c in parent.children if c.type == 'MESH']
    if not meshes:
        return
    bpy.ops.object.select_all(action='DESELECT')
    meshes[0].select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.mesh.separate(type='LOOSE')

    info = []
    for p in [c for c in parent.children if c.type == 'MESH']:
        vs = [p.matrix_world @ v.co for v in p.data.vertices]
        if not vs:
            continue
        c = sum(vs, mathutils.Vector()) / len(vs)
        vol = ((max(v.x for v in vs) - min(v.x for v in vs))
               * (max(v.y for v in vs) - min(v.y for v in vs))
               * (max(v.z for v in vs) - min(v.z for v in vs)))
        info.append((p, c, vol))
    if len(info) < 4:
        print("[warn] FrontPorts split into %d island(s); expected >=4" % len(info))
        return
    info.sort(key=lambda t: -t[2])
    four = info[:4]
    # Blender is Z-up here: c.z is height, c.x is left/right.
    upper = sorted(four, key=lambda t: -t[1].z)[:2]
    lower = [t for t in four if t not in upper]
    for group, label in ((upper, "MemCard"), (lower, "Port")):
        for i, t in enumerate(sorted(group, key=lambda t: t[1].x), start=1):
            t[0].name = "%s%d" % (label, i)
            print("[port] %-9s centroid=(%7.4f %7.4f %7.4f)"
                  % (t[0].name, t[1].x, t[1].y, t[1].z))
    for t in info[4:]:
        t[0].name = "PortTrim"


## The three rear RCA jack inserts, identified by their flat material colour
## rather than by position: the row is NOT evenly spaced (the grey RF DC OUT sits
## between the white and yellow jacks), so reading them left-to-right off a render
## gets the assignment wrong.
JACK_BY_COLOUR = {
    (0.8, 0.8, 0.0): "JackVideo",     # yellow
    (0.8, 0.8, 0.8): "JackAudioL",    # white
    (0.8, 0.0, 0.0): "JackAudioR",    # red
}


def name_av_jacks():
    """Give the rear jack meshes names GDScript can actually resolve.

    Their Sketchfab names ("PSX|PSX_Top|Dupli|_Material.001_0") contain a DOT,
    and Godot strips dots when it sanitises node names on import — so find_child()
    with the exported name silently matches nothing. Renaming here is what makes
    the model's jack lookups work at all.
    """
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or not ob.data.materials:
            continue
        mat = ob.data.materials[0]
        if mat is None:
            continue
        c = tuple(round(v, 1) for v in mat.diffuse_color[:3])
        if c in JACK_BY_COLOUR and "Material" in ob.name:
            ob.name = JACK_BY_COLOUR[c]
            print("[jack] %-11s rgb=%s" % (ob.name, c))


## What tilts when a stick moves: the shaft and the rubber cap.
DS_STICK_PARTS = ("Joysticks|Dupli", "Joystick_Rubber_Rough")

## Meshes that hold something animated and so have to be broken up.
DS_CONTROL_MESHES = ("Grey_Dark_Buttons", "Grey_Dark_Rough", "Disc_Rubber",
                     "Joystick")

## Islands that are neither shell nor control, set aside before anything is
## classified by position. All three were mistaken for controls first time round.
## Joysticks_Hubs is the 26 x 26 x 22.7 mm dish sunk into the shell around each
## stick, and it out-measured the 22.5 mm D-pad on "biggest square thing on the
## left". Lid_Buttons_Ports_Rough is the printed L1/R1 lettering, 2-3 mm across,
## sitting slightly higher and further back than the shoulders it names, so it
## won "closest to the back edge". Controller_LED is the ANALOG lamp, 4.5 x 1.8
## mm, which passed the small-button gate beside SELECT and START.
DS_NOT_CONTROLS = ("Joysticks_Hubs", "Lid_Buttons_Ports_Rough", "Controller_LED")

## Names an animated control can have. Anything matching moves into the frame
## frame_controls builds; anything else is shell and stays where it is.
CONTROL_PREFIXES = ("DPad", "Stick", "Btn")


def _island_info(objs):
    out = []
    for p in objs:
        vs = [p.matrix_world @ v.co for v in p.data.vertices]
        if not vs:
            continue
        c = sum(vs, mathutils.Vector()) / len(vs)
        lo = mathutils.Vector((min(v.x for v in vs), min(v.y for v in vs),
                               min(v.z for v in vs)))
        hi = mathutils.Vector((max(v.x for v in vs), max(v.y for v in vs),
                               max(v.z for v in vs)))
        out.append({"ob": p, "c": c, "size": hi - lo})
    return out


def frame_controls(group, root):
    """Put every animated control in the GROUP'S frame, not the exporter's.

    ControlAnimator presses along its node's -Y and rocks about its X and Z, so
    the frame a control node sits in IS its contract. canonicalise leaves the
    group root rotated -90 about X -- its comment says the exporter converts that
    back to identity, and it does not: the exported chain reads Sketchfab_model
    -90 X, .fbx +90 X cancelling, RootNode identity, then the root -90 again, so
    everything under it lies on its back.

    Nothing had noticed because every other use of these shells reads WORLD
    transforms, which do not care. An animation is the one thing that reads a
    node's own axes: a press went backwards into the pad instead of down into the
    face, and a D-pad's roll became a yaw, which changes no heights at all.

    Parenting the controls to RootNode would fix the frame and drop them from the
    export -- mesh_objects_of groups by top_group, and top_group skips RootNode by
    name -- so they get an empty that cancels the root's rotation and stay inside
    the group.
    """
    controls = [ob for ob in mesh_objects_of(group)
                if any(ob.name.startswith(k) for k in CONTROL_PREFIXES)]
    if not controls:
        return
    frame = bpy.data.objects.new("ControlsFrame", None)
    bpy.context.scene.collection.objects.link(frame)
    frame.parent = root
    frame.rotation_mode = 'XYZ'
    frame.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    bpy.context.view_layer.update()
    for ob in controls:
        mw = ob.matrix_world.copy()
        ob.parent = frame
        ob.matrix_world = mw
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    for ob in controls:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = controls[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    print("[frame] %s: %d control(s) put in the group's frame"
          % (group, len(controls)))


def separate_dualshock_controls(group, root):
    """Break the DualShock's merged control meshes apart and name every one.

    The pad ships its four face buttons, both shoulder pairs and SELECT/START as
    ONE object, which is why it could only ever animate a D-pad. They are not one
    SURFACE though: welded, that object falls into eight loose islands, the D-pad
    into its four arms and each stick into two. The geometry was always there --
    only the separation was missing.

    Named from MEASURED position, because the export's own names say nothing (a
    face cap is "..._Grey_Dark_Buttons_0.003"). Blender is Z-up here: x is
    left/right, y is depth and z is height, the frame separate_front_ports uses.
    """
    for ob in list(mesh_objects_of(group)):
        if not any(k in ob.name for k in DS_CONTROL_MESHES):
            continue
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.mesh.separate(type='LOOSE')

    parts = _island_info(mesh_objects_of(group))
    if not parts:
        print("[warn] DualShock: nothing to classify")
        return
    xs = [i["c"].x for i in parts]
    mid_x = (min(xs) + max(xs)) * 0.5
    sticks = [i for i in parts if any(k in i["ob"].name for k in DS_STICK_PARTS)]
    rest = [i for i in parts if i not in sticks
            and not any(k in i["ob"].name for k in DS_NOT_CONTROLS)]

    # Shoulders: the four islands closest to the BACK edge -- largest y, since the
    # sticks sit at the front -- and at least 12 mm across, which is what keeps
    # their own printed lettering out.
    wide = [i for i in rest if i["size"].x > 0.012]
    back = max(i["c"].y for i in wide) if wide else 0.0
    shoulders = [i for i in wide if i["c"].y > back - 0.006]
    if len(shoulders) == 4:
        shoulders.sort(key=lambda i: -i["c"].z)
        for n, side in enumerate(sorted(shoulders[:2], key=lambda i: i["c"].x)):
            side["ob"].name = "BtnL1" if n == 0 else "BtnR1"
        for n, side in enumerate(sorted(shoulders[2:4], key=lambda i: i["c"].x)):
            side["ob"].name = "BtnL2" if n == 0 else "BtnR2"
    else:
        print("[warn] DualShock: %d shoulder islands, expected 4" % len(shoulders))

    face = [i for i in rest if i not in shoulders and i["c"].x > mid_x
            and abs(i["size"].x - i["size"].y) < 0.002
            and 0.007 < i["size"].x < 0.012]
    if len(face) == 4:
        face.sort(key=lambda i: i["c"].x)
        face[0]["ob"].name = "BtnSquare"
        face[-1]["ob"].name = "BtnCircle"
        mids = sorted(face[1:3], key=lambda i: i["c"].y)
        mids[0]["ob"].name = "BtnCross"        # nearest the player
        mids[1]["ob"].name = "BtnTriangle"     # furthest away
    else:
        print("[warn] DualShock: %d face-button islands, expected 4" % len(face))

    # The D-pad is FOUR ARMS, not a cross: welded, it separates into one island
    # per arm, 8-9 mm each, all on the plane of the face buttons. A rocker has to
    # be one mesh or it would rock a quarter of itself -- the same reason
    # prepare_ps1_pad.group_controls joins the SCPH-1080's arms back together.
    # Being at the face buttons' HEIGHT is what tells them from the 22.7 mm stick
    # dish sitting 10 mm lower.
    top_z = face[0]["c"].z if len(face) == 4 else max(i["c"].z for i in rest)
    arms = [i for i in rest if i not in shoulders and i not in face
            and i["c"].x < mid_x and abs(i["c"].z - top_z) < 0.002
            and 0.005 < i["size"].x < 0.012]
    if len(arms) == 4:
        bpy.ops.object.select_all(action='DESELECT')
        for a in arms:
            a["ob"].select_set(True)
        bpy.context.view_layer.objects.active = arms[0]["ob"]
        bpy.ops.object.join()
        bpy.context.view_layer.objects.active.name = "DPad"
    else:
        print("[warn] DualShock: %d D-pad arms, expected 4" % len(arms))

    small = [i for i in rest if i not in shoulders and i not in face
             and i not in arms
             and 0.004 < i["size"].x < 0.009 and i["size"].z < 0.004]
    small.sort(key=lambda i: i["c"].x)
    if len(small) == 3:
        small[0]["ob"].name = "BtnSelect"
        small[1]["ob"].name = "BtnAnalog"
        small[2]["ob"].name = "BtnStart"
    else:
        print("[warn] DualShock: %d small buttons, expected 3" % len(small))

    for side, keep in (("StickL", lambda x: x < mid_x),
                       ("StickR", lambda x: x >= mid_x)):
        members = [i["ob"] for i in sticks if keep(i["c"].x)]
        if not members:
            continue
        bpy.ops.object.select_all(action='DESELECT')
        for m in members:
            m.select_set(True)
        bpy.context.view_layer.objects.active = members[0]
        if len(members) > 1:
            bpy.ops.object.join()
        bpy.context.view_layer.objects.active.name = side

    named = sorted(i["ob"].name for i in _island_info(mesh_objects_of(group))
                   if any(i["ob"].name.startswith(k) for k in CONTROL_PREFIXES))
    print("[ds] named %d control(s): %s" % (len(named), ", ".join(named)))


def separate_dpad(group, root):
    """Pull the D-pad out of a controller's button mesh and name it DPad.

    Only the D-pad can be recovered this way. The four face buttons, both
    shoulders and SELECT/START are ONE connected surface in the artist's mesh
    (11 784 triangles undecimated, a single island), so no amount of loose-part
    separation will give them individual meshes — AnimatedController binds the
    rocker here and leaves _buttons empty, which it tolerates.

    The D-pad is identified as the island on the -X half that is roughly square in
    plan, which is what distinguishes it from the big shared button surface.
    """
    parent = None
    for ob in bpy.data.objects:
        if ob.type == 'EMPTY' and ob.name.startswith(group) and "Buttons" in ob.name:
            parent = ob
            break
    if parent is None:
        return
    meshes = [c for c in parent.children if c.type == 'MESH']
    if not meshes:
        return
    bpy.ops.object.select_all(action='DESELECT')
    meshes[0].select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.mesh.separate(type='LOOSE')

    best, best_tris = None, 0
    for p in [c for c in parent.children if c.type == 'MESH']:
        vs = [p.matrix_world @ v.co for v in p.data.vertices]
        if not vs:
            continue
        c = sum(vs, mathutils.Vector()) / len(vs)
        w = max(v.x for v in vs) - min(v.x for v in vs)
        d = max(v.y for v in vs) - min(v.y for v in vs)
        n = len(p.data.polygons)
        # -X half, squarish in plan, and substantial.
        if c.x < 0.0 and n > 200 and 0.6 < (w / max(d, 1e-6)) < 1.7:
            if n > best_tris:
                best, best_tris = p, n
    if best is None:
        print("[warn] %s: no D-pad island found" % group)
        return
    best.name = "DPad"
    print("[dpad] %s -> DPad tris=%d" % (group, best_tris))

    frame_controls(group, root)


## Above this face angle an edge stays a crease after the cut; below it the two
## faces shade as one surface. 30 degrees is Blender's own auto-smooth default
## and it holds the shell's mouldings while letting the lid dome read round.
SHADE_ANGLE = math.radians(30.0)


def clear_split_normals(ob):
    """Drop the custom split normals glTF imported with the mesh.

    Load-bearing, and it is the bug that shipped: these normals describe the
    surface BEFORE the cut, so carried through a 90% collapse they read as
    smears and starburst facets — the lid's dome imploded into a cone because of
    exactly this. The old code called `Mesh.free_normals_split()` inside a bare
    `except Exception: pass`; that method (and `use_auto_smooth` beside it) was
    removed in Blender 4.1, so on 4.1+ the clear silently never happened and the
    docstring described something the tool had stopped doing.

    So: no silent swallow. If the operator is missing, the run dies and says so,
    because a quiet skip here is invisible until someone renders the result.
    """
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.mesh.customdata_custom_splitnormals_clear()


def reshade(objs, angle=SHADE_ANGLE):
    """Re-derive smooth/sharp from the geometry that actually survived.

    Done in bmesh rather than through `shade_smooth_by_angle`, which on 4.1+ adds
    a "Smooth by Angle" node-group MODIFIER — and this exports with
    `export_apply=False`, so a modifier would leave the GLB shaded exactly as it
    was. Edge flags are data, and they travel.

    Runs AFTER the decimate: the angles that matter are the ones in the cut mesh,
    not the ones in the mesh that was thrown away.
    """
    for ob in objs:
        me = ob.data
        bm = bmesh.new()
        bm.from_mesh(me)
        for f in bm.faces:
            f.smooth = True
        for e in bm.edges:
            if len(e.link_faces) == 2:
                e.smooth = e.calc_face_angle(0.0) <= angle
            else:
                e.smooth = False
        bm.to_mesh(me)
        me.update()
        bm.free()


def weld(objs):
    """Weld coincident vertices and drop custom split normals.

    Load-bearing: glTF stores UVs per VERTEX, so an imported mesh is split at
    every seam and arrives as triangle soup (2017 islands for three button caps).
    Collapse cannot reduce an isolated triangle, and nothing can be separated
    into meaningful parts, until this has run.

    Note the count to watch is VERTICES, not polygons — merging coincident verts
    leaves the polygon count alone, so a polygon-based before/after reads as "the
    weld did nothing" even when it did all its work.
    """
    before = sum(len(o.data.vertices) for o in objs)
    for ob in objs:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=WELD_DIST)
        bm.to_mesh(ob.data)
        ob.data.update()
        bm.free()
        clear_split_normals(ob)

    after = sum(len(o.data.vertices) for o in objs)
    print("[weld] %d -> %d verts" % (before, after))


def decimate(objs, target):
    """Collapse to the triangle budget, one shared ratio, with per-part floors.

    A single global ratio is right for the shell but wrong for the controls: at
    the 96% cut this console needs, the three button caps came out at 150
    triangles between them and stopped reading as round. TRI_FLOOR holds the
    named parts up; the shell absorbs the difference.
    """
    total = sum(len(o.data.polygons) for o in objs)
    ratio = min(1.0, float(target) / max(1, total))
    for ob in objs:
        n = len(ob.data.polygons)
        floor = MIN_TRIS
        for key, val in TRI_FLOOR.items():
            if ob.name.startswith(key) or (ob.parent is not None
                                           and ob.parent.name.startswith(key)):
                floor = max(floor, val)
        if n <= floor:
            continue
        want = max(floor, int(n * ratio))
        if want >= n:
            continue
        m = ob.modifiers.new("dec", 'DECIMATE')
        m.decimate_type = 'COLLAPSE'
        m.ratio = float(want) / n
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.modifier_apply(modifier=m.name)
    after = sum(len(o.data.polygons) for o in objs)
    print("[dec] %d -> %d tris (target %d)" % (total, after, target))


def export_part(part, group, outdir, do_decimate):
    root = bpy.data.objects.get(group)
    objs = mesh_objects_of(group)
    if root is None or not objs:
        print("[warn] %s: nothing to export for %s" % (part, group))
        return

    canonicalise(root)
    if part == "ps1_console":
        shut_the_lid()

    # Rest the part on z = 0 and centre it on its own footprint, so the Godot
    # side gets a shell that sits on whatever it is placed on.
    lo, hi = world_bounds(objs)
    # Shift in WORLD space via matrix_world, not by writing root.location: the
    # importer puts a Sketchfab_model/RootNode/.fbx chain above every group, so a
    # local location is not world axes and subtracting a world delta from it left
    # the console 39 mm off centre.
    delta = mathutils.Vector(((lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5, lo.z))
    mw = root.matrix_world.copy()
    mw.translation = mw.translation - delta
    root.matrix_world = mw
    bpy.context.view_layer.update()

    for old, new in RENAME.items():
        ob = bpy.data.objects.get(old)
        if ob is not None:
            ob.name = new

    # Weld first, then separate: the split is only meaningful on welded geometry.
    weld(objs)
    if part == "ps1_console":
        separate_buttons(root)
        separate_front_ports()
        separate_rear_sockets(group)
        name_av_jacks()
        objs = mesh_objects_of(group)          # the split added objects
    elif part == "ps1_dualshock":
        separate_dualshock_controls(group, root)
        frame_controls(group, root)
        objs = mesh_objects_of(group)      # joins delete objects; re-query LIVE
    elif part == "ps1_controller":
        separate_dpad(group, root)
        objs = mesh_objects_of(group)
    if do_decimate:
        decimate(objs, TARGETS.get(part, 20000))
    reshade(objs)

    bpy.ops.object.select_all(action='DESELECT')
    for ob in [root] + objs:
        ob.select_set(True)
        for p in _ancestors(ob, root):
            p.select_set(True)
    bpy.context.view_layer.objects.active = root

    path = os.path.join(outdir, part + ".glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB',
                              use_selection=True, export_yup=True,
                              export_apply=False)
    lo, hi = world_bounds(objs)
    tris = sum(len(o.data.polygons) for o in objs)
    print("[export] %-16s %.4f x %.4f x %.4f m  %d tris  -> %s"
          % (part, hi.x - lo.x, hi.z - lo.z, hi.y - lo.y, tris, path))


def _ancestors(ob, stop):
    out, cur = [], ob.parent
    while cur is not None:
        out.append(cur)
        if cur == stop:
            break
        cur = cur.parent
    return out


def main():
    args = argv()
    src = os.path.expanduser(opt(args, "--in"))
    outdir = os.path.expanduser(opt(args, "--out"))
    only = opt(args, "--only")
    decimate = "--no-decimate" not in args
    os.makedirs(outdir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)

    fill_logo_pocket(bpy.data.objects.get("PSX|Lid|Dupli|10"))
    drop_unwanted()
    scrub_textures()
    recolour_materials()
    downscale_textures()

    for part, group in PARTS.items():
        if only and part != only:
            continue
        export_part(part, group, outdir, decimate)
    print("[ok] done")


main()
