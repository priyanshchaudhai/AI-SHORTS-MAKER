
import os
import tempfile
import shutil
from pathlib import Path

import imageio_ffmpeg
from faster_whisper import WhisperModel

from flask import Flask, request, jsonify

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

MODEL = None


def get_model():
    global MODEL

    if MODEL is None:
        MODEL = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8"
        )

    return MODEL


@app.route("/")
def home():
    return jsonify({
        "app": "AI Shorts Maker",
        "status": "running",
        "version": "1.0"
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy"
    })


@app.route("/upload", methods=["POST"])
def upload_video():

    if "video" not in request.files:
        return jsonify({"error": "Video file missing"}), 400

    video = request.files["video"]

    if not video.filename:
        return jsonify({"error": "Filename missing"}), 400

    filename = os.path.basename(video.filename)

    video_path = os.path.join(UPLOAD_FOLDER, filename)

    video.save(video_path)

    return jsonify({
        "message": "Video uploaded successfully",
        "filename": filename
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
