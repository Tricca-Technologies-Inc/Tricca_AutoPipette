from Coordinate import Coordinate
from Coordinate import Location
import asyncio
from shiny import App, render, ui, reactive
from AutoPipette import *
from protocols import *
from pathlib import Path
import argparse


class PipetteApp:

    pipette = AutoPipette("0.0.0.0")

    def move_to_coordinate(x, y, z, speed):
        coordinate = Coordinate(x, y, z, speed)
        print(f"Moving to coordinates: X={x}, Y={y}, Z={z}, Speed={speed}")  # Debug print
        pipette.move_to(coordinate)

    def server(input, output, session):
        status_text = reactive.Value("Ready for commands")

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
            PipetteApp.move_to_coordinate(x, y, z, speed)
            command = f"Move to coordinates: X={x}, Y={y}, Z={z}, Speed={speed}"
            status_text.set(command)

        @render.ui
        @reactive.Effect
        @reactive.event(input.home)
        async def home_handler():
            with ui.Progress(min=1, max=15) as p:
                p.set(message="Calculation in progress", detail="This may take a while...")

                for i in range(1, 15):
                    p.set(i, message="Computing")
                    if (i == 12):
                        PipetteApp.move_to_coordinate(0,0,0,1500)
                        command = "Moved to home coordinates..."
                        status_text.set(command)
                    await asyncio.sleep(0.1)

            return "Done computing!"

        @render.ui
        @reactive.Effect
        @reactive.event(input.kit)
        async def kit_handler():
            with ui.Progress(min=1, max=15) as p:
                p.set(message="Executing Protocol", detail="This may take a while...")
                command = "Kit Manufacturing Initiated"
                status_text.set(command)
                for i in range(1, 15):
                    p.set(i, message="Executing Protocol")
                    if (i == 12):
                        kitTest(
                            pipette.source_vial,
                            pipette.dest_vial,
                            pipette,
                            pipette.tip_box,
                            Location.well_s5,
                            volumes_PRIME
                            )
                        command = "Kit Manufacturing Finished"
                        status_text.set(command)
                    await asyncio.sleep(0.1)
            return "Done!"

        @reactive.Effect
        @reactive.event(input.sample)
        def sample_handler():
            volumeTest(Location.vial1, pipette.dest_vial, pipette)
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
            coordinate = Location.locations.get(location_name, Location.home)
            speed = input.speed()  # Use the speed specified in the input
            print(f"Moving to location: {location_name}, Coordinate: {coordinate}, Speed: {speed}")  # Debug print
            PipetteApp.move_to_coordinate(coordinate.x, coordinate.y, coordinate.z, speed)
            command = f"Moving to location: {location_name} with Speed: {speed}"
            status_text.set(command)

        @reactive.Effect
        @reactive.event(input.traverse_wells)
        def traverse_wells_handler():
            kitTest(pipette.source_vial, pipette.dest_vial, pipette, Location.tip_box, Location.well_s5)

        @reactive.Effect
        @reactive.event(input.initPipette)
        def initPipette():
            pipette.initAll()
            command = "Machine ready to start!"
            status_text.set(command)

    def run_pipette_app():
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
                    class_="header"
                   ),
                class_="d-flex flex-column mb-3"  # Ensure header is separate and add margin-bottom
               ),
            ui.tags.div(
                ui.tags.div(
                    ui.tags.div(
                        ui.input_numeric("x", "X Coordinate:", value=0),
                        ui.input_numeric("y", "Y Coordinate:", value=0),
                        ui.input_numeric("z", "Z Coordinate:", value=0),
                        ui.input_numeric("speed", "Speed (mm/min):", value=1500),
                        ui.input_action_button("move", ui.tags.span(ui.tags.i(class_="fas fa-arrows-alt"), " Move to Coordinates"), class_="btn"),
                        ui.input_action_button("home", ui.tags.span(ui.tags.i(class_="fas fa-home"), " Move to Home"), class_="btn"),
                        ui.input_action_button("stop", ui.tags.span(ui.tags.i(class_="fas fa-stop"), " Stop"), class_="btn"),
                        ui.input_text("location_name", "Location Name:", value=""),
                        ui.input_action_button("move_to_location", ui.tags.span(ui.tags.i(class_="fas fa-map-marker-alt"), " Move to Location"), class_="btn"),
                        class_="sidebar"
                       ),
                    ui.tags.div(
                        ui.tags.h2("Protocols", class_="protocol-title"),
                        ui.input_action_button("initPipette", ui.tags.span(ui.tags.i(class_="fas fa-home"), "Initialize Pipette"), class_="btn"),
                        ui.input_action_button("kit", ui.tags.span(ui.tags.i(class_="fas fa-cogs"), " Kit Manufacturing"), class_="btn"),
                        ui.input_action_button("sample", ui.tags.span(ui.tags.i(class_="fas fa-flask"), " Sample Prep"), class_="btn"),

                        # Live video stream section
                        ui.tags.div(
                            ui.tags.h4("Live Video Stream"),
                            ui.tags.video(
                                controls=True,
                                autoplay=True,
                                src="https://commondatastorage.googleaample/BigBuckBunny.mp4",  # Replace with the URL of a camera
                                style="width: 50%; max-width: 50%; border-radius: 8px;"
                               ),
                            class_="card"  # Styling for the video container
                           ),
                        class_="right-section"
                       ),
                    class_="d-flex flex-column flex-grow-1"  # Ensure content grows to fill available space
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
        app = App(app_ui, PipetteApp.server)
        app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start a webpage for controlling the auto-pipette.")
    parser.add_argument("ip", help="the ip address of the auto-pipette")
    args = parser.parse_args()
    pipette = AutoPipette(args.ip)
    PipetteApp.pipette = pipette
    PipetteApp.run_pipette_app()
