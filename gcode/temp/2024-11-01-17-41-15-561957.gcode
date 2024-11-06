; AutoPipette Settings loaded from autopipette.conf
; NAME
;	 name_pipette_servo: my_servo
;	 name_pipette_stepper: lock_stepper
; BOUNDARY
;	 safe_altitude: 35
; SPEED
;	 speed_xy: 10000
;	 speed_z: 5000
;	 speed_pipette: 45
;	 speed_max: 99999
;	 speed_factor: 100
;	 velocity_max: 40000
;	 accel_max: 40000
; SERVO
;	 servo_angle_retract: 150
;	 servo_angle_ready: 80
; WAIT
;	 wait_time_eject: 1000
;	 wait_time_movement: 250
;	 wait_time_aspirate: 250
; VOLUME_CONV
;	 volumes: 19, 47, 77, 103
;	 steps: 11.94, 21.54, 31.09, 40.6
; COORDINATE plate0
;	 x: 309
;	 y: 5
;	 z: 35
;	 type: wellplate
; COORDINATE plate1
;	 x: 198
;	 y: 0
;	 z: 35
;	 type: vialholder
;	 col: 5
;	 row: 7
; COORDINATE plate2
;	 x: 86
;	 y: 0
;	 z: 35
;	 type: vialholder
;	 col: 5
;	 row: 6
; COORDINATE plate3
;	 x: 307
;	 y: 150
;	 z: 35
;	 type: tipbox
; COORDINATE plate4
;	 x: 170
;	 y: 150
;	 z: 35
;	 type: garbage
; COORDINATE plate5
;	 x: 91
;	 y: 141
;	 z: 35
;	 type: vialholder
; COORDINATE dest_vial
;	 x: 58
;	 y: 107
;	 z: 35
;	 type: tiltv
M220 S100.0
SET_VELOCITY_LIMIT VELOCITY=40000.0
SET_VELOCITY_LIMIT ACCEL=40000.0
G28 Z
G28 X Y
SET_SERVO SERVO=my_servo ANGLE=150
G4 P250
MANUAL_STEPPER STEPPER=lock_stepper SPEED=45 MOVE=-50 STOP_ON_ENDSTOP=1
MANUAL_STEPPER STEPPER=lock_stepper SET_POSITION=0

