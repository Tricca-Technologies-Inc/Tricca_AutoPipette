class Coordinate:
    def __init__(self, x, y, z, speed=1500):  # Default speed if not provided
        self.x = x
        self.y = y
        self.z = z
        self.speed = speed

    def __repr__(self):
        return f"Coordinate(x={self.x}, y={self.y}, z={self.z}, speed={self.speed})"

# 100uL Tips Origin points
tip_s3 = Coordinate(x=263, y=345, z=60.0)
tip_s4 = Coordinate(x=312, y=151.50, z=60.0)
tip_s6 = Coordinate(x=89, y=151.50, z=60.0)
testv = Coordinate(x=260.24, y=56.15, z=60)
well_end = Coordinate(x=300, y=294, z=60)

# Well Origin points
well_s5 = Coordinate(x=200, y=145.6, z=40)

# Change vial location manually
scale_vial = Coordinate(x=141.9, y=229.4, z=60)

# Vial Origin points
vial1 = Coordinate(x=33.29, y=338.72, z=60) # need to update
vial2 = Coordinate(x=205, y=3, z=40)
vial3 = Coordinate(x=93, y=5, z=40)

mvial = Coordinate(x=33.5, y=243.03, z=60)

# Garbage positions
garb_s5 = Coordinate(x=179.82, y=136.21, z=60.0)
tiltV = Coordinate(x=170, y=246.61, z=60)