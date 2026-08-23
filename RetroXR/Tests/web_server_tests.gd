## Web file server self-tests — the request-parsing and path-confinement half of
## WebFileServer, run headless with no socket, no browser and no client.
##
##     "$godot" --headless --path RetroXR res://Tests/web_server_tests.tscn
##     "$godot" --headless --path RetroXR res://Tests/web_server_tests.tscn -- --only=resolve
##
## Exits 0 when everything passes, 1 otherwise, so it can gate a commit.
##
## Why this exists: web_file_server.gd is 816 lines of hand-rolled HTTP — request
## line splitting, multipart upload streaming, a PIN cookie, and a path resolver
## that maps a URL onto the player's real disk — and it had no coverage of any
## kind. The resolver is the part that matters. It is reachable by anything on the
## LAN that has the PIN, and it decides which absolute path a request is allowed
## to read, overwrite or delete, so a mistake there is a security bug rather than
## a cosmetic one. Every `escape/` case below is a path that must NOT resolve.
##
## Nothing here starts the server. `start()` binds a TCP port and spawns a thread;
## a test that did it would be flaky under CI and would prove less than these do,
## because the interesting logic is all reachable directly.
##
## No files are read or written. The resolver is pure string work against the two
## named roots, and the two roots are derived from statics (server_root() and
## CoreDownloadManager.default_core_root()) that this asks for rather than assumes,
## so the cases hold whatever the player's roots happen to be.
extends Node

var _pass := 0
var _fail := 0
var _only := ""

var _srv: WebFileServer = null

## The "media" root, as the server itself computes it.
var _media := ""


func _ready() -> void:
	get_tree().create_timer(60.0).timeout.connect(func() -> void:
		print("[test] TIMEOUT")
		_cleanup()
		get_tree().quit(1))

	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--only="):
			_only = arg.substr(7)

	_srv = WebFileServer.new()
	_media = WebFileServer.server_root()

	if _wants("resolve"):
		_test_resolve_inside_root()
		_test_resolve_rejects_unknown_root()
	if _wants("escape"):
		_test_escape_to_sibling()
		_test_escape_upward()
		_test_escape_encoded()
	if _wants("subpath"):
		_test_safe_subpath()
	if _wants("parse"):
		_test_parse_query()
		_test_cookie()
		_test_extract_pin()
		_test_extract_filename()
		_test_find_bytes()

	_cleanup()
	print("[test] ---- %d passed, %d failed ----" % [_pass, _fail])
	get_tree().quit(1 if _fail > 0 else 0)


func _wants(group: String) -> bool:
	return _only.is_empty() or _only == group


func _cleanup() -> void:
	if is_instance_valid(_srv):
		_srv.free()
		_srv = null


func _ok(name: String, cond: bool, detail: String = "") -> void:
	if cond:
		_pass += 1
		print("[test] PASS  %s" % name)
	else:
		_fail += 1
		print("[test] FAIL  %s%s" % [name, "  — " + detail if not detail.is_empty() else ""])


func _eq(name: String, got: Variant, want: Variant) -> void:
	_ok(name, got == want, "got %s, want %s" % [str(got), str(want)])


## Asserts a URL path resolves to nothing at all. The failure detail prints what
## it DID resolve to, because "" vs "somewhere outside the root" is the whole
## difference between a confined server and an open one.
func _denied(name: String, rel: String) -> void:
	var got: String = _srv._resolve(rel)
	_ok("escape/" + name, got.is_empty(), "resolved to %s" % got)


# ── The resolver, inside its roots ────────────────────────────────────────────

func _test_resolve_inside_root() -> void:
	_eq("resolve/the virtual top level has no single path", _srv._resolve(""), "")
	_eq("resolve/a named root resolves to its base", _srv._resolve("media"), _media)
	_eq("resolve/a file under it keeps the root prefix",
		_srv._resolve("media/roms/nes/game.nes"), _media + "/roms/nes/game.nes")
	_eq("resolve/a percent-encoded space decodes",
		_srv._resolve("media/roms/my%20game.nes"), _media + "/roms/my game.nes")
	# Interior traversal that stays inside is legitimate and must still work --
	# a confinement check that rejects every ".." is too blunt and breaks the UI's
	# own "up one directory" link.
	_eq("resolve/traversal that lands back inside is allowed",
		_srv._resolve("media/roms/../roms/game.nes"), _media + "/roms/game.nes")
	_ok("resolve/the second named root resolves too",
		not _srv._resolve("libretro").is_empty())


func _test_resolve_rejects_unknown_root() -> void:
	_eq("resolve/an unknown root is refused", _srv._resolve("etc/passwd"), "")
	_eq("resolve/and so is a bare filename", _srv._resolve("secret.txt"), "")
	# The root name is matched whole, so a name that merely starts with a real
	# one is not a root.
	_eq("resolve/a root name is not a prefix match", _srv._resolve("mediaevil/x"), "")


# ── The resolver, under attack ────────────────────────────────────────────────

## The case that was live: a bare begins_with(base) also accepts a SIBLING
## directory whose name starts with the root's, so one ".." out and back into
## "<root>_evil" cleared the guard and served a file from outside the root.
func _test_escape_to_sibling() -> void:
	var sibling := _media.get_file() + "_evil"
	_denied("a sibling sharing the root's name prefix",
		"media/../%s/secret.txt" % sibling)
	_denied("the same escape from deeper in",
		"media/roms/../../%s/secret.txt" % sibling)
	_denied("and with the prefix continuing without a separator",
		"media/../%sX/secret.txt" % _media.get_file())


func _test_escape_upward() -> void:
	_denied("a plain walk out of the root", "media/../../secret.txt")
	_denied("a long walk toward the drive root",
		"media/../../../../../../../../Windows/win.ini")
	_denied("a walk out through a real subdirectory",
		"media/roms/../../../etc/passwd")


func _test_escape_encoded() -> void:
	# _resolve percent-decodes BEFORE splitting, so an encoded separator is
	# exactly as dangerous as a literal one and has to be judged after decoding.
	_denied("percent-encoded separators", "media%2F..%2F..%2Fsecret.txt")
	_denied("an encoded traversal after the root", "media/..%2F..%2Fsecret.txt")


# ── Upload filename sanitising ────────────────────────────────────────────────

## A folder upload carries a relative path in each part's filename, so this is
## the other place a client picks where bytes land.
func _test_safe_subpath() -> void:
	_eq("subpath/a plain name is kept", _srv._safe_subpath("game.nes"), "game.nes")
	_eq("subpath/a folder path is kept",
		_srv._safe_subpath("MyGame/save/data.001"), "MyGame/save/data.001")
	_eq("subpath/backslashes become separators",
		_srv._safe_subpath("MyGame\\save\\data.001"), "MyGame/save/data.001")
	_eq("subpath/traversal segments are dropped",
		_srv._safe_subpath("../../etc/passwd"), "etc/passwd")
	_eq("subpath/a traversal in the middle is dropped too",
		_srv._safe_subpath("MyGame/../../../x.nes"), "MyGame/x.nes")
	_eq("subpath/an absolute posix path loses its root",
		_srv._safe_subpath("/etc/passwd"), "etc/passwd")
	_eq("subpath/single dots are dropped", _srv._safe_subpath("./a/./b"), "a/b")
	_eq("subpath/empty segments collapse", _srv._safe_subpath("a//b"), "a/b")
	_eq("subpath/nothing usable gives nothing", _srv._safe_subpath("../.."), "")
	_eq("subpath/an empty name gives nothing", _srv._safe_subpath(""), "")


# ── Request parsing ───────────────────────────────────────────────────────────

func _test_parse_query() -> void:
	var q: Dictionary = _srv._parse_query("a=1&b=2")
	_eq("parse/a query splits into pairs", q.get("a", ""), "1")
	_eq("parse/and keeps the second", q.get("b", ""), "2")
	var enc: Dictionary = _srv._parse_query("path=roms%2Fmy%20game.nes")
	_eq("parse/values are percent-decoded", enc.get("path", ""), "roms/my game.nes")
	_eq("parse/an empty query is empty", _srv._parse_query("").size(), 0)
	# A bare flag has no "=", and the parser skips it rather than storing a null.
	_eq("parse/a valueless key is skipped", _srv._parse_query("flag").size(), 0)


func _test_cookie() -> void:
	_eq("parse/a cookie value is found",
		_srv._cookie("sid=abc123; other=1", "sid"), "abc123")
	_eq("parse/one later in the header is found too",
		_srv._cookie("other=1; sid=abc123", "sid"), "abc123")
	_eq("parse/a missing cookie is empty",
		_srv._cookie("other=1", "sid"), "")
	_eq("parse/an empty header is empty", _srv._cookie("", "sid"), "")


func _test_extract_pin() -> void:
	_eq("parse/a form pin is read", _srv._extract_pin("pin=1234"), "1234")
	_eq("parse/a pin among other fields is read",
		_srv._extract_pin("x=1&pin=4321&y=2"), "4321")
	_eq("parse/no pin field gives nothing", _srv._extract_pin("x=1"), "")


func _test_extract_filename() -> void:
	_eq("parse/a multipart filename is read",
		_srv._extract_filename('Content-Disposition: form-data; name="f"; filename="game.nes"'),
		"game.nes")
	_eq("parse/a filename with spaces survives",
		_srv._extract_filename('filename="my game.nes"'), "my game.nes")
	_eq("parse/no filename gives nothing",
		_srv._extract_filename('Content-Disposition: form-data; name="f"'), "")


func _test_find_bytes() -> void:
	var hay := "abcdefabc".to_utf8_buffer()
	_eq("parse/a needle is found at its offset",
		_srv._find_bytes(hay, "def".to_utf8_buffer()), 3)
	_eq("parse/searching from past it finds the later copy",
		_srv._find_bytes(hay, "abc".to_utf8_buffer(), 1), 6)
	_eq("parse/an absent needle is -1",
		_srv._find_bytes(hay, "zzz".to_utf8_buffer()), -1)
	# The multipart reader calls this on every incoming chunk, so a needle longer
	# than what has arrived so far is the normal case, not an edge one.
	_eq("parse/a needle longer than the haystack is -1",
		_srv._find_bytes("ab".to_utf8_buffer(), "abc".to_utf8_buffer()), -1)
