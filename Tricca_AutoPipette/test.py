#!/usr/bin/env python3

import asyncio
import threading
import queue
import cmd2
from cmd2 import Fg, style


class AsyncEventLoopManager:
    """Manages an asyncio event loop in a separate thread."""

    def __init__(self):
        self.event_loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_event_loop, name="AsyncioLoop", daemon=True)
        self.message_queue = queue.Queue()  # Queue for inter-thread communication

    def _run_event_loop(self):
        """Run the asyncio event loop."""
        asyncio.set_event_loop(self.event_loop)
        self.event_loop.run_forever()

    def start(self):
        """Start the event loop in a separate thread."""
        if not self.loop_thread.is_alive():
            self.loop_thread.start()

    def stop(self):
        """Stop the event loop and the thread."""
        if self.event_loop.is_running():
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        if self.loop_thread.is_alive():
            self.loop_thread.join()

    def submit_coroutine(self, coro):
        """Submit a coroutine to the event loop."""
        if self.event_loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self.event_loop)

    def enqueue_message(self, message):
        """Add a message to the queue for processing."""
        self.message_queue.put(message)

    def dequeue_message(self):
        """Retrieve a message from the queue, if any."""
        try:
            return self.message_queue.get_nowait()
        except queue.Empty:
            return None


class AlerterApp(cmd2.Cmd):
    """The main application for the command-line interface."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prompt = "(APR)> "
        self.loop_manager = AsyncEventLoopManager()
        self.alert_task = None  # Task for managing alerts

    def preloop(self):
        """Start the event loop manager before entering the command loop."""
        print("Starting AsyncEventLoopManager...")
        self.loop_manager.start()

    async def alerter_coroutine(self):
        """Coroutine for managing asynchronous alerts."""
        while True:
            await asyncio.sleep(0.5)  # Non-blocking sleep

            # Process messages from the queue
            while True:
                message = self.loop_manager.dequeue_message()
                if message is None:
                    break
                print(f"Processed message: {message}")

            alert_str = self._generate_alert_str()
            new_prompt = self._generate_colored_prompt()
            if alert_str:
                self.async_alert(alert_str, new_prompt)
            elif self.prompt != new_prompt:
                self.async_update_prompt(new_prompt)

    def do_start_alerts(self, _):
        """Start the alerts."""
        if self.alert_task and not self.alert_task.done():
            print("Alerts are already running.")
        else:
            self.alert_task = self.loop_manager.submit_coroutine(self.alerter_coroutine())
            print("Alerts started.")

    def do_stop_alerts(self, _):
        """Stop the alerts."""
        if self.alert_task:
            self.alert_task.cancel()
            print("Alerts stopped.")

    def do_send_message(self, message):
        """Send a message to the asyncio event loop."""
        self.loop_manager.enqueue_message(message)
        print(f"Message sent to event loop: {message}")

    def postloop(self):
        """Stop the event loop manager after exiting the command loop."""
        print("Stopping AsyncEventLoopManager...")
        self.loop_manager.stop()

    @staticmethod
    def _generate_alert_str() -> str:
        """Generate alert string (placeholder for demonstration)."""
        return "This is an alert!"

    def _generate_colored_prompt(self) -> str:
        """Generate a randomly colored prompt."""
        status_color = Fg.LIGHT_BLUE
        return style(self.visible_prompt, fg=status_color)


if __name__ == '__main__':
    app = AlerterApp()
    app.cmdloop()
