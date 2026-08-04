// PixelVeil test harness — Upload screen behaviour (docs/design.md Screen 1).
// File picker + drag/drop upload, first-frame extraction display, click-drag
// static-zone drawing, and per-zone deletion. Display->video pixel conversion
// is done server-side (/zone) so the authoritative mapping always uses the
// real video dimensions; this file only captures display-space coordinates.
//
// Later Phase 3 tasks own Processing/Results/Settings behaviour and the real
// pipeline wiring — Process Video here only hits a controlled placeholder.

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

    // Preserve whatever mode was selected before the file was chosen.
    if (selectedMode() !== "blur") syncMode();
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
  function syncMode() {
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

  // --- process (placeholder) ----------------------------------------------
  processBtn.addEventListener("click", function () {
    if (!upload) return;
    processStatus.textContent = "Submitting…";
    fetch("/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: upload.id }),
    })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
      .then(function (res) {
        // 501 is expected here — pipeline wiring is the next task.
        processStatus.textContent =
          (res.j.message || "Submitted.") +
          " (mode: " + res.j.mode + ", zones: " + res.j.num_zones + ")";
      })
      .catch(function () { processStatus.textContent = "Process request failed."; });
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
