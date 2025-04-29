"""Holds class and methods for manipulating a webcam."""
import cv2
import os
import sys
import urllib.request
import numpy as np


class TAPWebcam():
    """Webcam utilities for Tricca AutoPipette."""

    def __init__(self):
        """Initialize self."""
        pass

    def suppress_ffmpeg_logs(self):
        """Suppress FFmpeg's error and warning messages."""
        sys.stderr = open(os.devnull, 'w')

    def stream_webcam(self, url: str):
        """Stream from the webcam."""
        try:
            stream = urllib.request.urlopen(url)
            byte_data = b""
            print("Streaming video. Press 'q' to quit.")

            # Suppress FFmpeg logs
            self.suppress_ffmpeg_logs()

            while True:
                byte_data += stream.read(1024)
                start = byte_data.find(b'\xff\xd8')  # Start of JPEG
                end = byte_data.find(b'\xff\xd9')    # End of JPEG

                if start != -1 and end != -1:
                    jpg_data = byte_data[start:end+2]
                    byte_data = byte_data[end+2:]

                    try:
                        # Decode JPEG frame
                        frame = cv2.imdecode(np.frombuffer(jpg_data, np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            cv2.imshow("Web Camera Stream", frame)

                            # Exit on 'q'
                            if cv2.waitKey(1) & 0xFF == ord('q'):
                               break
                    except Exception as e:
                        print(f"Failed to decode frame: {e}")

            cv2.destroyAllWindows()
        except Exception as e:
            print(f"Error connecting to stream: {e}")
