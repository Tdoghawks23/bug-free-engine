(function () {
  "use strict";

  var form = document.getElementById("upload-form");
  var fileInput = document.getElementById("file-input");
  var submitButton = document.getElementById("submit-button");
  var uploadError = document.getElementById("upload-error");

  var progressSection = document.getElementById("progress-section");
  var progressFilename = document.getElementById("progress-filename");
  var progressBar = document.getElementById("progress-bar");
  var progressBarFill = document.getElementById("progress-bar-fill");
  var progressStatus = document.getElementById("progress-status");

  var errorSection = document.getElementById("error-section");
  var errorMessage = document.getElementById("error-message");

  var resultsSection = document.getElementById("results-section");
  var resultsSummary = document.getElementById("results-summary");
  var reviewCount = document.getElementById("review-count");
  var downloadsList = document.getElementById("downloads-list");

  var pollTimer = null;

  var ARTIFACT_LABELS = {
    pdf: "Tagged PDF",
    html: "Accessible HTML",
    "report.html": "Compliance report (HTML)",
    "report.json": "Compliance report (JSON)"
  };

  var STAGE_LABELS = {
    queued: "Queued",
    extracting: "Extracting document content",
    generating_html: "Generating accessible HTML",
    rendering_pdf: "Rendering tagged PDF",
    building_report: "Building compliance report",
    done: "Done",
    error: "Error"
  };

  function resetSections() {
    progressSection.hidden = true;
    errorSection.hidden = true;
    resultsSection.hidden = true;
    uploadError.textContent = "";
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    stopPolling();
    resetSections();

    var file = fileInput.files[0];
    if (!file) {
      uploadError.textContent = "Choose a .pdf or .docx file first.";
      return;
    }

    var formData = new FormData();
    formData.append("file", file);

    submitButton.disabled = true;
    fetch("/jobs", { method: "POST", body: formData })
      .then(function (response) {
        return response.json().then(function (body) {
          if (!response.ok) {
            throw new Error(body.detail || "Upload failed.");
          }
          return body;
        });
      })
      .then(function (body) {
        progressSection.hidden = false;
        progressFilename.textContent = "File: " + file.name;
        pollJob(body.id);
      })
      .catch(function (err) {
        uploadError.textContent = err.message;
      })
      .finally(function () {
        submitButton.disabled = false;
      });
  });

  function pollJob(jobId) {
    fetch("/jobs/" + jobId)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Lost track of this job (HTTP " + response.status + ").");
        }
        return response.json();
      })
      .then(function (job) {
        renderJob(job);
        if (job.state === "queued" || job.state === "processing") {
          pollTimer = setTimeout(function () {
            pollJob(jobId);
          }, 1000);
        }
      })
      .catch(function (err) {
        progressSection.hidden = true;
        errorSection.hidden = false;
        errorMessage.textContent = err.message;
      });
  }

  function renderJob(job) {
    if (job.state === "done") {
      progressSection.hidden = true;
      renderResults(job);
      return;
    }
    if (job.state === "error") {
      progressSection.hidden = true;
      errorSection.hidden = false;
      errorMessage.textContent = job.error || "Processing failed.";
      return;
    }

    var pct = Math.round((job.pct || 0) * 100);
    progressBar.setAttribute("aria-valuenow", String(pct));
    progressBarFill.style.width = pct + "%";
    var label = STAGE_LABELS[job.stage] || job.stage;
    progressStatus.textContent = label + " (" + pct + "%)";
  }

  function renderResults(job) {
    resultsSection.hidden = false;
    var summary = job.summary || {};
    var autoFixed = summary["auto-fixed"] || 0;
    var needsReview = summary["needs-human-review"] || 0;
    var info = summary["info"] || 0;
    var total = summary.total_items || autoFixed + needsReview + info;

    resultsSummary.textContent =
      "Compliance report: " + total + " item(s) total, " + autoFixed + " auto-fixed, " +
      info + " informational.";
    reviewCount.textContent = needsReview + " item(s) need human review.";

    downloadsList.innerHTML = "";
    var downloads = job.downloads || {};
    Object.keys(downloads).forEach(function (key) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = downloads[key];
      a.textContent = "Download " + (ARTIFACT_LABELS[key] || key);
      li.appendChild(a);
      downloadsList.appendChild(li);
    });
  }
})();
