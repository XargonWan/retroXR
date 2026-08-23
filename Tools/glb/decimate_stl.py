"""Join and decimate STL scans via Blender's Collapse decimator.

    blender --background --python Tools/glb/decimate_stl.py -- \
        --in A.stl --in B.stl --out shell.stl --target 6000

The STL sibling of decimate_glb.py, and it exists for the same reason: a laser
scan arrives at a density meant for measuring, not for a headset. Wesk's Nunchuk
shell is 5 million triangles across its two halves.

WELD FIRST. STL has no shared vertices at all -- every triangle carries its own
three corners -- so a raw scan is pure triangle soup and Collapse cannot reduce
an isolated triangle. Without the weld the mesh floors at a few hundred thousand
faces however low it is asked to go. This is the same trap decimate_glb.py
records for Sketchfab exports, and STL hits it every single time rather than
sometimes.

Custom split normals are dropped and shading re-derived by angle, because
normals carried through a 99% cut describe a surface that is no longer there.

Keep --weld TINY, and check the VERTEX count rather than the face count. Blender's
STL importer already welds coincident corners on the way in -- the Nunchuk scan
arrives at 2 499 995 vertices for 5 000 010 faces, which is a closed manifold to
within a dozen vertices -- so there is usually nothing left to do and the default
is a formality.

Raising --weld from there is actively harmful: it merges across thin features and
leaves non-manifold geometry that Collapse will not reduce, so it shreds the mesh
instead. Measured on this shell: 0.001 mm hits an 8 000 triangle target exactly,
0.02 mm floors at 11.8 k and renders as shattered facets, 0.15 mm floors at 114 k.

Faces will not tell you any of this. Welding soup barely changes the face count --
a triangle only disappears when two of its OWN corners merge -- so a face-count
report says "welded" about a mesh Collapse cannot touch. Read the vertices.

Collapse has a floor and will sail past --target when it hits one.
"""
import sys

import bpy


def argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opts(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def opt(args, flag, default=None):
    v = opts(args, flag)
    return v[0] if v else default


def main():
    args = argv()
    srcs = opts(args, "--in")
    dst = opt(args, "--out")
    target = int(opt(args, "--target", "6000"))
    weld = float(opt(args, "--weld", "0.02"))
    if not srcs or not dst:
        raise SystemExit("need --in (one or more) and --out")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    for s in srcs:
        try:
            bpy.ops.wm.stl_import(filepath=s)
        except AttributeError:
            bpy.ops.import_mesh.stl(filepath=s)
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    print("[stl] imported %d mesh(es), %d tris"
          % (len(objs), sum(len(o.data.polygons) for o in objs)))

    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active

    try:
        ob.data.free_normals_split()
    except Exception:
        pass
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=0.7)
    except Exception:
        bpy.ops.object.shade_smooth()

    vbefore = len(ob.data.vertices)
    before = len(ob.data.polygons)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=weld)
    bpy.ops.object.mode_set(mode="OBJECT")
    welded = len(ob.data.polygons)
    # VERTICES are the number that says whether the weld took. Faces barely move
    # when soup is welded -- a triangle only disappears if two of its own corners
    # merge -- so reading faces here reports success on a mesh Collapse cannot
    # touch, and Collapse then shreds it instead of reducing it.
    print("[stl] welded at %.3f mm: %d -> %d verts, %d -> %d tris"
          % (weld, vbefore, len(ob.data.vertices), before, welded))
    if len(ob.data.vertices) > vbefore * 0.6:
        print("[stl] WARNING: weld merged almost nothing -- raise --weld")

    if welded > target:
        m = ob.modifiers.new("dec", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = target / float(welded)
        bpy.ops.object.modifier_apply(modifier=m.name)
    print("[stl] final %d tris -> %s" % (len(ob.data.polygons), dst))

    try:
        bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=False)
    except AttributeError:
        bpy.ops.export_mesh.stl(filepath=dst)


main()
