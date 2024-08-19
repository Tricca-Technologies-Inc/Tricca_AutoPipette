class volume:
    def __init__(self, prep, dispense, aspirate):  # Default speed if not provided
        self.prep = prep
        self.dispense = dispense
        self.aspirate = aspirate

v100 = volume(38, 46, 0)