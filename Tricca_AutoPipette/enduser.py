from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.responses import RedirectResponse, HTMLResponse
from starlette.requests import Request

import uvicorn
from shiny import App, ui, reactive


# FIRST PAGE UI AND SERVER FUNCTION
def first_page_ui(request: Request):
    return ui.page_fluid(
        ui.tags.div(
            ui.h2("Welcome to AutoPipette Controller"), 
            ui.tags.div(
                ui.tags.button("Go to Recipe Page", onclick="window.location.href='/second_page';", style="padding:10px; font-size:16px;"),
                style="display: flex; justify-content: center; align-items: center; height: 80vh;"  # Centering styles
            ),
            style="text-align: center;"  # Center-align all contents in this div
        )
    )

def first_page_server(input, output, session):
    pass  # No server-side functionality for the first page


# SECOND PAGE UI AND SERVER FUNCTION
def second_page_ui(request: Request):
    return ui.page_fluid(
        ui.tags.div(
            ui.h2("Please Select a Recipe!"), 
            ui.tags.div(
                ui.tags.button("Recipe A", onclick="window.location.href='/third_page?recipe=A';", 
                               style="padding:10px; font-size:16px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;"),
                ui.tags.button("Recipe B", onclick="window.location.href='/third_page?recipe=B';", 
                               style="padding:10px; font-size:16px; background-color: #2196F3; color: white; border: none; border-radius: 5px; cursor: pointer;"),
                ui.tags.button("Recipe C", onclick="window.location.href='/third_page?recipe=C';", 
                               style="padding:10px; font-size:16px; background-color: #FF5722; color: white; border: none; border-radius: 5px; cursor: pointer;"),
                style="display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 10px; height: 80vh;"  # Centering and stacking styles
            ),
            style="text-align: center;"  # Center-align all contents in this div
        )
    )

def second_page_server(input, output, session):
    pass  # No server-side functionality for the second page


# THIRD PAGE UI AND SERVER FUNCTION
def third_page_ui(request: Request):
    # Extract the 'recipe' query parameter from the URL
    recipe_name = request.query_params.get('recipe', 'Unknown Recipe')
    
    # Update the title based on the recipe selected
    title_text = f"Start Recipe {recipe_name} When Ready!"

    # Define the UI with a dynamic title and an action button
    return ui.page_fluid(
        ui.tags.div(
            ui.h2(title_text),  # Display dynamic title based on the recipe selected
            ui.p("Please follow these steps to set up your recipe before starting:"), 
            ui.img(src="/static/testtube.jpg", style="width: 300px; margin-top: 20px;"),
            ui.tags.ul(
                ui.tags.li("Step 1: Gather all necessary ingredients and tools."),
                ui.tags.li("Step 2: Pour 50ml methanol in the test tube marked A"),
                ui.tags.li("Step 3: Double-check that you have the correct recipe and measurements."),
                style="text-align: left; max-width: 500px; margin: 0 auto; font-size:14px;"
            ),
            ui.input_action_button("start_button", "Start", style="padding:10px; margin-top:100px; font-size:16px;"),  # Action button
            style="text-align: center; display: flex; flex-direction: column; align-items: center; height: 80vh;"  # Center-align all contents in this div
        )
    )

def third_page_server(input, output, session):
    # Define a reactive event that triggers when the "Start" button is clicked
    @reactive.Effect
    @reactive.event(input.start_button)
    def on_start_click():
        print("The Start button was clicked!")  # Print to the backend


# REATE SHINY APPS FOR EACH PAGE
first_page_app = App(first_page_ui, first_page_server)
second_page_app = App(second_page_ui, second_page_server)
third_page_app = App(third_page_ui, third_page_server)


# COMBINE ALL PAGES INTO A APP

# Redirect from root to /first_page
async def redirect_to_first_page(request):
    return RedirectResponse(url="/first_page")

# DEFINE ROUTES
routes = [
    Route("/", endpoint=redirect_to_first_page),
    Mount("/first_page", app=first_page_app),
    Mount("/second_page", app=second_page_app),
    Mount("/third_page", app=third_page_app),
    Mount("/static", app=StaticFiles(directory=".//www"), name="static"),  # Serve static files
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
