class Coordinate:

    def __init__(self, x, y, z, speed=1500):  # Default speed if not provided
        self.x = x
        self.y = y
        self.z = z
        self.speed = speed

    def __repr__(self):
        return f"Coordinate(x={self.x}, y={self.y}, z={self.z}, speed={self.speed})"


class Location:

    # Home
    home = Coordinate(0, 0, 0)

    # 100uL Tips Origin points
    tip_s3 = Coordinate(x=263, y=345, z=40.0)
    tip_s4 = Coordinate(x=313.5, y=151, z=40.0)
    tip_s6 = Coordinate(x=89.6, y=150.50, z=40.0)
    testv = Coordinate(x=260.24, y=56.15, z=40)
    well_end = Coordinate(x=300, y=294, z=40)

    # Well Origin points
    well_s5 = Coordinate(x=202, y=148.50, z=40)

    # Change vial location manually
    scale_vial = Coordinate(x=141.9, y=229.4, z=60) # need to update

    # Vial Origin points
    vial1 = Coordinate(x=94, y=147.50, z=40)
    vial2 = Coordinate(x=205, y=4, z=40)
    vial3 = Coordinate(x=94, y=0, z=40)

    mvial = Coordinate(x=33.5, y=243.03, z=60)

    # Garbage positions
    garb_s5 = Coordinate(x=179.82, y=136.21, z=60.0)
    tiltV = Coordinate(x=170, y=246.61, z=60)

    # Map names to coordinates
    locations = {
        "Home": home,
        "Tip S3": tip_s3,
        "Tip S6": tip_s6,
        "Test V": testv,
        "Well End": well_end,
        "Well S5": well_s5,
        "Scale Vial": scale_vial,
        "Vial 1": vial1,
        "Vial 2": vial2,
        "Vial 3": vial3,
        "MVial": mvial,
        "Garbage S5": garb_s5,
        "Tilt V": tiltV,
        # Add more locations if needed
       }
