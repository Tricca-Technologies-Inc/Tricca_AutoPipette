class volume:
    def __init__(self, prep, dispense, aspirate, multiplier):  # Default speed if not provided
        self.prep = prep
        self.dispense = dispense
        self.aspirate = aspirate
        self.multiplier = multiplier

v100 = volume(39.25, 46, 0, 1)
v50 = volume(22.45, 46, 0, 1)
v25 = volume(14.35, 46, 0, 1)
v40 = volume(19.2, 46, 0, 1)
v400 = volume(39, 46, 0, 4)
v200 = volume(39,46, 0 , 2)
v250 = volume(22, 46, 0, 5)
v160 = volume(19, 46, 0, 4)


volume_mapping = {
    100: v100,
    50: v50,
    25: v25,
    40: v40
}