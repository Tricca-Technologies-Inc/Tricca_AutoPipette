from shiny import App, render, ui, reactive
import movement

# Create a Coordinate object named 'home' with coordinates (0, 0, 0)
home = movement.Coordinate(0, 0, 0, 6000)

def move_to_coordinates(x, y, z, speed):
    coordinate = movement.Coordinate(x, y, z, speed)
    movement.move_to(coordinate)

app_ui = ui.page_fluid(
    ui.panel_title("Robot Control Panel"),
    ui.layout_sidebar(
        ui.panel_sidebar(
            ui.input_numeric("x", "X Coordinate:", value=0),
            ui.input_numeric("y", "Y Coordinate:", value=0),
            ui.input_numeric("z", "Z Coordinate:", value=0),
            ui.input_numeric("speed", "Speed (mm/min):", value=1500),
            ui.input_action_button("move", "Move to Coordinates"),
            ui.input_action_button("homeX", "Home X"),
            ui.input_action_button("home", "Move to Home"),
            ui.input_action_button("kit", "Kit Manufacturing"),
            ui.input_action_button("sample", "Sample Prep"),
            ui.input_action_button("stop", "Stop"),
        ),
        ui.panel_main(
            ui.output_text_verbatim("output")
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
        status_text.set(f"Moving to coordinates: X={x}, Y={y}, Z={z}, Speed={speed}")

    @reactive.Effect
    @reactive.event(input.homeX)
    def homeX_handler():
        movement.homeX()
        status_text.set("Homing X axis...")

    @reactive.Effect
    @reactive.event(input.home)
    def home_handler():
        movement.move_to(home)
        status_text.set("Moving to home coordinates...")

    @reactive.Effect
    @reactive.event(input.kit)
    def kit_handler():
        movement.kit_manufacturing()
        status_text.set("Kit Manufacturing initiated...")

    @reactive.Effect
    @reactive.event(input.sample)
    def sample_handler():
        movement.sample_prep()
        status_text.set("Sample Prep initiated")

    @reactive.Effect
    @reactive.event(input.stop)
    def stop_handler():
        movement.stop_operations()
        status_text.set("Stopping all operations")

app = App(app_ui, server)

if __name__ == "__main__":
    app.run()