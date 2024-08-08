# Automated Pipetting System

This repository contains the codebase for an automated pipetting system designed to manage liquid handling tasks such as aspirating, dispensing, and ejecting tips using a robotic arm controlled by a pipette. The system is programmed using Python and interfaces with hardware through G-code commands and configuration files.

## Table of Contents

- [Overview](#overview)
- [Files and Structure](#files-and-structure)
- [Usage](#usage)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Contributing](#contributing)
- [License](#license)

## Overview

The automated pipetting system is designed for solution handling tasks, utilizing stepper motors and servos for accurate movement. This project includes functionality for controlling the pipette, moving to specific well coordinates, and executing complex liquid handling protocols.

## Files and Structure

- **app.py**  
  The main application entry point. Manages the overall flow of pipetting tasks.

- **coordinates.py**  
  Defines the coordinate system and functions for generating well plate coordinates.

- **main.py**  
  A script that initializes and runs the pipetting routines. (Currently not in use. Run app.py)

- **movement.py**  
  Contains functions for moving the machine to specific coordinates.

- **pipette.py**  
  Defines the pipette control functions and protocols, including aspirate, dispense, and tip ejection operations.

- **pipettev2.py**  
  An alternative or updated version of the `pipette.py` module with additional or modified functionality.

- **printer.cfg**  
  The configuration file for Klipper firmware, defining the hardware setup and motor configurations.

- **volumes.py**  
  Contains definitions for solution volumes used in pipetting protocols.

Configuration
printer.cfg
This file contains the configuration for the Klipper firmware, including stepper motors, endstops, and other hardware parameters. Modify this file according to  specific hardware configuration.

volumes.py
The volumes.py file contains predefined liquid volumes used for various pipetting tasks. You can customize these volumes to suit  particular requirements.

Dependencies
Ensure that Python 3.x is installed on your system. You will also need to install the necessary Python packages. You can do this by running:
