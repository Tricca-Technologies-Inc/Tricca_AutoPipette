"""Hold the TAPScreenPrinter Class."""
from io import StringIO
from rich.console import Console
from rich import print as rprint
from cmd2 import ansi
from threading import Thread, Event, Lock
from asyncio import Queue, run_coroutine_threadsafe, \
    set_event_loop, new_event_loop, AbstractEventLoop, wait_for
from res.string_constants import TAP_CLR_BANNER


class TAPScreenPrinter():
    """Create an ANSI string to be printed to the terminal as an alert."""

    console_buf: StringIO = None
    console: Console = None
    terminal_lock: Lock = None
    _alerter_thread: Thread = None
    _stop_event: Event = None
    alert_queue: Queue = None
    loop: AbstractEventLoop = None

    def __init__(self, parent, need_prompt_refresh,
                 async_refresh_prompt, terminal_lock):
        """Instantiate the TAPAlertPrinter object."""
        # Passed in functions
        self.parent = parent
        self.need_prompt_refresh = need_prompt_refresh
        self.async_refresh_prompt = async_refresh_prompt
        # Passed in objs
        self.terminal_lock = terminal_lock
        # Create objs
        self.console_buf = StringIO()
        self.console = Console(file=self.console_buf,
                               color_system="truecolor",
                               force_terminal=True)
        self.alert_queue = Queue()
        self._stop_event = Event()
        self._stop_event.clear()
        self.run_alerter()

    def run_alerter(self):
        """Run a thread to print alerts."""
        if self._alerter_thread is not None and self._alerter_thread.is_alive():
            rprint("Alerter thread is already running")
            return
        # Add loop to async stuff to allow non-async to append to alert queue
        self.loop = new_event_loop()
        self._alerter_thread = Thread(name='alerter',
                                      target=self.start_async_loop,
                                      args=(self.loop,),
                                      daemon=True)
        self._alerter_thread.start()
        run_coroutine_threadsafe(self._alerter_thread_func(),
                                 self.loop)

    def start_async_loop(self, loop):
        """Start a new event loop for the async code."""
        set_event_loop(loop)
        loop.run_forever()

    def refresh_screen(self):
        """Print the intro and update data fields."""
        # Clear the buffer
        self.console_buf.truncate(0)
        self.console_buf.seek(0)
        # Clear screen
        self.console.print(ansi.clear_screen(), end="", markup=False)
        self.console.print(ansi.Cursor.SET_POS(0, 0), end="", markup=-False)
        # Print the intro
        self.console.print(TAP_CLR_BANNER)
        self.append_to_alert(self.console_buf.getvalue())

    async def _alerter_thread_func(self) -> None:
        """Print alerts and update the prompt."""
        rprint("Start alerter loop")
        while not self._stop_event.is_set():
            try:
                if self.terminal_lock.acquire(blocking=False):
                    try:
                        if not self.alert_queue.empty():
                            rprint("not empty")
                            alert_str = await self.alert_queue.get()
                            rprint(alert_str)
                            self.parent.async_alert(self.get_formatted_str(alert_str))
                        if self.need_prompt_refresh():
                            await self.async_refresh_prompt()
                    finally:
                        self.terminal_lock.release()
            except TimeoutError:
                pass

    def get_formatted_str(self, text: str) -> str:
        """Return a string formatted by ANSI."""
        # Clear the buffer by truncating and seeking back to the start
        self.console_buf.truncate(0)
        self.console_buf.seek(0)
        self.console.print(text, end="")
        return self.console_buf.getvalue()

    def start_alerts(self):
        """Start the alerter thread."""
        if self._alerter_thread.is_alive():
            rprint("The alert thread is already started")
        else:
            self._stop_event.clear()
            self._alerter_thread = Thread(name='alerter',
                                          target=self._alerter_thread_func)
            self._alerter_thread.start()

    def stop_alerts(self):
        """Stop the alerter thread."""
        self._stop_event.set()
        if self._alerter_thread.is_alive():
            self._alerter_thread.join()
        else:
            rprint("The alert thread is already stopped")

    async def async_append_to_alert(self, message: str):
        """Append a message to the send queue."""
        rprint(f"async append {message}")
        await self.alert_queue.put(message)

    def append_to_alert(self, message: str):
        """Append a message to the send queue."""
        rprint("appendtoalert")
        run_coroutine_threadsafe(self.async_append_to_alert(message),
                                 self.loop)

    def close(self):
        """Close the buffer before destroying the class."""
        self._stop_event.set()
        if self._alerter_thread and self._alerter_thread.is_alive():
            self._alerter_thread.join()
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop.close()
        self.console_buf.close()
