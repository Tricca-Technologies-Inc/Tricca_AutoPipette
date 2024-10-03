; Set the speed of the pipette toolhead
; Autopipette SPEED_FACTOR changed from 100 to 100
M220 S100
; Autopipette MAX_VELOCITY changed from 99999 to 99999
SET_VELOCITY_LIMIT VELOCITY=99999
; Autopipette MAX_ACCEL changed from 99999 to 99999
SET_VELOCITY_LIMIT ACCEL=99999
; AutoPipette DEFAULT_SPEED_XY changed from 500 to 500
; AutoPipette DEFAULT_SPEED_Z changed from 500 to 500

; Setup the plates below the pipette
coor
coor
coor
coor
coor
coor
coor
coor

; Define destination coordinate
coor

; Home the pipette
G28 Z
G28 X Y
SET_SERVO SERVO=my_servo ANGLE=150
G4 P250
MANUAL_STEPPER STEPPER=lock_stepper SPEED=15 MOVE=-30 STOP_ON_ENDSTOP=1
MANUAL_STEPPER STEPPER=lock_stepper SET_POSITION=0

; Execute kit prep protocol
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
pipette
