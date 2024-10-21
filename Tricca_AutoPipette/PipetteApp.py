"""
Pipette App script.

Launch and manage the application.

Run from command line by running
>>> python3 PipetteApp.py ip
Or:
>>> python3 PipetteApp.py ip --gcode GCODE_FILE_PATH
"""
from Coordinate import Coordinate
import asyncio
from shiny import App, render, ui, reactive
from AutoPipette import AutoPipette
from pathlib import Path
import argparse
import requests
import random


GCODE_PATH = Path(__file__).parent.parent / 'gcode/'
# pipette = AutoPipette()
moonraker_url = "http://0.0.0.0:7125/printer/gcode/script"


def run_gcode(filename: str):
    """Open a gcode file and execute it."""
    file = GCODE_PATH / filename
    if (not file.exists()):
        print(f"File {filename} does not exist.")
    with file.open() as fileobj:
        for line in fileobj:
            print(line)
            send_gcode(line)


def send_gcode(command):
    """Send gcode to the pipette."""
    response = requests.post(moonraker_url, json={"script": command})
    if response.status_code == 200:
        print("Command sent successfully")
    else:
        print(f"Failed to send command: \
           {response.status_code}, {response.text}")


def server(input, output, session):
    """Define what the website looks like."""
    status_text = reactive.Value("Ready for commands")

    curr_x = reactive.Value(-1)
    curr_y = reactive.Value(-1)
    curr_z = reactive.Value(-1)
    curr_e = reactive.Value(-1)

    # @output
    @render.ui
    def coordinate_display():
        return ui.tags.div(
            ui.input_numeric("curr_x", "X Coordinate:", value=curr_x()),
            ui.input_numeric("curr_y", "Y Coordinate:", value=curr_y()),
            ui.input_numeric("curr_z", "Z Coordinate:", value=curr_z()),
            ui.input_numeric("curr_e", "E Coordinate:", value=curr_e()),
            class_="current_coordinates_row"
        )

    @reactive.effect
    def _():
        reactive.invalidate_later(1)
        coortinates = {
            'X': random.randint(1, 100),
            'Y': random.randint(1, 100),
            'Z': random.randint(1, 100),
            'E': random.randint(1, 100),
        }

        print(coortinates['X'], coortinates['Y'], coortinates['Z'], coortinates['E'])

        # Simulate fetching new coordinates (replace this with your actual update logic)
        curr_x.set(coortinates['X'])  # Update X coordinate
        curr_y.set(coortinates['Y'])  # Update Y coordinate
        curr_z.set(coortinates['Z'])  # Update Z coordinate
        curr_e.set(coortinates['E'])  # Update E coordinate

            # await asyncio.sleep(2)  # Wait for 1 second

    # asyncio.create_task(update_coordinates())

    @output
    @render.text
    def output():
        return status_text()

    @reactive.Effect
    @reactive.event(input.move)
    def move_handler():
        x = input.x()
        y = input.y()
        z = input.z()
        speed = input.speed()
        coordinate = Coordinate(x, y, z, speed)
        pipette.move_to(coordinate)
        command = f"Move to coordinates: X={x}, Y={y}, Z={z}, Speed={speed}"
        status_text.set(command)

    @render.ui
    @reactive.Effect
    @reactive.event(input.home)
    async def home_handler():
        with ui.Progress(min=1, max=15) as p:
            p.set(message="Calculation in progress",
                  detail="This may take a while...")
            for i in range(1, 15):
                p.set(i, message="Computing")
                if (i == 12):
                    run_gcode("home.gcode")
                    command = "Moved to home coordinates..."
                    status_text.set(command)
                await asyncio.sleep(0.1)
            return "Done computing!"

    @render.ui
    @reactive.Effect
    @reactive.event(input.kit)
    async def kit_handler():
        with ui.Progress(min=1, max=15) as p:
            p.set(message="Executing Protocol",
                  detail="This may take a while...")
            command = "Kit Manufacturing Initiated"
            status_text.set(command)
            for i in range(1, 15):
                p.set(i, message="Executing Protocol")
                if (i == 12):
                    run_gcode("kit_prep.gcode")
                    command = "Kit Manufacturing Finished"
                    status_text.set(command)
                await asyncio.sleep(0.1)
        return "Done!"

    @reactive.Effect
    @reactive.event(input.sample)
    def sample_handler():
        command = "Sample Prep initiated..."
        status_text.set(command)

    @reactive.Effect
    @reactive.event(input.stop)
    def stop_handler():
        exit()

    @reactive.Effect
    @reactive.event(input.move_to_location)
    def move_to_location_handler():
        location_name = input.location_name()
        # Grab the named location and default to home if nothing comes up.
        coordinate = pipette.get_location_coor(location_name)
        speed = input.speed()  # Use the speed specified in the input
        pipette.move_to(coordinate, speed)
        command = \
            f"Moving to location: {location_name} with Speed: {speed}"
        status_text.set(command)

    @reactive.Effect
    @reactive.event(input.traverse_wells)
    def traverse_wells_handler():
        pass

    @reactive.Effect
    @reactive.event(input.initPipette)
    def initPipette():
        pipette.init_all()
        command = "Machine ready to start!"
        status_text.set(command)


def run_pipette_app():
    """Generate and execute the AutoPipette app."""
    app_ui = ui.page_fluid(
        ui.tags.head(
            ui.include_css(
                Path(__file__).parent / "my-styles.css"
            )
        ),

        ui.tags.div(
            ui.tags.div(
                ui.tags.i(class_="fas fa-vial"),
                "AutoPipette Machine Control Panel",
                class_="header"),
            class_="d-flex flex-column mb-3"
        ),
        
        ui.tags.div(
            ui.tags.div(
                # CURRENT COORDINATES
                ui.output_ui("coordinate_display"),  # This will render the coordinates
                # ui.tags.div(
                #     ui.input_numeric("curr_x", "X Coordinate:", value=curr_x()),
                #     ui.input_numeric("curr_x", "Y Coordinate:", value=curr_y()),
                #     ui.input_numeric("curr_x", "Z Coordinate:", value=curr_x()),
                #     ui.input_numeric("curr_x", "E Coordinate:", value=curr_e()),
                #     class_="current_coordinates_row"
                # ),

                # COORDINATES INPUTS
                ui.tags.div(
                    ui.input_numeric("x", "X Coordinate:", value=0),
                    ui.input_numeric("y", "Y Coordinate:", value=0),
                    ui.input_numeric("z", "Z Coordinate:", value=0),
                    ui.input_numeric(
                        "speed", "Speed (mm/min):", value=1500),
                    ui.input_action_button("move", ui.tags.span(
                        ui.tags.i(
                            class_="fas fa-arrows-alt"),
                        "Move to Coordinate"), class_="btn"),
                    ui.input_action_button(
                        "home", ui.tags.span(
                            ui.tags.i(class_="fas fa-home"), "Move Home"),
                        class_="btn"),
                    ui.input_action_button("stop", ui.tags.span(ui.tags.i(
                        class_="fas fa-stop"), " Stop"), class_="btn"),
                    ui.input_text("location_name", "Location Name:",
                                    value=""),
                    ui.input_action_button("move_to_location", ui.tags.span(
                        ui.tags.i(class_="fas fa-map-marker-alt"),
                        " Move to Location"), class_="btn"),
                    class_="sidebar"
                ),
                
                # PROTOCOLS
                ui.tags.div(
                    ui.tags.h2("Protocols", class_="protocol-title"),
                    ui.input_action_button(
                        "initPipette",
                        ui.tags.span(ui.tags.i(class_="fas fa-home"),
                                        "Initialize Pipette"), class_="btn"),
                    
                    ui.input_action_button(
                        "kit",
                        ui.tags.span(ui.tags.i(class_="fas fa-cogs"),
                                        "Kit Manufacturing"), class_="btn"),
                    
                    ui.input_action_button("sample",
                                            ui.tags.span(
                                                ui.tags.i(
                                                    class_="fas fa-flask"),
                                                " Sample Prep"),
                                            class_="btn"),

                    # Live video stream section
                    ui.tags.div(
                        ui.tags.h4("Live Video Stream"),
                        ui.tags.video(
                            controls=True,
                            autoplay=True,
                            # Replace with the URL of a camera
                            src="https://commondatastorage.googleaample/BigBuckBunny.mp4",
                            style="width: 50%; max-width: 50%; border-radius: 8px;"
                            ),
                        class_="card"  # Styling for the video container
                        ),
                    class_="right-section"
                ),

                # Ensure content grows to fill available space
                class_="d-flex flex-column flex-grow-1"
            ),

            ui.tags.div(
                ui.card(
                    ui.tags.h2("Output"),
                    ui.output_text_verbatim("output"),
                    class_="card"
                    ),
                class_="ml-3 main-content"
            ),
            class_="d-flex flex-row"
        )
    )

    app = App(app_ui, server)
    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    # Setup parser and get arguments
    parser = argparse.ArgumentParser(
        description="Start a webpage for controlling the auto-pipette.")
    parser.add_argument("ip", help="The ip address of the auto-pipette.")
    parser.add_argument('gcode', type=str, nargs='?',
                        help="The gcode file to run on startup.")
    args = parser.parse_args()
    # Launch program
    # pipette = AutoPipette()
    moonraker_url = \
        "http://" + args.ip + ":7125/printer/gcode/script"
    if args.gcode is not None:
        run_gcode(args.gcode)
    else:
        run_pipette_app()
