
const form = document.getElementById("uploadForm");
const videoInput = document.getElementById("videoFile");
const formatInput = document.getElementById("format");
const statusText = document.getElementById("status");

const durationInput = document.getElementById("duration");

const resultsBox = document.createElement("div");
resultsBox.id = "results";
resultsBox.style.marginTop = "30px";
form.after(resultsBox);

const fileInfo = document.createElement("div");
fileInfo.style.cssText =
    "margin-top:12px;color:#a78bfa;font-size:14px;";

videoInput.after(fileInfo);

videoInput.addEventListener("change", () => {
    const file = videoInput.files[0];

    fileInfo.textContent = file
        ? `Selected: ${file.name} • ${(file.size / 1048576).toFixed(2)} MB`
        : "";
});

const progressBox = document.createElement("div");

progressBox.innerHTML = `
<div id="progressText" style="margin-top:20px;color:#c4b5fd">
Ready to create
</div>

<div style="background:#29293b;height:12px;border-radius:20px;
overflow:hidden;margin-top:10px">

<div id="progressBar" style="width:0%;height:100%;
background:linear-gradient(90deg,#8b5cf6,#67e8b5);
transition:width .3s"></div>

</div>
`;

statusText.after(progressBox);

const progressBar = document.getElementById("progressBar");
const progressText = document.getElementById("progressText");

function showProgress(value, message) {
    const percent = Math.max(0, Math.min(100, value || 0));

    progressBar.style.width = percent + "%";
    progressText.textContent = percent + "% • " + message;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function readResponse(response) {
    const text = await response.text();

    let data;

    try {
        data = JSON.parse(text);
    } catch {
        throw new Error(
            "Invalid server response. Check Render logs."
        );
    }

    if (!response.ok) {
        throw new Error(
            data.message ||
            data.detail ||
            "Server error: " + response.status
        );
    }

    return data;
}

// Upload video
function uploadFile(formData) {
    return new Promise((resolve, reject) => {

        const xhr = new XMLHttpRequest();

        xhr.open("POST", "/upload");
        xhr.timeout = 0;

        xhr.upload.onprogress = event => {
            if (event.lengthComputable) {

                const percent = Math.round(
                    event.loaded / event.total * 100
                );

                showProgress(percent, "Uploading video...");
            }
        };

        xhr.onload = async () => {
            try {
                const result = await readResponse({
                    status: xhr.status,
                    ok: xhr.status >= 200 && xhr.status < 300,
                    text: async () => xhr.responseText
                });

                resolve(result);

            } catch (error) {
                reject(error);
            }
        };

        xhr.onerror = () =>
            reject(new Error("Upload connection failed."));

        xhr.ontimeout = () =>
            reject(new Error("Upload timed out."));

        xhr.send(formData);
    });
}

// Start processing
async function startProcessing(filename, duration, format) {

    const response = await fetch("/process", {
        method: "POST",

        headers: {
            "Content-Type": "application/json"
        },

        body: JSON.stringify({
            filename: filename,
            duration: duration,
            format: format
        })
    });

    return await readResponse(response);
}

// Check processing status
async function checkJob(statusUrl) {

    let failures = 0;

    while (true) {

        try {

            const response = await fetch(statusUrl, {
                cache: "no-store"
            });

            const result = await readResponse(response);

            failures = 0;

            showProgress(
                result.progress,
                result.message || "Processing..."
            );

            if (result.status === "completed") {
                return result;
            }

            if (result.status === "failed") {
                throw new Error(
                    result.message || "Processing failed."
                );
            }

        } catch (error) {

            if (
                error.message.includes("Processing failed") ||
                error.message.includes("Server error:")
            ) {
                throw error;
            }

            failures++;

            if (failures >= 5) {
                throw new Error(
                    "Server connection lost. Try again."
                );
            }

            statusText.textContent =
                "Reconnecting to server...";
        }

        await sleep(3000);
    }
}

// Create download link
function createLink(url, text, filename) {

    if (!url) return null;

    const link = document.createElement("a");

    link.href = url;
    link.textContent = text;

    if (filename) {
        link.download = filename;
    }

    link.style.cssText = `
        display:inline-block;
        margin-top:12px;
        margin-right:10px;
        padding:12px 16px;
        background:#28243d;
        color:#c4b5fd;
        text-decoration:none;
        border-radius:10px;
        font-weight:bold;
    `;

    return link;
}

// Show generated shorts
function showResults(shorts) {

    resultsBox.replaceChildren();

    if (!shorts || shorts.length === 0) {

        statusText.textContent =
            "No suitable clips found.";

        return;
    }

    const heading = document.createElement("h2");

    heading.textContent = "✦ Your AI Shorts";

    resultsBox.appendChild(heading);

    shorts.forEach((short, index) => {

        const card = document.createElement("div");

        card.style.cssText = `
            padding:20px;
            margin:18px 0;
            background:#13131d;
            border:1px solid #29293b;
            border-radius:18px;
        `;

        const title = document.createElement("h3");

        title.textContent =
            "🎬 Short Video " + (index + 1);

        card.appendChild(title);

        if (short.video_url) {

            const video = document.createElement("video");

            video.src = short.video_url;
            video.controls = true;
            video.playsInline = true;

            video.style.cssText = `
                width:100%;
                max-width:350px;
                display:block;
                border-radius:14px;
                background:#000;
            `;

            card.appendChild(video);

            const download = createLink(
                short.video_url,
                "⬇ Download Short",
                short.video
            );

            if (download) {
                card.appendChild(download);
            }
        }

        if (short.captions_url) {

            const captions = createLink(
                short.captions_url,
                "⬇ Download Captions",
                short.captions
            );

            if (captions) {
                card.appendChild(captions);
            }
        }

        resultsBox.appendChild(card);
    });
}

// Main submit
form.addEventListener("submit", async event => {

    event.preventDefault();

    const file = videoInput.files[0];

    if (!file) {
        statusText.textContent =
            "Please select a video!";
        return;
    }

    const duration = durationInput
        ? Number(durationInput.value)
        : 30;

    if (![30, 60].includes(duration)) {
        statusText.textContent =
            "Please select 30 or 60 seconds.";
        return;
    }

    const formData = new FormData();

    // Backend upload field
    formData.append("video", file);

    const button = form.querySelector("button");

    resultsBox.replaceChildren();

    button.disabled = true;
    button.textContent = "✦ AI Processing...";

    try {

        statusText.textContent =
            "Uploading your video...";

        showProgress(0, "Starting upload...");

        // 1. Upload
        const uploadResult = await uploadFile(formData);

        if (!uploadResult.filename) {
            throw new Error(
                "Server did not return filename."
            );
        }

        statusText.textContent =
            "Upload complete. Starting AI...";

        // 2. Start processing
        const processResult = await startProcessing(
            uploadResult.filename,
            duration,
            formatInput.value
        );

        const statusUrl = processResult.status_url ||
            (processResult.job_id
                ? "/status/" + encodeURIComponent(processResult.job_id)
                : null);

        if (!statusUrl) {
            throw new Error(
                "Server did not return a job status URL."
            );
        }

        // 3. Wait for completion
        const result = await checkJob(statusUrl);

        statusText.textContent =
            "Your Shorts are ready!";

        showProgress(100, "Completed!");

        // 4. Show videos
        showResults(result.shorts);

    } catch (error) {

        statusText.textContent =
            "Error: " + error.message;

        progressText.textContent =
            "Processing stopped.";

        console.error(error);

    } finally {

        button.disabled = false;

        button.textContent =
            "✦ Generate AI Shorts";
    }
});
