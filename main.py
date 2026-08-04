"""
PixelVeil — entry point.

Launches the Tkinter product GUI (gui/app.py).
For development/testing, use webtest/server.py instead (Flask test harness).
"""

from gui.app import launch_app

if __name__ == "__main__":
    launch_app()
