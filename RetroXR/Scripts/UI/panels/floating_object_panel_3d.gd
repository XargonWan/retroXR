## FloatingObjectPanel3D — a 2D options panel that hangs in the air above the
## thing it belongs to and turns to face the player.
##
## Ten panels had grown their own copy of the same twelve lines: top_level on,
## hidden until asked for, and a _process that parks the panel over its object
## and aims it at the camera. Nine were identical in _ready and hide_panel, six
## in _process too.
##
## Two hooks rather than one shared member, so no panel has to rename anything:
## _target_node() hands back whatever that panel already calls its subject
## (_dvd, _vcr, _card...), and _float_height() how far above it to sit. A panel
## whose placement is not "straight up from the origin" — the television, which
## measures the set's own top, the poster, which steps off the surface it is
## stuck to, and the core panel, which clears the tower — overrides _anchor()
## instead and ignores both.
##
## The double flip in _process is not redundant: look_at points the node's -Z at
## the target, and a Viewport2Din3D's face is +Z, so without the half turn every
## panel would present its back to the player.
class_name FloatingObjectPanel3D
extends Node3D

## Default distance above the subject's origin. Overridden per panel, because it
## depends on how tall the thing underneath is.
const DEFAULT_FLOAT_HEIGHT := 0.3

## The head this panel turns towards. Handed in by show_for; a panel with no
## camera still parks correctly and simply does not rotate.
var _camera: Node3D = null

## Set once the panel's 2D UI has been found and its signals wired. The lookup
## has to be deferred — the SubViewport's child does not exist on the frame the
## panel is added — so this guards against wiring the same signals twice.
var _ui_connected := false


func _ready() -> void:
	# top_level: the panel is positioned in world space every frame, so it must
	# not inherit the transform of whatever it happens to be parented under.
	top_level = true
	visible = false


func _process(_delta: float) -> void:
	if not visible:
		return
	var target := _target_node()
	if target != null and is_instance_valid(target):
		global_position = _anchor()
	if _camera != null and is_instance_valid(_camera):
		look_at(_camera.global_position, Vector3.UP)
		rotate_object_local(Vector3.UP, PI)


func hide_panel() -> void:
	visible = false


# ── Hooks ─────────────────────────────────────────────────────────────────────

## The object this panel belongs to, or null when it is not showing for anything.
func _target_node() -> Node3D:
	return null


## How far above the subject's origin to sit.
func _float_height() -> float:
	return DEFAULT_FLOAT_HEIGHT


## Where the panel should be this frame. Override for a subject whose top is not
## a fixed distance from its origin.
func _anchor() -> Vector3:
	var target := _target_node()
	if target == null or not is_instance_valid(target):
		return global_position
	return target.global_position + Vector3(0, _float_height(), 0)
