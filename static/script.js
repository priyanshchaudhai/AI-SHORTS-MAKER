
const form = document.getElementById("uploadForm");
const videoInput = document.getElementById("videoFile");
const formatInput = document.getElementById("format");
const statusText = document.getElementById("status");

const resultsBox = document.createElement("div");
resultsBox.id = "results";
resultsBox.style.marginTop = "30px";
form.after(resultsBox);

const fileInfo = document.createElement("div");
fileInfo.style.cssText = `
  margin-top:12px;
  color:#a78bfa;
  font-size:14px;
  line-height:1.6;
`;
videoInput.after(fileInfo);

videoInput.addEventListener("change", function() {
    const file = videoInput.files[0];

    if (!file) {
        fileInfo.textContent = "";
        return;
    }

    fileInfo.textContent =
        "Selected: " + file.name + " • " +
        (file.size / (1024 * 1024)).toFixed(2) + " MB";
});

const progressBox = document.createElement("div");

progressBox.innerHTML = `
  <div id="progressText"
       style="margin-top:20px;color:#c4b5fd;font-size:14px">
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
    const percent = Math.max(0, Math.min(100, value));
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
            "Server returned invalid data (HTTP " +
            response.status +
            "). Check Render logs."
        );
    }

    if (!response.ok) {
        throw new Error(
            data.detail || data.message ||
            "Server error: HTTP " + response.status
        );
    }

    return data;
}

function uploadFile(formData) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();

        xhr.open("POST", "/upload");
        xhr.timeout = 0;

        xhr.upload.onprogress = function(event) {
            if (event.lengthComputable) {
                const percent = Math.round(
                    event.loaded / event.total * 100
                );

                showProgress(percent, "Uploading video...");
            }
        };

        xhr.onload = async function() {
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

        xhr.onerror = function() {
            reject(new Error(
                "Upload connection failed. Render may have stopped."
            ));
        };

        xhr.onabort = function() {
            reject(new Error("Upload cancelled."));
        };

        xhr.ontimeout = function() {
            reject(new Error("Upload timed out."));
        };

        xhr.send(formData);
    });
}

async function checkJob(jobId) {
    let failures = 0;

    while (true) {
        let response;
        let result;

        try {
            response = await fetch(
                "/status/" + encodeURIComponent(jobId),
                { cache: "no-store" }
            );

            result = await readResponse(response);
            failures = 0;

        } catch (error) {
            failures++;

            if (failures >= 5) {
                throw new Error(
                    "Unable to reach server after several attempts: " +
                    error.message
                );
            }

            statusText.textContent =
                "Server temporarily unavailable. Reconnecting...";

            await sleep(4000);
            continue;
        }

        showProgress(
            result.progress || 0,
            result.message || "Processing..."
        );

        if (result.status === "completed") {
            return result;
        }

        if (result.status === "failed") {
            throw new Error(result.message || "AI processing failed");
        }

        await sleep(3000);
    }
}

function createLink(url, text, downloadName) {
    if (!url) return null;

    const link = document.createElement("a");
    link.href = url;
    link.textContent = text;

    if (downloadName) {
        link.download = downloadName;
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
      font-size:14px;
    `;

    return link;
}

function showResults(shorts) {
    resultsBox.replaceChildren();

    if (!shorts || shorts.length === 0) {
        statusText.textContent = "No suitable clips found.";
        return;
    }

    const heading = document.createElement("h2");
    heading.textContent = "✦ Your AI Shorts";
    heading.style.marginBottom = "20px";
    resultsBox.appendChild(heading);

    shorts.forEach((short, index) => {
        const card = document.createElement("div");

        card.style.cssText = `
          padding:20px;margin:18px 0;background:#13131d;
          border:1px solid #29293b;border-radius:18px;
        `;

        const title = document.createElement("h3");
        title.textContent = "🎬 Short Video " + (index + 1);
        title.style.marginBottom = "15px";
        card.appendChild(title);

        if (short.video_url) {
            const video = document.createElement("video");
            video.src = short.video_url;
            video.controls = true;
            video.playsInline = true;
            video.style.cssText = `
              width:100%;max-width:350px;display:block;
              border-radius:14px;background:#000;
            `;
            card.appendChild(video);

            const download = createLink(
                short.video_url, "⬇ Download Short", short.video
            );

            if (download) card.appendChild(download);
        }

        if (short.captions_url) {
            const captions = createLink(
                short.captions_url,
                "⬇ Download Captions",
                short.captions
            );

            if (captions) card.appendChild(captions);
        }

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
    button.textContent = "✦ AI Processing...";

    try {
        statusText.textContent = "Uploading your video...";
        showProgress(0, "Starting upload...");

        const uploadResult = await uploadFile(formData);

        if (!uploadResult.job_id) {
            throw new Error("Server did not return a Job ID.");
        }

        statusText.textContent =
            "Upload complete. AI processing started...";

        const result = await checkJob(uploadResult.job_id);

        statusText.textContent = "Your Shorts are ready!";
        showProgress(100, "Completed!");
        showResults(result.shorts);

    } catch (error) {
        statusText.textContent = "Error: " + error.message;
        progressText.textContent = "Processing stopped.";
        console.error(error);

    } finally {
        button.disabled = false;
        button.textContent = "✦ Generate AI Shorts";
    }
});
