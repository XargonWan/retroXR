## GameCube-to-GBA link, with the two real cores.
##
##   "$godot" --headless --path RetroXR res://Tools/gc_gba_link_probe.tscn -- \
##       --gc-rom="C:/…/Four Swords Adventures (USA).rvz" \
##       --gba-rom="C:/…/Super Mario Advance (USA, Europe).gba"
##
## A probe: it wants Dolphin, mGBA and two commercial ROMs, so it cannot live in
## Tests/. It reports and asserts, and exits non-zero when the bus never forms.
##
## WHY. The GameCube lead is the asymmetric one and the only one whose ends are
## not even the same kind of socket: the wide end sits in a CONTROLLER port and
## announces itself as RETRO_DEVICE_GBA_LINK, while the barrel end sits in the
## handheld's EXT port. Everything about it has been reasoned and unit-tested
## and never once run with the cores that actually speak the JOY bus.
##
## It reproduces exactly what GcGbaCable does when a player seats the lead:
## SetControllerPortDevice((7 << 8) | 0) on the console's port, then
## LinkConnect(gba, console_port, GBA_JOY_PORT). Nothing here is a shortcut past
## the room's own path.
##
## WHAT A PASS MEANS, AND WHAT IT DOES NOT. This proves the BUS: that both cores
## attach, find each other, and carry bytes. It does not prove either game does
## anything with them. Four Swords Adventures uses the GBA as a screen-and-pad
## and uploads its own program over the wire — the real pairing has NO cartridge
## in the handheld at all (multiboot / single-pak). A GBA sitting on its own
## commercial cartridge is a legitimate cabling but not a conversation either
## title was written for, so zero game-level traffic there is information, not
## necessarily a fault.
extends Node

static var _home := OS.get_environment("HOME") if OS.get_name() == "Linux" \
		else OS.get_environment("USERPROFILE").replace("\\", "/")

## Matches GcLinkPlug.DEVICE_GBA_LINK and DolphinLibretro's RETRO_DEVICE_GBA_LINK.
const DEVICE_GBA_LINK := (7 << 8) | 0
## Matches GcGbaCable.GBA_JOY_PORT: which of the handheld's two conversations
## this cable is. Not the same number as the console's socket index.
const GBA_JOY_PORT := 1
const GC_PORT := 0

const BOOT_TICKS := 1800      ## Dolphin takes a while to have a machine at all
const RUN_TICKS := 2400

var root_dir := _home + "/retroxr/libretro"
var gc_core := "dolphin"
var gba_core := "mgba"
var gc_rom := _home + "/retroxr/roms/gamecube/Legend of Zelda, The - Four Swords Adventures (USA).rvz"
var gba_rom := _home + "/retroxr/roms/game_boy_advance/Super Mario Advance (USA, Europe).gba"
## Cable the handheld with NO cartridge, which is what Four Swords Adventures
## actually expects: the console uploads the program over the wire.
var gba_empty := false
## Boot both cores and run them side by side WITHOUT cabling them, so the cost
## of the bus can be told from the cost of Dolphin.
var no_cable := false

var _gc: Node = null
var _gba: Node = null
var _ticks := 0
var _cabled := false
var _fail := 0
var _done := false
var _peak_traffic := [0, 0]
var _run_started_ms := 0
var _frames_at_start := [0, 0]


func _ready() -> void:
	for arg: String in OS.get_cmdline_user_args():
		arg = arg.strip_edges()
		if arg.begins_with("--gc-rom="):
			gc_rom = arg.trim_prefix("--gc-rom=")
		elif arg.begins_with("--gba-rom="):
			gba_rom = arg.trim_prefix("--gba-rom=")
		elif arg.begins_with("--gc-core="):
			gc_core = arg.trim_prefix("--gc-core=")
		elif arg.begins_with("--gba-core="):
			gba_core = arg.trim_prefix("--gba-core=")
		elif arg.begins_with("--root="):
			root_dir = arg.trim_prefix("--root=")
		elif arg == "--gba-empty":
			gba_empty = true
		elif arg == "--no-cable":
			no_cable = true
	get_tree().create_timer(600.0).timeout.connect(func() -> void:
		print("[gcgba] TIMEOUT at tick %d" % _ticks)
		_report()
		get_tree().quit(1))

	_gc = _spawn(gc_core, gc_rom)
	_gba = _spawn(gba_core, "" if gba_empty else gba_rom)
	print("[gcgba] %s <- %s" % [gc_core, gc_rom.get_file()])
	print("[gcgba] %s <- %s" % [gba_core, "(no cartridge, multiboot)" if gba_empty else gba_rom.get_file()])


func _spawn(core: String, rom: String) -> Node:
	var obj: Object = ClassDB.instantiate("Libretro")
	var lib: Node = obj as Node
	add_child(lib)
	lib.StartContent(root_dir, core, rom)
	return lib


func _process(_d: float) -> void:
	if _done or _gc == null or _gba == null:
		return
	_ticks += 1

	if not _cabled:
		# Both cores have to be UP before the lead means anything: a bus joined
		# before a core has attached its serial hardware is a wire with no ends.
		var gc_up: bool = not (_gc.GetCoreIdentity() as Dictionary).is_empty()
		var gba_up: bool = not (_gba.GetCoreIdentity() as Dictionary).is_empty()
		if not (gc_up and gba_up):
			if _ticks > BOOT_TICKS:
				_bad("a core never came up (gc=%s gba=%s)" % [gc_up, gba_up])
				_report()
				get_tree().quit(1)
			return
		_cabled = true
		_run_started_ms = Time.get_ticks_msec()
		_frames_at_start = [int(_gc.GetFrameCount()), int(_gba.GetFrameCount())]
		print("[gcgba] gc  = %s" % _ident(_gc))
		print("[gcgba] gba = %s" % _ident(_gba))
		if no_cable:
			print("[gcgba] NOT cabling (control run)")
			return
		# Exactly what GcGbaCable does on seating, in the same order.
		_gc.SetControllerPortDevice(GC_PORT, DEVICE_GBA_LINK)
		var ok: bool = _gc.LinkConnect(_gba, GC_PORT, GBA_JOY_PORT)
		print("[gcgba] LinkConnect -> %s (console port %d <-> handheld JOY %d)" % [
			ok, GC_PORT, GBA_JOY_PORT])
		if not ok:
			_bad("the two cores refused to share a wire")
		return

	var t0 := int(_gc.LinkTraffic(GC_PORT))
	var t1 := int(_gba.LinkTraffic(GBA_JOY_PORT))
	_peak_traffic[0] = maxi(_peak_traffic[0], t0)
	_peak_traffic[1] = maxi(_peak_traffic[1], t1)

	if _ticks % 600 == 0:
		print("[gcgba] tick %d: gc frame %d, gba frame %d, peers %d/%d, traffic %d/%d" % [
			_ticks, _gc.GetFrameCount(), _gba.GetFrameCount(),
			_gc.LinkPeerCount(GC_PORT), _gba.LinkPeerCount(GBA_JOY_PORT), t0, t1])

	if _ticks >= BOOT_TICKS + RUN_TICKS:
		_report()
		_done = true
		_gc.StopContent()
		_gba.StopContent()
		await get_tree().create_timer(3.0).timeout
		print("[gcgba] RESULT=%s" % ("FAIL" if _fail > 0 else "PASS"))
		get_tree().quit(1 if _fail > 0 else 0)


func _report() -> void:
	var gc_peers: int = _gc.LinkPeerCount(GC_PORT) if _gc != null else 0
	var gba_peers: int = _gba.LinkPeerCount(GBA_JOY_PORT) if _gba != null else 0
	print("[gcgba] ---- gc frames=%d gba frames=%d" % [
		_gc.GetFrameCount() if _gc else -1, _gba.GetFrameCount() if _gba else -1])
	print("[gcgba] ---- peers: console %d, handheld %d" % [gc_peers, gba_peers])
	print("[gcgba] ---- traffic peak: console %d, handheld %d" % [
		_peak_traffic[0], _peak_traffic[1]])
	# What the bus COSTS, which is the number to compare between a cabled run
	# and a --no-cable control. Emulated frames per real second: 60 is a machine
	# keeping up with itself, and anything well under that is the player waiting.
	var secs := float(Time.get_ticks_msec() - _run_started_ms) / 1000.0
	if secs > 0.0:
		var gc_fps := float(int(_gc.GetFrameCount()) - _frames_at_start[0]) / secs
		var gba_fps := float(int(_gba.GetFrameCount()) - _frames_at_start[1]) / secs
		print("[gcgba] ---- throughput over %.1f s: console %.1f fps, handheld %.1f fps%s" % [
			secs, gc_fps, gba_fps, "  (UNCABLED control)" if no_cable else ""])
	if no_cable:
		return
	# The bus forming is the claim this probe makes. Both ends must SEE each
	# other; a count of 1 is a lead hanging out of a socket.
	if gc_peers < 2:
		_bad("the console never saw a peer on its JOY bus")
	if gba_peers < 2:
		_bad("the handheld never saw a peer on its JOY bus")
	if _peak_traffic[0] == 0 and _peak_traffic[1] == 0:
		print("[gcgba] NOTE: the wire carried nothing. Expected when the handheld")
		print("[gcgba]       holds its own cartridge: Four Swords Adventures")
		print("[gcgba]       uploads a program to an EMPTY GBA (--gba-empty).")


func _ident(lib: Node) -> String:
	var d: Dictionary = lib.GetCoreIdentity()
	return "%s %s" % [str(d.get("library_name", "?")), str(d.get("library_version", "?"))]


func _bad(why: String) -> void:
	_fail += 1
	print("[gcgba] FAIL %s" % why)
