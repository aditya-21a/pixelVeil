"""
Local Flask app — the test harness UI described in docs/design.md.
Serves Upload / Processing / Results / Settings screens and triggers
core/video_pipeline.py, streaming progress back to the browser.

This is a development/QA tool only, not the shipped product (see
docs/DECISIONS.md D10).
"""

from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def upload():
    return render_template("upload.html")


@app.route("/processing")
def processing():
    return render_template("processing.html")


@app.route("/results")
def results():
    return render_template("results.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


if __name__ == "__main__":
    app.run(debug=True)
