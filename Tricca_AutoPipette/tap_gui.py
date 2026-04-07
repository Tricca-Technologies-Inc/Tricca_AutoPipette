import sys

from PyQt6.QtWidgets import QMainWindow, QPushButton, QVBoxLayout, QWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pipette Control")
        self.setMinimumSize(400, 300)

        self.button = QPushButton("Aspirate")
        self.button.clicked.connect(self.on_aspirate)

        layout = QVBoxLayout()
        layout.addWidget(self.button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def on_aspirate(self):
        pass  # wire to controller later
