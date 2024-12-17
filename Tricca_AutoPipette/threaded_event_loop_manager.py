"""Holds a class used to handle asynchronous tasks."""
import asyncio
import threading
import queue


class ThreadedEventLoopManager:
    """Manages an asyncio event loop in a separate thread."""

    def __init__(self):
        """Initialize self and async utilities."""
        self.event_loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_event_loop,
                                            name="AsyncioLoop",
                                            daemon=True)
        self.message_queue = queue.Queue()  # Queue for inter-thread comms

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
            pending = asyncio.all_tasks(self.event_loop)
            for task in pending:
                task.cancel()
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
