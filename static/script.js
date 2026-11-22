const form = document.getElementById("uploadForm");
const videoInput = document.getElementById("videoFile");
const formatInput = document.getElementById("format");
const statusText = document.getElementById("status");

const resultsBox = document.createElement("div");
resultsBox.id = "results";
form.after(resultsBox);

const progressBox = document.createElement("div");
progressBox.innerHTML = `
  <div id="progressText" style="margin-top:20px">
    Ready
  </div>
  <div style="background:#34415c;height:14px;border-radius:20px;overflow:hidden;margin-top:10px">
    <div id="progressBar" style="width:0%;height:100%;background:#18a878;transition:width .3s"></div>
  </div>
`;
statusText.after(progressBox);

const progressBar = document.getElementById("progressBar");
const progressText = document.getElementById("progressText");

function showProgress(value, message) {
    const percent = Math.max(0, Math.min(100, value));

    progressBar.style.width = percent + "%";
    progressText.textContent = percent + "% - " + message;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function parseResponse(text) {
    try {
        return JSON.parse(text);
    } catch {
        throw new Error(
            "Server returned an empty or invalid response. Please check Render Logs."
        );
    }
}

function uploadFile(formData) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();

        xhr.open("POST", "/upload");

        xhr.upload.onprogress = function(event) {
            if (event.lengthComputable) {
                const percent = Math.round(
                    event.loaded / event.total * 100
                );

                showProgress(percent, "Uploading video...");
            }
        };

        xhr.onload = function() {
            const result = parseResponse(xhr.responseText);

            if (xhr.status < 200 || xhr.status >= 300) {
                reject(new Error(result.detail || "Upload failed"));
                return;
            }

            resolve(result);
        };

        xhr.onerror = function() {
            reject(new Error("Network error during upload."));
        };

        xhr.send(formData);
    });
}

async function checkJob(jobId) {
    while (true) {
        const response = await fetch(
            "/status/" + encodeURIComponent(jobId)
        );

        const result = parseResponse(await response.text());

        if (!response.ok) {
            throw new Error(result.detail || "Status check failed");
        }

        showProgress(result.progress, result.message);

        if (result.status === "completed") {
            return result;
        }

        if (result.status === "failed") {
            throw new Error(result.message || "AI processing failed");
        }

        await sleep(2500);
    }
}

function showResults(shorts) {
    resultsBox.replaceChildren();

    if (!shorts || shorts.length === 0) {
        statusText.textContent = "No suitable clips found.";
        return;
    }

    const heading = document.createElement("h2");
    heading.textContent = "Your AI Shorts 🎬";
    resultsBox.appendChild(heading);

    shorts.forEach((short, index) => {
        const card = document.createElement("div");

        card.style.padding = "15px";
        card.style.margin = "15px 0";
        card.style.background = "#252f48";
        card.style.borderRadius = "12px";

        const title = document.createElement("h3");
        title.textContent = "Short Video " + (index + 1);

        const video = document.createElement("video");
        video.src = short.video_url;
        video.controls = true;
        video.playsInline = true;
        video.style.width = "100%";
        video.style.maxWidth = "300px";

        const download = document.createElement("a");
        download.href = short.video_url;
        download.download = short.video;
        download.textContent = "⬇ Download Short Video";

        const captions = document.createElement("a");
        captions.href = short.captions_url;
        captions.download = short.captions;
        captions.textContent = "⬇ Download Captions";

        download.style.display = "block";
        captions.style.display = "block";
        download.style.marginTop = "12px";
        captions.style.marginTop = "10px";

        card.append(title, video, download, captions);
        resultsBox.appendChild(card);
    });
}

form.addEventListener("submit", async function(event) {
    event.preventDefault();

    const file = videoInput.files[0];

    if (!file) {
        statusText.textContent = "Please select a video!";
        return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("format", formatInput.value);

    resultsBox.replaceChildren();

    const button = form.querySelector("button");
    button.disabled = true;
    button.textContent = "AI Processing...";

    try {
        statusText.textContent = "Uploading your video...";
        showProgress(0, "Starting upload...");

        const uploadResult = await uploadFile(formData);

        if (!uploadResult.job_id) {
            throw new Error("Server did not return a Job ID.");
        }

        statusText.textContent =
            "Video uploaded. AI processing started...";

        const result = await checkJob(uploadResult.job_id);

        statusText.textContent = result.message;
        showProgress(100, "Completed!");

        showResults(result.shorts);

    } catch (error) {
        statusText.textContent = "Error: " + error.message;
    } finally {
        button.disabled = false;
        button.textContent = "🚀 Generate AI Shorts";
    }
});
