## Wii motion self-tests — what a remote and its Nunchuk report, headless.
##
##     "$godot" --headless --path RetroXR res://Tests/motion_tests.tscn
##     "$godot" --headless --path RetroXR res://Tests/motion_tests.tscn -- --only=accel
##
## Exits 0 when everything passes, 1 otherwise, so it can gate a commit.
##
## What is here is what can be decided without a core: the change of basis from
## a tracked pose into the axes an emulated accelerometer reports on, the clock
## that reading is derived on, and which of the two accelerometers a remote is
## carrying at all. Whether either one reaches a running core needs Dolphin and
## a game, and is checked by playing one.
##
## The change of basis is the reason this file exists. It is two coordinate
## changes in a row, nothing downstream complains about a wrong one, and the
## game just tilts the wrong way — so every axis is pinned here against a pose
## whose answer is known from the physics rather than from the code.
extends Node

const NUNCHUK_SCENE := preload("res://Scenes/Objects/controllers/wii/nunchuk.tscn")
const WIIMOTE_SCENE := preload("res://Scenes/Objects/controllers/wii/wiimote.tscn")
const MOTION_PLUS_SCENE := preload("res://Scenes/Objects/controllers/wii/motion_plus.tscn")

## Tolerance on a g reading. Generous, because these are floats through two
## basis inversions; a wrong AXIS is off by a whole g, not by a thousandth.
const EPS := 0.001

var _pass := 0
var _fail := 0
var _only := ""


func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--only="):
			_only = arg.substr(7)
	get_tree().create_timer(60.0).timeout.connect(func() -> void:
		print("[motion] TIMEOUT")
		get_tree().quit(1))

	if _wants("accel"):
		await _test_at_rest_upright()
		await _test_at_rest_inverted()
		await _test_top_forward_reads_back()
		await _test_top_right_reads_left()
		await _test_always_one_g_at_rest()
		await _test_smoothing_settles_on_rest()
	if _wants("clock"):
		await _test_a_carried_nunchuk_reads_the_path_it_is_carried_on()
		await _test_a_gentle_carry_keeps_the_pose()
		await _test_motion_is_not_a_button()
	if _wants("pair"):
		_test_the_extension_takes_a_sub_device()
		await _test_bare_remote()
		await _test_a_seated_nunchuk()
		await _test_a_nunchuk_behind_a_dongle()
		await _test_pulling_the_extension()

	print("[motion] ---- %d passed, %d failed ----" % [_pass, _fail])
	get_tree().quit(1 if _fail > 0 else 0)


func _wants(group: String) -> bool:
	return _only.is_empty() or _only == group


func _ok(name: String, cond: bool, detail := "") -> void:
	if cond:
		_pass += 1
		print("[motion] PASS %s" % name)
	else:
		_fail += 1
		print("[motion] FAIL %s%s" % [name, "" if detail.is_empty() else "  (%s)" % detail])


func _vec_ok(name: String, got: Vector3, want: Vector3) -> void:
	_ok(name, got.distance_to(want) < EPS, "got %v, want %v" % [got, want])


# ── The accelerometer's frame ────────────────────────────────────────────────
# Dolphin's IMUAccelerometer reports on the device's OWN axes: +X left, +Y back,
# +Z up. Proper acceleration is what an accelerometer measures, so a device at
# rest reads +1 g along whichever of its own axes happens to point at the sky.
# Each case below tips the shell a known way and names the axis that should be
# reading, which is a fact about gravity rather than a restatement of the code.

## A Nunchuk added to the tree and left alone: no velocity, so at rest.
##
## Frozen, and that is load-bearing rather than tidiness. Added to a bare test
## scene it is a loose rigid body over no floor, so it falls — and a falling
## accelerometer correctly reads WEIGHTLESS, which is the one thing none of the
## cases below mean by "at rest". Every one of them wants a device sitting on
## something.
func _at_rest_nunchuk() -> Nunchuk:
	var nc: Nunchuk = NUNCHUK_SCENE.instantiate()
	nc.freeze = true
	add_child(nc)
	await get_tree().process_frame
	return nc


## Hold the pose for long enough that the low-pass has nothing left to converge
## on. A single frame would be testing the smoothing, not the basis change.
func _settle(nc: Nunchuk) -> void:
	for i in range(60):
		nc._update_accel(1.0 / 60.0)


func _test_at_rest_upright() -> void:
	var nc := await _at_rest_nunchuk()
	nc.global_transform = Transform3D.IDENTITY
	_settle(nc)
	# Stick end up, which is the device's own up, so gravity is felt entirely
	# along it. This is also the reading the GDExtension serves when nothing has
	# ever driven the sensor, which is what makes it the right default.
	_vec_ok("upright at rest reads one g on the up axis",
		nc.accel_in_nunchuk_frame(), Vector3(0, 0, 1))
	nc.queue_free()


func _test_at_rest_inverted() -> void:
	var nc := await _at_rest_nunchuk()
	# Turned over: the stick end points at the floor.
	nc.global_transform = Transform3D(Basis(Vector3.FORWARD, PI), Vector3.ZERO)
	_settle(nc)
	_vec_ok("upside down reads one g the other way",
		nc.accel_in_nunchuk_frame(), Vector3(0, 0, -1))
	nc.queue_free()


func _test_top_forward_reads_back() -> void:
	var nc := await _at_rest_nunchuk()
	# Tipped nose-down through a right angle about X, so the stick end now points
	# where the buttons were facing. The sky is off the shell's rear face, so the
	# device feels gravity on the axis Dolphin calls back.
	nc.global_transform = Transform3D(Basis(Vector3.RIGHT, -PI / 2.0), Vector3.ZERO)
	_settle(nc)
	_vec_ok("stick end forward reads one g on the back axis",
		nc.accel_in_nunchuk_frame(), Vector3(0, 1, 0))
	nc.queue_free()


func _test_top_right_reads_left() -> void:
	var nc := await _at_rest_nunchuk()
	# Laid over to the right: the stick end points to world +X, so the sky is now
	# off the shell's LEFT side, which is the axis Dolphin calls +X.
	nc.global_transform = Transform3D(Basis(Vector3.BACK, -PI / 2.0), Vector3.ZERO)
	_settle(nc)
	_vec_ok("stick end to the right reads one g on the left axis",
		nc.accel_in_nunchuk_frame(), Vector3(1, 0, 0))
	nc.queue_free()


func _test_always_one_g_at_rest() -> void:
	var nc := await _at_rest_nunchuk()
	# However it is lying, a still device feels exactly one gravity. A basis
	# change that scaled or skewed would still pass an axis case pointing the
	# right way, and would fail here.
	var worst := 0.0
	for step in range(12):
		var a := TAU * float(step) / 12.0
		nc.global_transform = Transform3D(
			Basis(Vector3(0.6, 0.8, 0.0).normalized(), a), Vector3.ZERO)
		_settle(nc)
		worst = maxf(worst, absf(nc.accel_in_nunchuk_frame().length() - 1.0))
	_ok("a still Nunchuk reads one g whichever way it lies", worst < EPS,
		"worst error %f g" % worst)
	nc.queue_free()


func _test_smoothing_settles_on_rest() -> void:
	var nc := await _at_rest_nunchuk()
	nc.global_transform = Transform3D.IDENTITY
	# Straight out of the scene, before anything has driven it. A smoothed value
	# starting at zero would read as freefall for the first tenth of a second,
	# which is a Nunchuk that has been dropped rather than one just picked up.
	_vec_ok("a Nunchuk reads at rest before it is ever driven",
		nc.accel_in_nunchuk_frame(), Vector3(0, 0, 1))
	nc.queue_free()


# ── Which clock the reading is derived on ────────────────────────────────────
# The cases above hand _update_accel a velocity and a delta, so they cannot tell
# WHO calls it — and that is the whole of the defect these two exist for. A held
# Nunchuk is a frozen kinematic body the grab driver moves in its own
# _physics_process, so linear_velocity changes on the physics tick and nowhere
# else. Differentiated from _process it is a step function sampled off-phase and
# divided by the wrong number, which over-read a brisk 30 cm wave by 3.7x and
# swung the pose the core reads a hand's position from by up to 84 degrees.
#
# So these drive a real body along a known path through real physics and check
# the arithmetic against what the path says the answer is.

## Carry a Nunchuk along x = amp*sin(2*PI*hz*t) for one second of physics, the
## way a hand carries it: frozen kinematic, moved on the physics tick. Answers
## with the worst motion component and the worst pose error seen.
func _carry(nc: Nunchuk, amp: float, hz: float) -> Dictionary:
	nc.freeze = true
	nc.freeze_mode = RigidBody3D.FREEZE_MODE_KINEMATIC
	nc.global_transform = Transform3D(Basis(), Vector3(0, 1.2, 0))
	var t := 0.0
	var peak := 0.0
	var tilt := 0.0
	# A settling lap first: the low-pass starts at rest and the first ticks are
	# it catching up, not the path.
	for tick in range(int(1.5 * Engine.physics_ticks_per_second)):
		t += 1.0 / float(Engine.physics_ticks_per_second)
		nc.global_position = Vector3(amp * sin(TAU * hz * t), 1.2, 0)
		await get_tree().physics_frame
		if t < 0.5:
			continue
		peak = maxf(peak, (nc._accel_smoothed - Vector3.UP * Nunchuk.G).length())
		# Upright the whole way, so the reading should be one g on the device's
		# own up axis, leaned over by exactly as much as the motion justifies.
		var g_vec := nc.accel_in_nunchuk_frame()
		if g_vec.length() > 0.001:
			tilt = maxf(tilt, rad_to_deg(g_vec.normalized().angle_to(Vector3(0, 0, 1))))
	return {"peak": peak, "tilt": tilt}


func _test_a_carried_nunchuk_reads_the_path_it_is_carried_on() -> void:
	var nc := await _at_rest_nunchuk()
	# 30 cm peak to peak at 2 Hz — a brisk wave of the arm, well inside what a
	# player does. Its acceleration is amp*(2*PI*hz)^2 and nothing else.
	var amp := 0.15
	var hz := 2.0
	var got: Dictionary = await _carry(nc, amp, hz)
	var want := amp * pow(TAU * hz, 2.0)
	var ratio: float = float(got["peak"]) / want
	# The band is wide on purpose: the low-pass costs about a tenth at this rate
	# and a second difference is not a derivative. It is nowhere near wide enough
	# to admit a reading taken off the render clock.
	_ok("a carried Nunchuk reports the acceleration of the path it is on",
		ratio > 0.7 and ratio < 1.3,
		"%.1f m/s^2 against a true %.1f (%.2fx)" % [got["peak"], want, ratio])
	nc.queue_free()


func _test_a_gentle_carry_keeps_the_pose() -> void:
	var nc := await _at_rest_nunchuk()
	# 10 cm at half a hertz: 0.49 m/s^2, a twentieth of a g. A real
	# accelerometer leans by atan(0.49/9.81) = 2.9 degrees under it and no more,
	# and that lean IS the hand position Dolphin's IMUAccelerometer draws from.
	var got: Dictionary = await _carry(nc, 0.05, 0.5)
	_ok("a gently carried Nunchuk still reports which way is up",
		float(got["tilt"]) < 5.0, "worst pose error %.1f degrees" % got["tilt"])
	nc.queue_free()


## Motion used to double as a button: a magnitude over a threshold set L2, the
## core's "Shake Nunchuk", which Dolphin composes ON TOP of the accelerometer as
## a canned burst. With a real accelerometer behind it that is a second and
## larger punch behind every real one, and it fired on hand tremor — two
## millimetres of tracking jitter cleared it on 40% of frames.
func _test_motion_is_not_a_button() -> void:
	var wm: Wiimote = WIIMOTE_SCENE.instantiate()
	var nc: Nunchuk = NUNCHUK_SCENE.instantiate()
	add_child(wm)
	add_child(nc)
	await get_tree().process_frame
	wm._on_extension_seated(nc)
	_ok("a Nunchuk reports no shake", not nc.get_state().has("shake"))
	# Thrown hard enough that any threshold anyone would pick is behind it.
	nc.linear_velocity = Vector3.ZERO
	nc._update_accel(1.0 / 90.0)
	nc.linear_velocity = Vector3(6.0, 0.0, 0.0)
	nc._update_accel(1.0 / 90.0)
	var mask: int = wm._button_mask(wm._pressed_now())
	_ok("and however hard it is thrown, the remote sends no L2",
		mask & (1 << ControllerBindings.JOYPAD_L2) == 0,
		"mask %d" % mask)
	wm.queue_free()
	nc.queue_free()
	nc.queue_free()


# ── Which accelerometers a remote is carrying ────────────────────────────────
# The remote owns the libretro slot and makes every call for the pair, so the
# question "is there a second accelerometer" is answered here and nowhere else.

## The remote passes a sub-device index to the extension, and an extension built
## before that existed would take the call and drop the argument on the floor —
## a Nunchuk whose motion silently lands on the remote's own accelerometer. The
## binding is checked rather than the call, because there is no reader for sensor
## state to assert against, and a case that cannot fail is worse than none.
func _test_the_extension_takes_a_sub_device() -> void:
	var arity := -1
	for method: Dictionary in ClassDB.class_get_method_list("Libretro"):
		if str(method.get("name", "")) == "SetSensorAccel":
			arity = (method.get("args", []) as Array).size()
			break
	_ok("the extension's SetSensorAccel takes a sub-device index", arity == 5,
		"found %d arguments, want 5" % arity)


func _test_bare_remote() -> void:
	var wm: Wiimote = WIIMOTE_SCENE.instantiate()
	add_child(wm)
	await get_tree().process_frame
	_ok("a bare remote is a plain Wiimote", wm.device_type == Wiimote.RETRO_DEVICE_WIIMOTE)
	_ok("and reports no Nunchuk", not wm._has_nunchuk())
	wm.queue_free()


func _test_a_seated_nunchuk() -> void:
	var wm: Wiimote = WIIMOTE_SCENE.instantiate()
	var nc: Nunchuk = NUNCHUK_SCENE.instantiate()
	add_child(wm)
	add_child(nc)
	await get_tree().process_frame
	wm._on_extension_seated(nc)
	_ok("a seated Nunchuk makes it a Nunchuk remote",
		wm.device_type == Wiimote.RETRO_DEVICE_WIIMOTE_NC)
	_ok("and the remote can reach it", wm._nunchuk == nc)
	_ok("so it will send a second accelerometer", wm._has_nunchuk())
	wm.queue_free()
	nc.queue_free()


func _test_a_nunchuk_behind_a_dongle() -> void:
	var wm: Wiimote = WIIMOTE_SCENE.instantiate()
	var mp: MotionPlus = MOTION_PLUS_SCENE.instantiate()
	var nc: Nunchuk = NUNCHUK_SCENE.instantiate()
	add_child(wm)
	add_child(mp)
	add_child(nc)
	await get_tree().process_frame
	# Dongle first, then the Nunchuk into the dongle's own pass-through. The
	# remote cannot see that zone, so this only works if it followed the chain.
	wm._on_extension_seated(mp)
	mp._on_nunchuk_seated(nc)
	_ok("a Nunchuk behind a dongle is still reachable", wm._nunchuk == nc)
	_ok("the pair is a MotionPlus Nunchuk remote",
		wm.device_type == Wiimote.RETRO_DEVICE_WIIMOTE_MP_NC)
	_ok("and it still sends a second accelerometer", wm._has_nunchuk())
	wm.queue_free()
	mp.queue_free()
	nc.queue_free()


func _test_pulling_the_extension() -> void:
	var wm: Wiimote = WIIMOTE_SCENE.instantiate()
	var nc: Nunchuk = NUNCHUK_SCENE.instantiate()
	add_child(wm)
	add_child(nc)
	await get_tree().process_frame
	wm._on_extension_seated(nc)
	wm._on_extension_removed()
	_ok("pulling the Nunchuk puts the remote back",
		wm.device_type == Wiimote.RETRO_DEVICE_WIIMOTE)
	_ok("and it stops claiming a second accelerometer", not wm._has_nunchuk())
	wm.queue_free()
	nc.queue_free()
