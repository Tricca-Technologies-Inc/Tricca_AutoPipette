#!/usr/bin/env python3
import asyncio
import threading
import json
import websockets
from cmd2 import Cmd2ArgumentParser


def main():
    argparser = Cmd2ArgumentParser()
    argparser.add_argument("ip", type=str,
                           help="ip address of the autopipette")
    args = argparser.parse_args()
    data_dict = {}
    event = threading.Event()
    url = "ws://" + args.ip + ":7125/websocket"  # Replace with your WebSocket server URL
    objs = {"gcode_move": None, "toolhead": ["position", "status"]}

    # Start the WebSocket listener in a separate thread
    run_websocket_listener(data_dict, event, url, objs)

    # Main loop: wait for new data and print it
    while True:
        event.wait()  # Block until new data is available
        event.clear()  # Reset the event for the next update
        try:
            print("Current Position:", data_dict['latest'])
        except KeyError:
            pass


async def sub_to_printer_objs(url, objs, data_dict, event):
    """Connects to the WebSocket server, subscribes to printer objects,
    and updates data_dict with incoming messages.
    """
    async with websockets.connect(url) as websocket:
        # Send the subscription request
        subscribe_message = {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {
                "objects": objs
            },
            "id": 5434
        }
        await websocket.send(json.dumps(subscribe_message))

        # Continuously listen for messages and update the data_dict
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            data_dict['latest'] = data
            event.set()  # Notify synchronous code that new data has arrived


def start_async_loop(loop):
    """Starts a new event loop for the async code.
    """
    asyncio.set_event_loop(loop)
    loop.run_forever()


def run_websocket_listener(data_dict, event, url, objs):
    """Starts the async WebSocket listener in a separate thread.
    """
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=start_async_loop, args=(loop,))
    t.start()
    # Run the async websocket listener coroutine in the new loop
    asyncio.run_coroutine_threadsafe(
        sub_to_printer_objs(url, objs, data_dict, event), loop
    )


if __name__ == "__main__":
    main()
