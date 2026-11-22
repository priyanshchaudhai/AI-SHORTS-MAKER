
import subprocess
from pathlib import Path

import imageio_ffmpeg
from faster_whisper import WhisperModel

MODEL = None


def get_model(progress_callback=None):
    global MODEL

    if MODEL is None:
        if progress_callback:
            progress_callback(10, "Loading AI speech model...")

        MODEL = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8"
        )

    return MODEL


def make_srt_time(seconds):
    total_ms = round(seconds * 1000)

    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)

    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def process_video(
    video_path,
    output_dir,
    video_format="9:16",
    progress_callback=None
):
    def update(value, message):
        if progress_callback:
            progress_callback(value, message)

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load AI model
    update(5, "Preparing AI model...")

    model = get_model(update)

    # Analyze video speech
    update(15, "AI is analyzing your video...")

    segments, info = model.transcribe(
        str(video_path),
        vad_filter=True
    )

    transcript = []
    duration = info.duration or 0

    for segment in segments:
        transcript.append(segment)

        if duration > 0:
            progress = 15 + int(
                min(segment.end / duration, 1) * 35
            )

            update(
                min(progress, 50),
                "AI is analyzing your video..."
            )

    if not transcript:
        raise ValueError(
            "No speech detected in video. Please try a video with speech."
        )

    duration = duration or transcript[-1].end

    if duration <= 0:
        raise ValueError("Could not determine video duration.")

    update(50, "AI analysis completed. Finding clips...")

    # Find interesting video windows
    clip_length = 30

    keywords = [
        "wow", "amazing", "secret",
        "important", "best", "why",
        "how", "incredible", "never"
    ]

    windows = []
    start = 0

    while start < duration:
        end = min(start + clip_length, duration)

        if end - start >= 5:
            score = 0
            selected = []

            for segment in transcript:
                overlap = max(
                    0,
                    min(segment.end, end)
                    - max(segment.start, start)
                )

                if overlap > 0:
                    score += overlap
                    selected.append(segment)

                    text = segment.text.lower()

                    score += sum(
                        2 for word in keywords
                        if word in text
                    )

            if selected:
                windows.append(
                    (score, start, end, selected)
                )

        start += clip_length

    windows.sort(
        key=lambda item: item[0],
        reverse=True
    )

    if not windows:
        raise ValueError("No suitable clips found.")

    # Prepare FFmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    formats = {
        "9:16": "1080:1920",
        "16:9": "1920:1080",
        "1:1": "1080:1080"
    }

    if video_format not in formats:
        raise ValueError("Unsupported output format.")

    width, height = formats[video_format].split(":")

    results = []
    selected_windows = windows[:3]

    # Create video clips
    for index, (_, start, end, selected) in enumerate(
        selected_windows, start=1
    ):
        progress = 55 + int(
            (index - 1) / len(selected_windows) * 40
        )

        update(
            progress,
            f"Creating AI Short {index} of {len(selected_windows)}..."
        )

        output_video = output_dir / f"short_{index}.mp4"
        output_srt = output_dir / f"short_{index}.srt"

        filter_video = (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )

        command = [
            ffmpeg,
            "-y",
            "-ss", str(start),
            "-i", str(video_path),
            "-t", str(end - start),
            "-vf", filter_video,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_video)
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600
        )

        if result.returncode != 0:
            raise RuntimeError(
                "FFmpeg error: " + result.stderr[-2000:]
            )

        # Create subtitles
        subtitles = []

        for segment in selected:
            sub_start = max(segment.start, start) - start
            sub_end = min(segment.end, end) - start

            if sub_end <= sub_start:
                continue

            subtitles.append(
                f"{len(subtitles) + 1}\n"
                f"{make_srt_time(sub_start)} --> "
                f"{make_srt_time(sub_end)}\n"
                f"{segment.text.strip()}\n"
            )

        output_srt.write_text(
            "\n".join(subtitles),
            encoding="utf-8"
        )

        results.append({
            "video": output_video.name,
            "captions": output_srt.name,
            "start": start,
            "end": end
        })

    update(100, "AI Shorts are ready!")

    return results
