## MotionFilter — the noise floor under a hand-tracked accelerometer.
##
## A held remote's acceleration is a SECOND difference of a tracked pose, and
## double differentiation multiplies position noise by the frame rate squared:
## half a millimetre of tracking jitter at 90 Hz is already several m/s^2. The
## low-pass in _update_accel averages that down but cannot remove it, and what
## is left does not read as noise on screen — it tilts the vector the game reads
## the controller's POSE from, so a perfectly still hand wobbles.
##
## Measured on a Nunchuk held still with jitter, worst pose error over 2 s:
##
##     jitter   as shipped   heavier low-pass   deadband 5
##     0.5 mm       12.4 deg          5.7 deg      0.0 deg
##     1.0 mm       24.2 deg         11.2 deg      0.0 deg
##     a punch    57.3 m/s^2       37.0 m/s^2   52.3 m/s^2
##
## Which is why this is a deadband and not simply more smoothing. Smoothing hard
## enough to halve the wobble costs a third of the punch; the deadband takes the
## wobble to zero for 9% of it, because a punch is an order of magnitude above
## the noise and there is nothing real in between.
class_name MotionFilter
extends RefCounted

## Motion below this, in m/s^2, is treated as tracking noise. Half a g: no hand
## sustains that without meaning to, and every still-hand case above sits under
## it while a punch is ten times it.
const DEADBAND := 5.0


## Strip the noise floor out of a proper-acceleration vector, leaving gravity
## exactly as it was.
##
## Two things are load-bearing. It acts on the MOTION term alone — gravity is
## what carries the pose, and a deadband on the whole vector would drag the
## reported pose toward vertical. And it must run AFTER the low-pass, not before:
## per-tick jitter spikes are tens of m/s^2, so a deadband ahead of the filter
## catches almost none of them (measured: 12.4 deg to 10.6 deg, no use at all).
##
## Soft knee — the excess is kept rather than the whole magnitude — so the output
## is continuous across the threshold instead of snapping on.
static func deadband_motion(accel: Vector3, gravity: float) -> Vector3:
	var up := Vector3.UP * gravity
	var motion := accel - up
	var mag := motion.length()
	if mag <= DEADBAND:
		return up
	return up + motion * ((mag - DEADBAND) / mag)
