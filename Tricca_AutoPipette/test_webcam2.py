#!/usr/bin/env python3

import cmd2
import subprocess
import threading


class WebcamRecorderApp(cmd2.Cmd):
    def __init__(self):
        super().__init__()
        self.recording_process = None
        self.output_filename = "output.mp4"
        self.stream_url = "http://192.168.65.14/webcam/?action=stream"

    @cmd2.with_category("Webcam")
    def do_start_recording(self, _: cmd2.Statement):
        """Start recording the webcam stream."""
        if self.recording_process and self.recording_process.poll() is None:
            self.poutput("Recording is already in progress.")
            return

        self.poutput("Starting recording...")
        self.recording_process = subprocess.Popen(
            [
                "ffmpeg",
                "-i", self.stream_url,
                "-c:v", "libx264",
                "-r", "30",
                self.output_filename
            ],
            stdout=subprocess.DEVNULL,  # Suppress output
            stderr=subprocess.DEVNULL  # Suppress errors
        )
        self.poutput(f"Recording started. Saving to {self.output_filename}.")

    @cmd2.with_category("Webcam")
    def do_stop_recording(self, _: cmd2.Statement):
        """Stop recording the webcam stream."""
        if not self.recording_process or self.recording_process.poll() is not None:
            self.poutput("Recording is not in progress.")
            return

        self.poutput("Stopping recording...")
        self.recording_process.terminate()
        self.recording_process.wait()
        self.recording_process = None
        self.poutput(f"Recording stopped. Video saved as {self.output_filename}.")

    def postloop(self):
        # Ensure recording is stopped when exiting
        if self.recording_process and self.recording_process.poll() is None:
            self.recording_process.terminate()
            self.recording_process.wait()
        super().postloop()


if __name__ == '__main__':
    app = WebcamRecorderApp()
    app.cmdloop()
