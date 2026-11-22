import subprocess
from pathlib import Path

import imageio_ffmpeg
from faster_whisper import WhisperModel

MODEL = None


def get_model():
    global MODEL

    if MODEL is None:
        MODEL = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8"
        )

    return MODEL


def make_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)

    return (
        f"{hours:02}:{minutes:02}:"
        f"{secs:02},{millis:03}"
    )


def process_video(video_path, output_dir, video_format="9:16"):
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = get_model()

    segments, info = model.transcribe(
        str(video_path),
        vad_filter=True
    )

    transcript = list(segments)

    if not transcript:
        raise ValueError("No speech detected in video.")

    duration = info.duration
    clip_length = 30
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

                    keywords = [
                        "wow", "amazing", "secret",
                        "important", "best", "why",
                        "how", "incredible", "never"
                    ]

                    score += sum(
                        2 for word in keywords
                        if word in text
                    )

            windows.append(
                (score, start, end, selected)
            )

        start += clip_length

    windows.sort(
        key=lambda item: item[0],
        reverse=True
    )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    formats = {
        "9:16": "1080:1920",
        "16:9": "1920:1080",
        "1:1": "1080:1080"
    }

    if video_format not in formats:
        raise ValueError("Unsupported video format")

    width, height = formats[video_format].split(":")

    results = []

    for index, (_, start, end, selected) in enumerate(
        windows[:3], start=1
    ):
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

        subprocess.run(
            command,
            check=True,
            capture_output=True
        )

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

    return results
