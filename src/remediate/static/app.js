(function () {
  "use strict";

  var form = document.getElementById("upload-form");
  var fileInput = document.getElementById("file-input");
  var selectedFile = document.getElementById("selected-file");
  var submitButton = document.getElementById("submit-button");
  var uploadError = document.getElementById("upload-error");

  var progressSection = document.getElementById("progress-section");
  var progressFilename = document.getElementById("progress-filename");
  var progressBar = document.getElementById("progress-bar");
  var progressBarFill = document.getElementById("progress-bar-fill");
  var progressStatus = document.getElementById("progress-status");
  var stageListItems = document.querySelectorAll("#stage-list li[data-stage]");

  var errorSection = document.getElementById("error-section");
  var errorMessage = document.getElementById("error-message");
  var errorHint = document.getElementById("error-hint");

  var resultsSection = document.getElementById("results-section");
  var reviewCount = document.getElementById("review-count");
  var statAutofixed = document.getElementById("stat-autofixed");
  var statInfo = document.getElementById("stat-info");
  var statTotal = document.getElementById("stat-total");
  var downloadsList = document.getElementById("downloads-list");

  var pollTimer = null;

  // Ordered to match pipeline.py's real stage sequence; anything reported
  // that isn't in this list (there shouldn't be) just skips the tracker.
  var STAGE_ORDER = ["extracting", "generating_html", "rendering_pdf", "building_report"];

  var STAGE_LABELS = {
    queued: "Queued",
    extracting: "Extracting document content",
    generating_html: "Generating accessible HTML",
    rendering_pdf: "Rendering tagged PDF",
    building_report: "Building compliance report",
    done: "Done",
    error: "Error"
  };

  // Download tiers: the tagged PDF is the deliverable; report.html is the
  // reviewer's follow-up work list; the rest are byproducts.
  var ARTIFACT_INFO = {
    pdf: {
      title: "Tagged PDF",
      desc: "The finished, WCAG 2.1 AA tagged document.",
      tier: "primary"
    },
    "report.html": {
      title: "Compliance report",
      desc: "Every auto-fix and every item flagged for review, in one page.",
      tier: "secondary"
    },
    html: {
      title: "Accessible HTML",
      desc: "The intermediate HTML the PDF was rendered from.",
      tier: "tertiary"
    },
    "report.json": {
      title: "Compliance report (JSON)",
      desc: "Machine-readable version of the same report.",
      tier: "tertiary"
    }
  };

  var ARTIFACT_ORDER = ["pdf", "report.html", "html", "report.json"];

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

  fileInput.addEventListener("change", function () {
    var file = fileInput.files[0];
    selectedFile.textContent = file ? "Selected: " + file.name : "";
  });

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
        resetStageList();
        progressSection.hidden = false;
        progressFilename.textContent = file.name;
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
        errorHint.textContent = "";
      });
  }

  function resetStageList() {
    stageListItems.forEach(function (li) {
      li.classList.remove("is-done", "is-active");
    });
  }

  function updateStageList(stage) {
    var currentIndex = STAGE_ORDER.indexOf(stage);
    stageListItems.forEach(function (li) {
      var stepIndex = STAGE_ORDER.indexOf(li.getAttribute("data-stage"));
      li.classList.remove("is-done", "is-active");
      if (stage === "done" || (currentIndex > -1 && stepIndex < currentIndex)) {
        li.classList.add("is-done");
      } else if (stepIndex === currentIndex) {
        li.classList.add("is-active");
      }
    });
  }

  // Best-effort extra guidance for the two documented rejection reasons
  // (spike/FINDINGS.md + extractors/pdf.py): scanned/image-only and
  // encrypted PDFs. Purely additive -- falls back to nothing if the
  // backend message doesn't match either case.
  function errorHintFor(message) {
    var lower = (message || "").toLowerCase();
    if (lower.indexOf("scanned") !== -1 || lower.indexOf("image-only") !== -1) {
      return "This looks like a scanned or image-only PDF with no extractable text. " +
        "Run it through OCR first, then upload the result.";
    }
    if (lower.indexOf("password") !== -1 || lower.indexOf("encrypt") !== -1) {
      return "Remove the password/encryption from the PDF, then upload it again.";
    }
    return "No changes were saved. Fix the issue above and upload again.";
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
      errorHint.textContent = errorHintFor(job.error);
      return;
    }

    var pct = Math.round((job.pct || 0) * 100);
    progressBar.setAttribute("aria-valuenow", String(pct));
    progressBarFill.style.width = pct + "%";
    updateStageList(job.stage);
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

    reviewCount.textContent = String(needsReview);
    statAutofixed.textContent = String(autoFixed);
    statInfo.textContent = String(info);
    statTotal.textContent = String(total);

    downloadsList.innerHTML = "";
    var downloads = job.downloads || {};
    var keys = ARTIFACT_ORDER.filter(function (key) {
      return Object.prototype.hasOwnProperty.call(downloads, key);
    });
    // Any unexpected artifact key still shows up, just after the known ones.
    Object.keys(downloads).forEach(function (key) {
      if (keys.indexOf(key) === -1) {
        keys.push(key);
      }
    });

    keys.forEach(function (key) {
      var info = ARTIFACT_INFO[key] || { title: key, desc: "", tier: "tertiary" };
      var li = document.createElement("li");
      li.className = "tier-" + info.tier;

      var row = document.createElement("div");
      row.className = "download-label";

      var title = document.createElement("span");
      title.className = "download-title";
      title.textContent = info.title;
      row.appendChild(title);

      var a = document.createElement("a");
      a.href = downloads[key];
      a.textContent = "Download";
      row.appendChild(a);

      li.appendChild(row);

      if (info.desc) {
        var desc = document.createElement("p");
        desc.className = "download-desc";
        desc.textContent = info.desc;
        li.appendChild(desc);
      }

      downloadsList.appendChild(li);
    });
  }
})();
