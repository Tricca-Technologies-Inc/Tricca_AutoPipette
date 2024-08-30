# Automated Pipetting System

This repository contains the codebase for an automated pipetting system designed to manage protocols for kit manufacturing and sample preparation using a gantry system controlled by a pipette. The system is programmed using Python and interfaces with hardware through G-code commands and configuration files.

## Table of Contents

- [Overview](#overview)
- [Files and Structure](#files-and-structure)
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

- **movement.py**  
  Contains functions for moving the machine to specific coordinates.

- **pipettev2.py**  
  An alternative or updated version of the `pipette.py` module with additional or modified functionality.

- **printer.cfg**  
  The configuration file for Klipper firmware, defining the hardware setup and motor configurations.

- **volumes.py**  
  Contains definitions for solution volumes used in pipetting protocols.

## Configuration
printer.cfg
This file contains the configuration for the Klipper firmware, including stepper motors, endstops, and other hardware parameters. Modify this file according to  specific hardware configuration.

## Dependencies
Ensure that Python 3.x is installed on your system. You will also need to install the necessary Python packages. You can do this by running:

## How to run the machine
- **1.) Connecting to the board.**  
  On Code FAQ#9
  
- **2.) Setting up the software**  
  Git pull the repo to a folder. Use VS code

- **3.) Getting Started**  
  Change the IP addresses (from step 1) on the current code set. Run app.py and open the web app to run protocols

- **4.) Operation**  
  First, click 'initialize pipette' on the web app to home all motors and set the right speeds.
  Then, set the speed to 100% first before executing any protocols. Click 'kit manufacturing' to run the test. Once the protocol is ran, you can set the speed up to 800%. Finally, wait for the protocol to finish. Have Mainsail open for emergency stop, just in case the machine/program fails.

- **5.) Notes**  
  Calibrate the coordinates manually using mainsail before executing protocols to prevent any collisions/problems.
  
