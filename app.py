from shiny import App, render, ui, reactive
import movement
import coordinates
from coordinates import *
from pipettev2 import *
import asyncio

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
            }
            .header {
                background-color: #0288d1;
                color: white;
                padding: 60px;
                text-align: center;
                border-radius: 8px;
                margin-bottom: 20px;
                font-size: 40px;
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
            }
            .card {
                background-color: #fff;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 8px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
        """)
    ),
    ui.tags.div(
        ui.tags.div(
            ui.tags.i(class_="fas fa-vial"),
            "AutoPipette Machine Control Panel",
            class_="header"
        ),
        ui.tags.div(
            ui.tags.div(
                ui.input_numeric("x", "X Coordinate:", value=0),
                ui.input_numeric("y", "Y Coordinate:", value=0),
                ui.input_numeric("z", "Z Coordinate:", value=0),
                ui.input_numeric("speed", "Speed (mm/min):", value=1500),
                ui.input_action_button("move", ui.tags.span(ui.tags.i(class_="fas fa-arrows-alt"), " Move to Coordinates"), class_="btn"),
                ui.input_action_button("homeX", ui.tags.span(ui.tags.i(class_="fas fa-home"), " Home X"), class_="btn"),
                ui.input_action_button("home", ui.tags.span(ui.tags.i(class_="fas fa-home"), " Move to Home"), class_="btn"),
                ui.input_action_button("kit", ui.tags.span(ui.tags.i(class_="fas fa-cogs"), " Kit Manufacturing"), class_="btn"),
                ui.input_action_button("sample", ui.tags.span(ui.tags.i(class_="fas fa-flask"), " Sample Prep"), class_="btn"),
                ui.input_action_button("stop", ui.tags.span(ui.tags.i(class_="fas fa-stop"), " Stop"), class_="btn"),
                ui.input_text("location_name", "Location Name:", value="Home"),
                ui.input_action_button("traverse_wells", ui.tags.span(ui.tags.i(class_="fas fa-th"), " Traverse Wells"), class_="btn"),
                ui.input_action_button("move_to_location", ui.tags.span(ui.tags.i(class_="fas fa-map-marker-alt"), " Move to Location"), class_="btn"),
                class_="sidebar"
            ),
            ui.tags.div(
                ui.card(
                    ui.tags.h2("Output"),
                    ui.output_text_verbatim("output"),
                    class_="card"
                ),
                class_="ml-3"  # Add margin to separate from sidebar
            ),
            class_="d-flex flex-column justify-content-start"  # Align items in a column
        )
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
    @reactive.event(input.homeX)
    async def homeX_handler():
        with ui.Progress(min=1, max=15) as p:
            p.set(message="Calculation in progress", detail="This may take a while...")

            for i in range(1, 15):
                p.set(i, message="Computing")
                if (i == 12):
                    movement.homeX()
                    command = "Homed X axis..."
                    status_text.set(command)
                await asyncio.sleep(0.1)

        return "Done computing!"

    @reactive.Effect
    @reactive.event(input.home)
    def home_handler():
        movement.move_to(home)
        command = "Moving to home coordinates..."
        status_text.set(command)

    @reactive.Effect
    @reactive.event(input.kit)
    def kit_handler():
        movement.kit_manufacturing()
        command = "Kit Manufacturing initiated..."
        status_text.set(command)

    @reactive.Effect
    @reactive.event(input.sample)
    def sample_handler():
        movement.sample_prep()
        command = "Sample Prep initiated..."
        status_text.set(command)

    @reactive.Effect
    @reactive.event(input.stop)
    def stop_handler():
        movement.stop_operations()
        command = "Stopping all operations..."
        status_text.set(command)

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
        sample_test(vial2, dest_plate, pipette)

app = App(app_ui, server)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)