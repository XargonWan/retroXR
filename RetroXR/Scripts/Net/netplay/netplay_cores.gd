## NetplayCores — allowlist of libretro cores verified safe for deterministic
## lockstep netplay, plus the deterministic options each one needs.
##
## A core only becomes netplay-capable once it has been vetted with
## Tools/netplay_spike.gd: savestate round-trip AND two cold-started processes
## must produce identical RAM-CRC streams. Cores not listed here fall back to
## the pre-netplay "LIVE on host" placeholder for remote peers.
##
## `options` are forced on every peer at cold start so a peer's local core-option
## config can't introduce divergence (e.g. threaded renderers, frameskip, RNG).
class_name NetplayCores
extends RefCounted

## TWO PROPERTIES, NOT ONE. `verified` is cold-start determinism: two processes
## running the same inputs from frame 0 produce identical RAM-CRC streams. That
## is all a lockstep session needs while everybody starts together, and it is
## what makes a game playable.
##
## `state_transfer` is savestate RELOAD fidelity: a state captured and restored
## reproduces the same stream. Only a late join and a desync resync need it,
## because only they put a state on the wire.
##
## They are genuinely different, and gambatte is the proof: it reproduces
## perfectly from a cold start across two processes, and fails 16 of 20
## checkpoints after reloading its own state. One flag for both would either
## bar a core that plays fine or promise a late join that cannot work.
##
## core_name -> { verified, state_transfer, rollback, systems, options, notes }
const CORES: Dictionary = {
	"fceumm": {
		"verified": true,
		"state_transfer": true,
		"rollback": true,   # serialization is fast+small (13.7 KB) — per-frame savestates OK
		"systems": ["nes"],
		"options": {},   # SMB passed determinism with defaults
		"notes": "NES. Verified GREEN 2026-07-05 (savestate + cold-start cross-process CRC match; x64<->arm64 verified 2026-07-06).",
	},
	"gambatte": {
		"verified": true,
		# Fails its own savestate reload, so no late join and no resync. The
		# round-trip probe localises it: 15 bytes differ in the state's first
		# 1.7 KB and the offsets MOVE between runs, which is host-clock or RTC
		# leakage in a header rather than anything about the emulated machine.
		"state_transfer": false,
		# Rollback rewinds through a state every frame, which is the one thing
		# this core cannot reproduce.
		"rollback": false,
		"systems": ["game_boy", "game_boy_color"],
		"options": {},
		"notes": "Game Boy / Color. Cold-start GREEN 2026-08-21: identical CRC streams across two processes on Pokemon Yellow, 30 distinct checkpoints. Savestate reload RED, 16/20 mismatches, so no late join. GB and GBC link verified over netplay the same day, two peers, 0 desyncs. NOTE: the first vetting run used Tools/gblink ROMs and passed with a CONSTANT CRC at every checkpoint - an oracle that cannot fail. Vet against a real game.",
	},
	# Pending vetting with netplay_spike before they can be enabled:
	"snes9x": {
		"verified": false,
		"systems": ["super_nes"],
		"options": {},
		"notes": "SNES. Not yet spike-verified.",
	},
	"genesis_plus_gx": {
		"verified": false,
		"systems": ["megadrive", "genesis", "master_system", "game_gear"],
		"options": {},
		"notes": "Sega. Not yet spike-verified.",
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


static func notes(core_name: String) -> String:
	var e: Dictionary = CORES.get(core_name, {})
	return str(e.get("notes", ""))
