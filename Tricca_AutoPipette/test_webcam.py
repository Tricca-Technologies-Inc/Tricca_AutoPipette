#!/usr/bin/env python3
import cmd2
import cv2
import threading


class WebcamRecorderApp(cmd2.Cmd):
    def __init__(self):
        super().__init__()
        self.recording = False
        self.thread = None
        self.cap = None
        self.out = None
        self.url = "http://192.168.65.14/webcam/?action=stream"
        self.output_filename = "output.avi"

    def start_recording(self):
        self.cap = cv2.VideoCapture(self.url)
        if not self.cap.isOpened():
            self.poutput("Error: Unable to connect to the webcam stream.")
            return

        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        frame_rate = 20.0
        frame_size = (
            int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        )
        self.out = cv2.VideoWriter(self.output_filename, fourcc, frame_rate, frame_size)
        self.recording = True

        def record():
            while self.recording:
                ret, frame = self.cap.read()
                if not ret:
                    self.poutput("Warning: Frame lost or stream disconnected.")
                    continue  # Try the next frame instead of stopping immediately
                self.out.write(frame)

        self.thread = threading.Thread(target=record, daemon=True)
        self.thread.start()
        self.poutput("Recording started. Use 'stop_recording' to stop.")

    def stop_recording(self):
        if not self.recording:
            self.poutput("Recording is not in progress.")
            return

        self.recording = False
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                self.poutput("Warning: Recording thread did not stop in time.")

        if self.cap:
            self.cap.release()
        if self.out:
            self.out.release()
        self.poutput(f"Recording stopped. Video saved as {self.output_filename}.")

    def postloop(self):
        # Ensure resources are released when exiting the app
        self.stop_recording()
        super().postloop()

    @cmd2.with_category("Webcam")
    def do_start_recording(self, _: cmd2.Statement):
        """Start recording the webcam stream."""
        if self.recording:
            self.poutput("Recording is already in progress.")
        else:
            self.start_recording()

    @cmd2.with_category("Webcam")
    def do_stop_recording(self, _: cmd2.Statement):
        """Stop recording the webcam stream."""
        self.stop_recording()


if __name__ == '__main__':
    app = WebcamRecorderApp()
    app.cmdloop()
