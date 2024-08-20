import movement
import coordinates
import asyncio
from shiny import App, render, ui, reactive
from coordinates import *
from pipettev2 import *
from protocols import *

# Create a Coordinate object named 'home' with coordinates (0, 0, 0)
home = coordinates.Coordinate(0, 0, 0)

def move_to_coordinates(x, y, z, speed):
    coordinate = coordinates.Coordinate(x, y, z, speed)
    print(f"Moving to coordinates: X={x}, Y={y}, Z={z}, Speed={speed}")  # Debug print
    movement.move_to(coordinate)

def get_coordinates_from_name(name):
    # Map names to coordinates
    locations = {
        "Tip S3": tip_s3,
        "Tip S6": tip_s6,
        "Test V": testv,
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
    coordinate = locations.get(name, home)  # Default to home if location is not found
    print(f"get_coordinates_from_name('{name}') = {coordinate}")  # Debug print
    return coordinate

app_ui = ui.page_fluid(
    ui.tags.head(
        ui.tags.style("""
            @import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css');
            body {
                background-color: #e0f7fa;
                font-family: Arial, sans-serif;
                color: #333;
                margin: 0;  /* Remove default margin */
                padding: 0;  /* Remove default padding */
            }
            .header {
                background-color: #0288d1;
                color: white;
                padding: 20px;  /* Reduce padding for a smaller header */
                text-align: center;
                border-radius: 8px;
                margin-bottom: 10px;  /* Space below the header */
                font-size: 24px;  /* Decrease font size */
                width: 100%;  /* Make sure header spans full width */
            }
            .header i {
                margin-right: 10px;
            }
            .btn {
                background-color: #0288d1;
                border: none;
                color: white;
                padding: 10px 24px;
                text-align: center;
                text-decoration: none;
                display: inline-block;
                font-size: 16px;
                margin: 4px 2px;
                cursor: pointer;
                border-radius: 8px;
            }
            .btn:hover {
                background-color: #0277bd;
            }
            .btn i {
                margin-right: 8px;
            }
            .sidebar {
                background-color: #b3e5fc;
                padding: 15px;
                border-radius: 8px;
                min-width: 250px;  /* Set a minimum width for the sidebar */
            }
            .card {
                background-color: #fff;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 8px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
            .d-flex {
                display: flex;
                flex-wrap: wrap;  /* Allow wrapping to fit content */
            }
            .flex-column {
                flex-direction: column;
            }
            .justify-content-start {
                justify-content: flex-start;
            }
            .ml-3 {
                margin-left: 1rem;
            }
            .right-section {
                background-color: #e1f5fe;
                padding: 15px;
                border-radius: 8px;
                min-width: 200px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                flex-grow: 1;  /* Allow right section to grow */
                margin-left: 20px;  /* Add some space between the content and right section */
            }
            .main-content {
                flex: 1;  /* Let the main content take available space */
            }
            .protocol-title {
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 10px;
                text-align: center;
                color: #0288d1;
            }
        """)
    ),
    ui.tags.div(
        ui.tags.div(
            ui.tags.i(class_="fas fa-vial"),
            "AutoPipette Machine Control Panel",
            class_="header"
        ),
        class_="d-flex flex-column"  # Ensure header is separate
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
                class_="right-section"
            ),
            class_="d-flex"
        ),

        ui.tags.div(
            ui.card(
                ui.tags.h2("Output"),
                ui.output_text_verbatim("output"),
                class_="card"
            ),
            class_="ml-3 main-content"
        ),
        class_="d-flex justify-content-start"
    )
)


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
        move_to_coordinates(x, y, z, speed)
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
                    movement.move_to(home)
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
                    kitTest(source_vial, dest_vial, pipette, tip_box, well_s5)
                    command = "Kit Manufacturing Finished"
                    status_text.set(command)
                await asyncio.sleep(0.1)

        return "Done!"

    @reactive.Effect
    @reactive.event(input.sample)
    def sample_handler():
        movement.sample_prep()
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
        coordinate = get_coordinates_from_name(location_name)
        speed = input.speed()  # Use the speed specified in the input
        print(f"Moving to location: {location_name}, Coordinate: {coordinate}, Speed: {speed}")  # Debug print
        move_to_coordinates(coordinate.x, coordinate.y, coordinate.z, speed)
        command = f"Moving to location: {location_name} with Speed: {speed}"
        status_text.set(command)

    @reactive.Effect
    @reactive.event(input.traverse_wells)
    def traverse_wells_handler():
        kitTest(source_vial, dest_vial, pipette, tip_box, well_s5)
        # tip_test(source_plate, dest_tips, pipette)

    @reactive.Effect
    @reactive.event(input.initPipette)
    def initPipette():
        pipette.initAll()
        command = "Machine ready to start!"
        status_text.set(command)

app = App(app_ui, server)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)