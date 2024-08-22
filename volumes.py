class volume:
    def __init__(self, prep, dispense, aspirate):  # Default speed if not provided
        self.prep = prep
        self.dispense = dispense
        self.aspirate = aspirate

v100 = volume(39, 46, 0)
v50 = volume(22, 46, 0)
v25 = volume(14.8, 46, 0)
v40 = volume(19, 46, 0)
