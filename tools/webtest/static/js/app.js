// PixelVeil test harness — Upload screen behaviour (docs/design.md Screen 1).
// File picker + drag/drop upload, first-frame extraction display, click-drag
// static-zone drawing, and per-zone deletion. Display->video pixel conversion
// is done server-side (/zone) so the authoritative mapping always uses the
// real video dimensions; this file only captures display-space coordinates.
//
// Later Phase 3 tasks own Processing/Results/Settings behaviour and the real
// pipeline wiring — Process Video here only starts the background job.

(function () {
  "use strict";

  // Only the Upload screen has these elements; bail on the other pages.
  var dropzone = document.getElementById("dropzone");
  if (!dropzone) return;

  var fileInput = document.getElementById("fileInput");
  var uploadError = document.getElementById("uploadError");
  var uploadInfo = document.getElementById("uploadInfo");
  var zoneEditor = document.getElementById("zoneEditor");
  var zonePlaceholder = document.getElementById("zonePlaceholder");
  var canvas = document.getElementById("frameCanvas");
  var ctx = canvas.getContext("2d");
  var zoneList = document.getElementById("zoneList");
  var zoneEmpty = document.getElementById("zoneEmpty");
  var processBtn = document.getElementById("processBtn");
  var processStatus = document.getElementById("processStatus");

  var MAX_CANVAS_W = 640; // fit the frame into the single-column layout

  // --- session state -------------------------------------------------------
  var upload = null;   // {id, width, height}
  var baseImage = null;
  // Each zone: {disp:{x,y,w,h} in canvas px, video:[x,y,w,h] in video px}.
  var zones = [];
  var drag = null;     // {x0,y0,x1,y1} during a click-drag

  // --- helpers -------------------------------------------------------------
  function showError(msg) {
    uploadError.textContent = msg;
    uploadError.hidden = false;
  }
  function clearError() {
    uploadError.hidden = true;
    uploadError.textContent = "";
  }
  function selectedMode() {
    var el = document.querySelector('input[name="mode"]:checked');
    return el ? el.value : "blur";
  }

  function canvasPos(evt) {
    // Map a pointer event to canvas backing-store coordinates, correct even if
    // CSS has scaled the canvas element down.
    var r = canvas.getBoundingClientRect();
    var sx = canvas.width / r.width;
    var sy = canvas.height / r.height;
    return { x: (evt.clientX - r.left) * sx, y: (evt.clientY - r.top) * sy };
  }

  function redraw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (baseImage) ctx.drawImage(baseImage, 0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 2;
    zones.forEach(function (z) {
      ctx.strokeStyle = "#2563EB";
      ctx.fillStyle = "rgba(37,99,235,0.15)";
      ctx.fillRect(z.disp.x, z.disp.y, z.disp.w, z.disp.h);
      ctx.strokeRect(z.disp.x, z.disp.y, z.disp.w, z.disp.h);
    });
    if (drag) {
      var x = Math.min(drag.x0, drag.x1);
      var y = Math.min(drag.y0, drag.y1);
      var w = Math.abs(drag.x1 - drag.x0);
      var h = Math.abs(drag.y1 - drag.y0);
      ctx.strokeStyle = "#111111";
      ctx.setLineDash([5, 3]);
      ctx.strokeRect(x, y, w, h);
      ctx.setLineDash([]);
    }
  }

  function renderZoneList() {
    zoneList.innerHTML = "";
    zones.forEach(function (z, i) {
      var li = document.createElement("li");
      var v = z.video;
      var label = document.createElement("span");
      label.textContent =
        "Zone " + (i + 1) + " — x:" + v[0] + " y:" + v[1] +
        " w:" + v[2] + " h:" + v[3] + " (video px)";
      var del = document.createElement("button");
      del.type = "button";
      del.className = "btn btn-small";
      del.textContent = "Delete";
      del.addEventListener("click", function () { deleteZone(i); });
      li.appendChild(label);
      li.appendChild(del);
      zoneList.appendChild(li);
    });
    zoneEmpty.hidden = zones.length > 0;
  }

  // --- upload --------------------------------------------------------------
  function looksLikeVideo(file) {
    if (file.type && file.type.indexOf("video/") === 0) return true;
    return /\.(mp4|mov|mkv|avi|webm|m4v)$/i.test(file.name || "");
  }

  function handleFile(file) {
    clearError();
    if (!file) return;
    if (!looksLikeVideo(file)) {
      showError("That doesn't look like a video file. Choose an mp4/mov/mkv/avi/webm.");
      return;
    }
    var fd = new FormData();
    fd.append("video", file);
    uploadInfo.hidden = false;
    uploadInfo.textContent = "Uploading " + file.name + "…";
    fetch("/upload", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          uploadInfo.hidden = true;
          showError(res.j.error || "Upload failed.");
          return;
        }
        onUploaded(res.j, file.name);
      })
      .catch(function () {
        uploadInfo.hidden = true;
        showError("Upload failed (network or server error).");
      });
  }

  function onUploaded(state, name) {
    upload = { id: state.id, width: state.width, height: state.height };
    zones = [];
    renderZoneList();
    uploadInfo.hidden = false;
    uploadInfo.textContent =
      name + " — " + state.width + "×" + state.height + " px. Draw zones below.";

    baseImage = new Image();
    baseImage.onload = function () {
      var scale = Math.min(1, MAX_CANVAS_W / state.width);
      canvas.width = Math.round(state.width * scale);
      canvas.height = Math.round(state.height * scale);
      redraw();
    };
    baseImage.src = state.frame_url + "?t=" + Date.now();

    zonePlaceholder.hidden = true;
    zoneEditor.hidden = false;
    processBtn.disabled = false;
    processStatus.textContent = "Ready to process.";

    // Always sync the selected mode to the server after a new upload so the
    // server's per-uid mode is authoritative even if it stayed on "blur"
    // (the server default) — prevents a stale fake_data mode from a prior
    // upload carrying over into this new uid's job.
    syncMode();
  }

  // --- zone drawing --------------------------------------------------------
  canvas.addEventListener("mousedown", function (e) {
    if (!upload) return;
    var p = canvasPos(e);
    drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
  });
  canvas.addEventListener("mousemove", function (e) {
    if (!drag) return;
    var p = canvasPos(e);
    drag.x1 = p.x;
    drag.y1 = p.y;
    redraw();
  });
  window.addEventListener("mouseup", function () {
    if (!drag) return;
    var d = drag;
    drag = null;
    redraw();
    var x = Math.min(d.x0, d.x1);
    var y = Math.min(d.y0, d.y1);
    var w = Math.abs(d.x1 - d.x0);
    var h = Math.abs(d.y1 - d.y0);
    if (w < 3 || h < 3) return; // ignore stray clicks
    var dispRect = { x: x, y: y, w: w, h: h };
    fetch("/zone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: upload.id,
        rect: dispRect,
        display: { w: canvas.width, h: canvas.height },
      }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { showError(res.j.error || "Could not add zone."); return; }
        zones.push({ disp: dispRect, video: res.j.video_rect });
        renderZoneList();
        redraw();
      });
  });

  function deleteZone(index) {
    if (!upload) return;
    fetch("/zone/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: upload.id, index: index }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { showError(res.j.error || "Could not delete zone."); return; }
        zones.splice(index, 1);
        renderZoneList();
        redraw();
      });
  }

  // --- mode ----------------------------------------------------------------
  function syncModeUI() {
    // Show/hide the explanatory note for the fake_data two-pass behaviour.
    // Face anonymization card stays visible for BOTH modes — faces are blurred
    // in fake_data mode too.
    var isBlur = (selectedMode() === "blur");
    var fakeNote = document.getElementById("fakeDataNote");
    if (fakeNote) fakeNote.style.display = isBlur ? "none" : "";
  }

  function syncMode() {
    syncModeUI(); // always update note visibility immediately
    if (!upload) return;
    fetch("/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: upload.id, mode: selectedMode() }),
    });
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('input[name="mode"]'),
    function (el) { el.addEventListener("change", syncMode); }
  );

  // Run on page load so the note visibility matches the initial radio state.
  syncModeUI();

  // --- process (start background job, then go to the Processing screen) ----
  processBtn.addEventListener("click", function () {
    if (!upload) return;
    processBtn.disabled = true; // prevent a double-start from a double-click
    processStatus.textContent = "Starting\u2026";
    // Include mode at click-time so the server uses the exact current radio
    // value, regardless of whether /mode was called previously. This is the
    // authoritative source — eliminates any stale-sync race condition.
    fetch("/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: upload.id, mode: selectedMode() }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, j: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          // 409 = a job is already running; other codes = real error.
          processStatus.textContent = res.j.error || "Could not start processing.";
          processBtn.disabled = false;
          return;
        }
        // Navigate to the live Processing screen for this job.
        window.location.href = "/processing?job=" + encodeURIComponent(upload.id);
      })
      .catch(function () {
        processStatus.textContent = "Process request failed.";
        processBtn.disabled = false;
      });
  });

  // --- wiring: file picker + drag/drop ------------------------------------
  dropzone.addEventListener("click", function () { fileInput.click(); });
  dropzone.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files[0]) handleFile(fileInput.files[0]);
  });
  ["dragenter", "dragover"].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone.addEventListener("drop", function (e) {
    var dt = e.dataTransfer;
    if (dt && dt.files && dt.files[0]) handleFile(dt.files[0]);
  });
})();

// ===========================================================================
// Processing screen (docs/design.md Screen 2). Polls /job/<uid> for live
// progress, per-stage status, and the technical log. Bails on other pages.
// The live current-frame preview / detection-box overlay is a later task.
// ===========================================================================
(function () {
  "use strict";

  var root = document.getElementById("processingRoot");
  if (!root) return; // not the Processing page

  var jobId = root.getAttribute("data-job-id");
  var progressFill = document.getElementById("progressFill");
  var progressText = document.getElementById("progressText");
  var stageRows = document.getElementById("stageRows");
  var logPanel = document.getElementById("logPanel");
  var doneMsg = document.getElementById("processingDone");
  var previewImage = document.getElementById("previewImage");
  var previewPlaceholder = document.getElementById("previewPlaceholder");

  if (!jobId) {
    progressText.textContent = "No active job — start one from the Upload screen.";
    return;
  }

  var POLL_MS = 500;
  var logPinnedToBottom = true;
  var lastPreviewSeq = -1;

  // Refresh the diagnostic frame image only when the job reports a NEW preview
  // (seq changed). The image is fetched from its own endpoint — never embedded
  // in the /job JSON — and the seq doubles as a cache-buster.
  function updatePreview(snap) {
    if (!previewImage || !snap.has_preview) return;
    if (snap.preview_seq === lastPreviewSeq) return;
    lastPreviewSeq = snap.preview_seq;
    previewImage.src =
      "/job/" + encodeURIComponent(jobId) + "/preview?seq=" + snap.preview_seq;
    previewImage.style.display = "block";
    if (previewPlaceholder) previewPlaceholder.style.display = "none";
  }

  // Let the user scroll up to inspect a moment without being yanked back down.
  logPanel.addEventListener("scroll", function () {
    var atBottom = logPanel.scrollHeight - logPanel.scrollTop - logPanel.clientHeight < 4;
    logPinnedToBottom = atBottom;
  });

  function renderStages(stages) {
    stageRows.innerHTML = "";
    stages.forEach(function (s) {
      var tr = document.createElement("tr");
      var name = document.createElement("td");
      name.textContent = s.name;
      var state = document.createElement("td");
      state.className = "state " + s.state;
      state.textContent = s.state;
      var detail = document.createElement("td");
      detail.textContent = s.detail;
      tr.appendChild(name);
      tr.appendChild(state);
      tr.appendChild(detail);
      stageRows.appendChild(tr);
    });
  }

  function render(snap) {
    progressFill.style.width = snap.percent + "%";
    // For a fake_data TELEA/NS comparison the job runs two sequential passes;
    // show which method (pass N/M) is currently processing so the two runs are
    // legible on one progress bar. A normal single-pass job shows no suffix.
    var passInfo = "";
    if (snap.num_passes && snap.num_passes > 1 && snap.status === "running") {
      passInfo = " · " + (snap.pass_label || "").toUpperCase() +
        " (pass " + ((snap.pass_index || 0) + 1) + "/" + snap.num_passes + ")";
    }
    progressText.textContent =
      "Frame " + snap.frame + " of " + (snap.total || "?") +
      " · " + snap.percent + "% · elapsed " + snap.elapsed + "s · " + snap.status +
      passInfo;

    renderStages(snap.stages);

    logPanel.textContent = (snap.log && snap.log.length)
      ? snap.log.join("\n")
      : "[--:--:--] waiting for output…";
    if (logPinnedToBottom) logPanel.scrollTop = logPanel.scrollHeight;

    updatePreview(snap);

    if (snap.status === "complete") {
      doneMsg.hidden = false;
      doneMsg.innerHTML =
        "Done. " + (snap.summary ? snap.summary.frames_processed + " frames, " +
        snap.summary.faces_blurred + " faces blurred. " : "") +
        '<a class="btn primary" href="/results?job=' +
        encodeURIComponent(jobId) + '">View results</a>';
    } else if (snap.status === "error") {
      doneMsg.hidden = false;
      doneMsg.className = "error-msg";
      doneMsg.textContent = "Processing failed: " + (snap.error || "unknown error");
    }
  }

  function poll() {
    fetch("/job/" + encodeURIComponent(jobId))
      .then(function (r) {
        if (!r.ok) throw new Error("job not found");
        return r.json();
      })
      .then(function (snap) {
        render(snap);
        if (snap.status === "running" || snap.status === "pending") {
          window.setTimeout(poll, POLL_MS);
        }
      })
      .catch(function () {
        progressText.textContent = "Lost contact with the job.";
      });
  }

  poll();
})();

// ===========================================================================
// Settings screen (docs/design.md Screen 4). Functional tuning: OCR sample
// rate, face-detection confidence, and the four PII regex patterns. Saving
// hits the /settings JSON API (server-side validation is authoritative); a
// newly started job then uses these values. Bails on other pages.
// ===========================================================================
(function () {
  "use strict";

  var root = document.getElementById("settingsRoot");
  if (!root) return; // not the Settings page

  var saveUrl = root.getAttribute("data-save-url");
  var resetUrl = root.getAttribute("data-reset-url");

  var ocrRate = document.getElementById("ocrRate");
  var faceConf = document.getElementById("faceConf");
  var faceConfValue = document.getElementById("faceConfValue");
  var saveBtn = document.getElementById("saveSettings");
  var resetBtn = document.getElementById("resetSettings");
  var feedback = document.getElementById("settingsFeedback");

  var PII_TYPES = ["EMAIL", "PHONE", "CARD", "IP"];

  // Keep the confidence read-out in sync while dragging the slider.
  faceConf.addEventListener("input", function () {
    faceConfValue.textContent = Number(faceConf.value).toFixed(2);
  });

  function showFeedback(msg, ok) {
    feedback.hidden = false;
    feedback.textContent = msg;
    feedback.className = "settings-feedback " + (ok ? "ok" : "error-msg");
  }

  // Reflect a settings dict (from the API) back into the form controls.
  function applyValues(s) {
    ocrRate.value = s.ocr_sample_rate;
    faceConf.value = s.face_min_confidence;
    faceConfValue.textContent = Number(s.face_min_confidence).toFixed(2);
    PII_TYPES.forEach(function (t) {
      var el = document.getElementById("pattern" + t);
      if (el && s.pii_patterns && s.pii_patterns[t] !== undefined) {
        el.value = s.pii_patterns[t];
      }
    });
  }

  function collectPatterns() {
    var patterns = {};
    PII_TYPES.forEach(function (t) {
      var el = document.getElementById("pattern" + t);
      if (el) patterns[t] = el.value;
    });
    return patterns;
  }

  saveBtn.addEventListener("click", function () {
    saveBtn.disabled = true;
    var body = {
      ocr_sample_rate: ocrRate.value,
      face_min_confidence: faceConf.value,
      pii_patterns: collectPatterns(),
    };
    fetch(saveUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          showFeedback(res.j.error || "Could not save settings.", false);
          return;
        }
        applyValues(res.j);
        showFeedback("Settings saved. The next run will use them.", true);
      })
      .catch(function () { showFeedback("Save request failed.", false); })
      .then(function () { saveBtn.disabled = false; });
  });

  resetBtn.addEventListener("click", function () {
    resetBtn.disabled = true;
    fetch(resetUrl, { method: "POST" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { showFeedback("Could not reset settings.", false); return; }
        applyValues(res.j);
        showFeedback("Settings reset to defaults.", true);
      })
      .catch(function () { showFeedback("Reset request failed.", false); })
      .then(function () { resetBtn.disabled = false; });
  });
})();

// ===========================================================================
// Upload page — Face anonymization controls. Auto-saves to /face-redaction
// whenever the user changes method or intensity. Bails on other pages.
// ===========================================================================
(function () {
  "use strict";

  var card = document.getElementById("faceRedactionCard");
  if (!card) return; // not the Upload page

  var blurRow    = document.getElementById("uploadBlurIntensityRow");
  var pixRow     = document.getElementById("uploadPixelateIntensityRow");
  var blurSelect = document.getElementById("uploadFaceBlurIntensity");
  var savedBadge = document.getElementById("faceRedactionSaved");

  var saveTimer = null;

  function currentMethod() {
    var el = document.querySelector('input[name="faceRedactionMethod"]:checked');
    return el ? el.value : "blur";
  }

  function syncRows() {
    var m = currentMethod();
    if (blurRow) blurRow.style.display = (m === "blur")     ? "" : "none";
    if (pixRow)  pixRow.style.display  = (m === "pixelate") ? "" : "none";
    // Keep disabled so the hidden select isn't accidentally read elsewhere.
    if (blurSelect) blurSelect.disabled = (m !== "blur");
  }

  function saveNow() {
    var m = currentMethod();
    var body = {
      face_redaction_method:   m,
      face_blur_intensity:     blurSelect ? blurSelect.value  : "medium",
      face_pixelate_intensity: "medium", // standard/ignored anyway
    };
    fetch("/face-redaction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) return;
        if (savedBadge) {
          savedBadge.style.display = "";
          clearTimeout(saveTimer);
          saveTimer = setTimeout(function () {
            savedBadge.style.display = "none";
          }, 2000);
        }
      })
      .catch(function () { /* network error — ignore */ });
  }

  // Wire method radios.
  Array.prototype.forEach.call(
    document.querySelectorAll('input[name="faceRedactionMethod"]'),
    function (el) {
      el.addEventListener("change", function () { syncRows(); saveNow(); });
    }
  );

  // Wire intensity selects.
  if (blurSelect) blurSelect.addEventListener("change", saveNow);

  // Set initial row visibility based on server-rendered checked state.
  syncRows();
})();

