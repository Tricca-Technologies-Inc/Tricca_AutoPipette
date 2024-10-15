; Set the speed of the pipette toolhead
; SPEED_FACTOR changed from 100 to 100
M220 S100
; MAX_VELOCITY changed from 4000 to 99999
SET_VELOCITY_LIMIT VELOCITY=99999
; MAX_ACCEL changed from 4000 to 99999
SET_VELOCITY_LIMIT ACCEL=99999
; DEFAULT_SPEED_XY changed from 500 to 5000
; DEFAULT_SPEED_Z changed from 500 to 12000

; Setup the plates below the pipette
; Location:plate0 set to x:309 y:0 z:40
; Location:plate1 set to x:202 y:0 z:40
; Location:plate2 set to x:90 y:0 z:40
; Location:plate3 set to x:310 y:144 z:40
; Location:plate4 set to x:170 y:196 z:40
; Location:plate5 set to x:91 y:141 z:40
; Location:plate0 set to Plate:wellplate
; Location:plate1 with rows:5 cols:7 set to Plate:vialholder
; Location:plate2 with rows:5 cols:6 set to Plate:vialholder
; Location:plate3 set to Plate:tipbox
; Location:plate4 set to Plate:garbage
; Location:plate5 set to Plate:vialholder

; Define destination coordinate
; Location:dest_vial set to x:65 y:104 z:40
; Location:dest_vial set to Plate:tiltv

; Home the pipette
G28 Z
G28 X Y
SET_SERVO SERVO=my_servo ANGLE=150
G4 P250
MANUAL_STEPPER STEPPER=lock_stepper SPEED=45 MOVE=-30 STOP_ON_ENDSTOP=1
MANUAL_STEPPER STEPPER=lock_stepper SET_POSITION=0
; Test X
G1 X0 Y150 Z40 F5000
G1 X300 Y150 Z40 F5000
G1 X0 Y150 Z40 F5000
; DEFAULT_SPEED_XY changed from 5000 to 5500
G1 X0 Y150 Z40 F5500
G1 X300 Y150 Z40 F5500
G1 X0 Y150 Z40 F5500
; DEFAULT_SPEED_XY changed from 5500 to 10000
G1 X0 Y150 Z40 F10000
G1 X300 Y150 Z40 F10000
G1 X0 Y150 Z40 F10000
; DEFAULT_SPEED_XY changed from 10000 to 6500
G1 X0 Y150 Z40 F6500
G1 X300 Y150 Z40 F6500
G1 X0 Y150 Z40 F6500
; DEFAULT_SPEED_XY changed from 6500 to 7000
G1 X0 Y150 Z40 F7000
G1 X300 Y150 Z40 F7000
G1 X0 Y150 Z40 F7000
; DEFAULT_SPEED_XY changed from 7000 to 5000
; Test Y
G1 X150 Y0 Z40 F5000
G1 X150 Y300 Z40 F5000
G1 X150 Y0 Z40 F5000
; DEFAULT_SPEED_XY changed from 5000 to 5500
G1 X150 Y0 Z40 F5500
G1 X150 Y300 Z40 F5500
G1 X150 Y0 Z40 F5500
; DEFAULT_SPEED_XY changed from 5500 to 6000
G1 X150 Y0 Z40 F6000
G1 X150 Y300 Z40 F6000
G1 X150 Y0 Z40 F6000
; DEFAULT_SPEED_XY changed from 6000 to 6500
G1 X150 Y0 Z40 F6500
G1 X150 Y300 Z40 F6500
G1 X150 Y0 Z40 F6500
; DEFAULT_SPEED_XY changed from 6500 to 7000
G1 X150 Y0 Z40 F7000
G1 X150 Y300 Z40 F7000
G1 X150 Y0 Z40 F7000
; DEFAULT_SPEED_XY changed from 7000 to 5000
