; AutoPipette Settings loaded from autopipette.conf
; NAME
;	 name_pipette_servo: my_servo
;	 name_pipette_stepper: lock_stepper
; BOUNDARY
;	 safe_altitude: 40
; SPEED
;	 speed_xy: 5000
;	 speed_z: 5000
;	 speed_pipette: 45
;	 speed_max: 99999
;	 speed_factor: 100
;	 velocity_max: 4000
;	 accel_max: 4000
; SERVO
;	 servo_angle_retract: 150
;	 servo_angle_ready: 80
; WAIT
;	 wait_time_eject: 1000
;	 wait_time_movement: 250
; COORDINATE plate0
;	 x: 309
;	 y: 0
;	 z: 40
;	 type: wellplate
; COORDINATE plate1
;	 x: 202
;	 y: 0
;	 z: 40
;	 type: vialholder
;	 col: 5
;	 row: 7
; COORDINATE plate2
;	 x: 90
;	 y: 0
;	 z: 40
;	 type: vialholder
;	 col: 5
;	 row: 6
; COORDINATE plate3
;	 x: 311
;	 y: 148
;	 z: 40
;	 type: tipbox
; COORDINATE plate4
;	 x: 170
;	 y: 196
;	 z: 40
;	 type: garbage
; COORDINATE plate5
;	 x: 91
;	 y: 141
;	 z: 40
;	 type: vialholder
; COORDINATE dest_vial
;	 x: 65
;	 y: 104
;	 z: 40
M220 S100.0
SET_VELOCITY_LIMIT VELOCITY=4000.0
SET_VELOCITY_LIMIT ACCEL=4000.0
G28 Z
G28 X Y
SET_SERVO SERVO=my_servo ANGLE=150
G4 P250
MANUAL_STEPPER STEPPER=lock_stepper SPEED=45 MOVE=-30 STOP_ON_ENDSTOP=1
MANUAL_STEPPER STEPPER=lock_stepper SET_POSITION=0
; Test X
; SPEED_XY changed from 5000 to 5000
G1 X0 Y150 Z40 F5000
G1 X300 Y150 Z40 F5000
G1 X0 Y150 Z40 F5000
; SPEED_XY changed from 5000 to 10000
G1 X0 Y150 Z40 F10000
G1 X300 Y150 Z40 F10000
G1 X0 Y150 Z40 F10000
; SPEED_XY changed from 10000 to 15000
G1 X0 Y150 Z40 F15000
G1 X300 Y150 Z40 F15000
G1 X0 Y150 Z40 F15000
; SPEED_XY changed from 15000 to 20000
G1 X0 Y150 Z40 F20000
G1 X300 Y150 Z40 F20000
G1 X0 Y150 Z40 F20000
; SPEED_XY changed from 20000 to 25000
G1 X0 Y150 Z40 F25000
G1 X300 Y150 Z40 F25000
G1 X0 Y150 Z40 F25000
; SPEED_XY changed from 25000 to 30000
G1 X0 Y150 Z40 F30000
G1 X300 Y150 Z40 F30000
G1 X0 Y150 Z40 F30000
; Test Y
; SPEED_XY changed from 30000 to 5000
G1 X150 Y0 Z40 F5000
G1 X150 Y300 Z40 F5000
G1 X150 Y0 Z40 F5000
; SPEED_XY changed from 5000 to 10000
G1 X150 Y0 Z40 F10000
G1 X150 Y300 Z40 F10000
G1 X150 Y0 Z40 F10000
; SPEED_XY changed from 10000 to 15000
G1 X150 Y0 Z40 F15000
G1 X150 Y300 Z40 F15000
G1 X150 Y0 Z40 F15000
; SPEED_XY changed from 15000 to 20000
G1 X150 Y0 Z40 F20000
G1 X150 Y300 Z40 F20000
G1 X150 Y0 Z40 F20000
; SPEED_XY changed from 20000 to 25000
G1 X150 Y0 Z40 F25000
G1 X150 Y300 Z40 F25000
G1 X150 Y0 Z40 F25000
; SPEED_XY changed from 25000 to 30000
G1 X150 Y0 Z40 F30000
G1 X150 Y300 Z40 F30000
G1 X150 Y0 Z40 F30000
