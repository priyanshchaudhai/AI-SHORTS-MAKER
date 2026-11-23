
import os
import re
import uuid
import threading
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify, send_file, render_template_string
from faster_whisper import WhisperModel

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

BASE = Path("/tmp/ai_shorts")
UPLOADS = BASE / "uploads"
OUTPUTS = BASE / "outputs"

UPLOADS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()
processing_lock = threading.Lock()
model = None

MAX_CLIPS = 5
CLIP_LENGTH = 40
STEP = 10


# ---------------- MODEL ----------------

def get_model():
    global model

    if model is None:
        model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=2
        )

    return model


# ---------------- FFmpeg ----------------

def run_command(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])

    return result


def get_duration(path):
    result = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ])

    return float(result.stdout.strip())


# ---------------- VIRAL SCORING ----------------

HOOK_WORDS = [
    "secret", "truth", "mistake", "never", "always",
    "why", "how", "amazing", "crazy", "insane",
    "important", "money", "success", "failure",
    "lesson", "learn", "best", "worst", "stop",
    "listen", "believe", "remember", "problem",
    "solution", "warning", "tip", "trick",
    "million", "billion", "powerful", "change",
    "actually", "surprising", "because", "free",
    "danger", "wrong", "right", "easy"
]

HOOK_PHRASES = [
    "the truth is", "here is why", "here's why",
    "the biggest mistake", "you need to",
    "you should never", "what if",
    "let me tell you", "the secret",
    "this is important", "most people",
    "nobody tells you", "one thing",
    "listen to me", "do not do",
    "don't do", "the problem is",
    "the reason is", "you can actually"
]


def score_window(segments, start, end):
    selected = [
        s for s in segments
        if s["end"] > start and s["start"] < end
    ]

    if not selected:
        return 0

    text = " ".join(s["text"] for s in selected).lower()
    words = re.findall(r"\b[\w']+\b", text)
    count = len(words)

    if count < 15:
        return 0

    score = 0

    for word in HOOK_WORDS:
        matches = len(re.findall(
            r"\b" + re.escape(word) + r"\b",
            text
        ))
        score += min(matches, 3) * 1.5

    for phrase in HOOK_PHRASES:
        if phrase in text:
            score += 5

    duration = max(end - start, 1)
    wps = count / duration

    if 1.8 <= wps <= 3.5:
        score += 8
    elif wps > 1:
        score += 4

    score += text.count("?") * 2
    score += text.count("!") * 2
    score += min(len(selected), 20) * 0.4

    if 20 <= duration <= 45:
        score += 5

    if count < 25:
        score -= 8

    return score


def find_moments(segments, video_duration):
    if video_duration <= CLIP_LENGTH:
        return [{
            "start": 0,
            "end": video_duration,
            "score": score_window(
                segments, 0, video_duration
            )
        }]

    candidates = []

    for start in range(0, int(video_duration), STEP):
        end = min(start + CLIP_LENGTH, video_duration)

        if end - start < 15:
            continue

        score = score_window(segments, start, end)

        if score > 0:
            candidates.append({
                "start": float(start),
                "end": float(end),
                "score": float(score)
            })

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    selected = []

    for candidate in candidates:
        overlapping = False

        for existing in selected:
            overlap = max(
                0,
                min(candidate["end"], existing["end"])
                - max(candidate["start"], existing["start"])
            )

            if overlap > 10:
                overlapping = True
                break

        if not overlapping:
            selected.append(candidate)

        if len(selected) >= MAX_CLIPS:
            break

    selected.sort(key=lambda x: x["start"])

    return selected


# ---------------- SUBTITLES ----------------

def srt_time(seconds):
    seconds = max(0, seconds)

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    sec = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)

    return (
        f"{hours:02}:{minutes:02}:"
        f"{sec:02},{ms:03}"
    )


def create_srt(segments, clip_start, clip_end, srt_path):
    lines = []
    number = 1

    for seg in segments:
        if seg["end"] <= clip_start:
            continue

        if seg["start"] >= clip_end:
            continue

        start = max(0, seg["start"] - clip_start)
        end = min(clip_end, seg["end"]) - clip_start

        if end <= start:
            continue

        text = seg["text"].strip()

        if not text:
            continue

        lines.append(str(number))
        lines.append(
            f"{srt_time(start)} --> {srt_time(end)}"
        )
        lines.append(text)
        lines.append("")
        number += 1

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------- VIDEO RENDER ----------------

def render_clip(video, moment, segments, output_path):
    start = moment["start"]
    end = moment["end"]
    length = end - start

    srt_path = output_path.with_suffix(".srt")

    create_srt(
        segments,
        start,
        end,
        srt_path
    )

    # Paths are created under /tmp and contain no spaces.
    subtitle_filter = (
        "subtitles=" + str(srt_path) +
        ":force_style='FontName=Arial,"
        "FontSize=22,"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "Outline=3,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=180'"
    )

    video_filter = (
        "scale=1080:1920:"
        "force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        + subtitle_filter
    )

    command = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(video),
        "-t", str(length),
        "-vf", video_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path)
    ]

    run_command(command)


# ---------------- BACKGROUND JOB ----------------

def process_job(job_id, video_path):
    try:
        jobs[job_id]["status"] = "Loading AI model"
        jobs[job_id]["progress"] = 5

        whisper = get_model()

        jobs[job_id]["status"] = "Transcribing video audio"
        jobs[job_id]["progress"] = 15

        result, info = whisper.transcribe(
            str(video_path),
            beam_size=1,
            vad_filter=True
        )

        segments = [
            {
                "start": float(s.start),
                "end": float(s.end),
                "text": s.text.strip()
            }
            for s in result
        ]

        if not segments:
            raise RuntimeError(
                "No speech found in the video."
            )

        jobs[job_id]["progress"] = 35
        jobs[job_id]["status"] = "Finding viral moments"

        video_duration = get_duration(video_path)

        moments = find_moments(
            segments,
            video_duration
        )

        if not moments:
            raise RuntimeError(
                "No suitable clips found in the video."
            )

        jobs[job_id]["moments"] = [
            {
                "start": round(m["start"], 2),
                "end": round(m["end"], 2),
                "score": round(m["score"], 2)
            }
            for m in moments
        ]

        output_folder = OUTPUTS / job_id
        output_folder.mkdir(parents=True, exist_ok=True)

        clips = []

        for index, moment in enumerate(moments):
            jobs[job_id]["status"] = (
                f"Rendering Short {index+1}/{len(moments)}"
            )

            progress = 40 + int(
                (index / max(len(moments), 1)) * 55
            )

            jobs[job_id]["progress"] = progress

            output_name = f"short_{index+1}.mp4"
            output_file = output_folder / output_name

            render_clip(
                video_path,
                moment,
                segments,
                output_file
            )

            clips.append(output_name)

        jobs[job_id]["clips"] = clips
        jobs[job_id]["progress"] = 100
        jobs[job_id]["status"] = "Completed"

    except Exception as e:
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"] = str(e)[:2000]

    finally:
        try:
            video_path.unlink(missing_ok=True)
        except Exception:
            pass

        processing_lock.release()


# ---------------- FRONTEND ----------------

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Viral Shorts Maker</title>
<style>
body {
    background:#101827;
    color:white;
    font-family:Arial,sans-serif;
    margin:0;
    padding:20px;
}
.container {
    max-width:700px;
    margin:40px auto;
    background:#1e293b;
    padding:25px;
    border-radius:16px;
}
h1 {
    text-align:center;
    color:#38bdf8;
}
input {
    margin:20px 0;
    width:100%;
}
button {
    width:100%;
    padding:14px;
    background:#0284c7;
    color:white;
    border:0;
    border-radius:10px;
    font-size:17px;
    cursor:pointer;
}
button:disabled {
    opacity:.5;
}
.progress {
    background:#334155;
    height:24px;
    border-radius:12px;
    overflow:hidden;
    margin-top:20px;
}
.bar {
    height:100%;
    background:#22c55e;
    width:0%;
    transition:width .4s;
}
#status {
    text-align:center;
    margin-top:20px;
}
a {
    display:block;
    color:#38bdf8;
    margin:15px 0;
}
.note {
    color:#94a3b8;
    font-size:14px;
}
</style>
</head>
<body>
<div class="container">
<h1>AI Viral Shorts Maker</h1>
<p>Upload your long video. AI will find interesting moments,
make vertical Shorts and burn subtitles.</p>

<input type="file" id="video" accept="video/*">
<button id="btn" onclick="uploadVideo()">Find Viral Moments</button>

<div class="progress">
<div class="bar" id="bar"></div>
</div>

<div id="status">Ready</div>
<div id="downloads"></div>

<p class="note">
This tool scores transcript-based moments. Viral performance
is not guaranteed.
</p>
</div>

<script>
let job = null;

async function uploadVideo() {
    const file = document.getElementById("video").files[0];

    if (!file) {
        alert("Select a video first.");
        return;
    }

    const btn = document.getElementById("btn");
    btn.disabled = true;

    document.getElementById("downloads").innerHTML = "";
    document.getElementById("bar").style.width = "0%";
    document.getElementById("status").innerText = "Uploading video...";

    const form = new FormData();
    form.append("video", file);

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body: form
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Upload failed");
        }

        job = data.job_id;
        checkStatus();

    } catch (e) {
        document.getElementById("status").innerText =
            "Error: " + e.message;
        btn.disabled = false;
    }
}

async function checkStatus() {
    if (!job) return;

    try {
        const response = await fetch("/status/" + job);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Status unavailable");
        }

        document.getElementById("bar").style.width =
            data.progress + "%";

        document.getElementById("status").innerText =
            data.status + " (" + data.progress + "%)";

        if (data.status === "Completed") {
            let html = "<h3>Created Shorts</h3>";

            data.clips.forEach(function(name) {
                html += '<a href="/download/' + job + '/' +
                    encodeURIComponent(name) + '">' +
                    'Download ' + name + '</a>';
            });

            if (data.moments) {
                html += "<h3>Detected moments</h3>";

                data.moments.forEach(function(m, i) {
                    html += "<p>Clip " + (i+1) +
                        ": " + m.start + "s - " + m.end +
                        "s | Score: " + m.score + "</p>";
                });
            }

            document.getElementById("downloads").innerHTML = html;
            document.getElementById("btn").disabled = false;
            job = null;
            return;
        }

        if (data.status === "Failed") {
            document.getElementById("status").innerText =
                "Failed: " + (data.error || "Unknown error");
            document.getElementById("btn").disabled = false;
            job = null;
            return;
        }

        setTimeout(checkStatus, 3000);

    } catch (e) {
        document.getElementById("status").innerText =
            "Connection interrupted. Checking again...";
        setTimeout(checkStatus, 5000);
    }
}
</script>
</body>
</html>
"""


# ---------------- ROUTES ----------------

@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/upload", methods=["POST"])
def upload():
    if not processing_lock.acquire(blocking=False):
        return jsonify({
            "error": "Another video is processing. Please wait."
        }), 429

    try:
        if "video" not in request.files:
            processing_lock.release()
            return jsonify({"error": "Video missing"}), 400

        file = request.files["video"]

        if not file.filename:
            processing_lock.release()
            return jsonify({"error": "Invalid filename"}), 400

        job_id = str(uuid.uuid4())

        video_path = UPLOADS / f"{job_id}.video"
        file.save(video_path)

        jobs[job_id] = {
            "status": "Queued",
            "progress": 0,
            "clips": [],
            "moments": [],
            "error": None
        }

        thread = threading.Thread(
            target=process_job,
            args=(job_id, video_path),
            daemon=True
        )

        thread.start()

        return jsonify({"job_id": job_id})

    except Exception as e:
        if processing_lock.locked():
            processing_lock.release()

        return jsonify({"error": str(e)}), 500


@app.route("/status/<job_id>")
def status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(jobs[job_id])


@app.route("/download/<job_id>/<filename>")
def download(job_id, filename):
    folder = OUTPUTS / job_id
    path = folder / filename

    if not path.exists() or path.parent != folder:
        return jsonify({"error": "File not found"}), 404

    return send_file(
        str(path),
        as_attachment=True,
        download_name=filename
    )


@app.errorhandler(413)
def too_large(error):
    return jsonify({
        "error": "Maximum upload size is 500 MB."
    }), 413


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
