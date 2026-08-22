## NetplayCores — which cores may hold a deterministic lockstep session, and the
## options each is pinned to.
##
## Vetted with Tools/netplay_spike.gd. `verified` is cold-start determinism:
## two processes running the same inputs from frame 0 produce identical RAM-CRC
## streams, which is all a session needs while everybody starts together.
## `state_transfer` is savestate reload fidelity, which only a late join and a
## desync resync need. `rollback` needs a state cheap enough to take every frame.
## A core not listed here falls back to the "LIVE on host" placeholder.
##
## `options` are forced on every peer at cold start so a peer's own core-option
## config cannot introduce divergence.
##
## core_name -> { verified, state_transfer, rollback, systems, options }
class_name NetplayCores
extends RefCounted

const CORES: Dictionary = {
	"fceumm": {
		"verified": true,
		"state_transfer": true,
		"rollback": true,
		"systems": ["nes"],
		"options": {},
	},
	"gambatte": {
		"verified": true,
		"state_transfer": false,
		"rollback": false,
		"systems": ["game_boy", "game_boy_color"],
		"options": {},
	},
	"mgba": {
		"verified": true,
		"state_transfer": true,
		"rollback": false,
		"systems": ["game_boy_advance", "game_boy", "game_boy_color"],
		"options": {},
	},
	"snes9x": {
		"verified": true,
		"state_transfer": true,
		"rollback": false,
		"systems": ["super_nes"],
		"options": {},
	},
	"genesis_plus_gx": {
		"verified": true,
		"state_transfer": true,
		"rollback": false,
		"systems": ["megadrive", "genesis"],
		"options": {},
	},
}


## Debug: let an UNVETTED core start a session anyway.
##
## The allowlist refuses to start rather than risk a silent desync, but the
## session already detects one — periodic RAM CRCs, a savestate resync, three
## strikes to spectator. Refusing to start is belt-and-braces, and it forecloses
## its own evidence: a core cannot be shown deterministic-in-practice if nothing
## may run it. This switch is how a core gets MEASURED before it is listed.
##
## A static, deliberately, and never written to AppPrefs: a debug option that
## survives a restart is one a player can be left stranded in.
static var debug_allow_unverified := false


## True if the core is on the allowlist AND has passed determinism vetting.
static func is_capable(core_name: String) -> bool:
	if debug_allow_unverified and not core_name.is_empty():
		return true
	var e: Dictionary = CORES.get(core_name, {})
	return bool(e.get("verified", false))


## Deterministic core options to force on every peer for this core (may be empty).
static func forced_options(core_name: String) -> Dictionary:
	var e: Dictionary = CORES.get(core_name, {})
	return (e.get("options", {}) as Dictionary).duplicate()


## True when the core supports rollback netplay: verified deterministic AND
## cheap enough to savestate every frame (rollback rewinds via a state ring).
static func rollback_capable(core_name: String) -> bool:
	var e: Dictionary = CORES.get(core_name, {})
	return bool(e.get("verified", false)) and bool(e.get("rollback", false))


## True when a state captured from this core can be restored by another peer,
## which is what a late join and a desync resync both put on the wire. False
## means a session still PLAYS, from a cold start, with everyone present.
##
## Deliberately NOT covered by debug_allow_unverified: that switch exists to let
## a core be measured, and shipping it a state that will not restore measures
## nothing. An unlisted core answers false here.
static func state_transfer_capable(core_name: String) -> bool:
	var e: Dictionary = CORES.get(core_name, {})
	return bool(e.get("verified", false)) and bool(e.get("state_transfer", false))
