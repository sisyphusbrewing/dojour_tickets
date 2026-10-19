// Sisyphus photo booth. See README.md for the hardware and setup.
(function () {
  var SUPABASE_URL = "https://idsdwkubqnavkazlteis.supabase.co";
  var SUPABASE_KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb";
  var EXPERIENCE = "booth";
  var SHOTS = 4, COUNT_FROM = 3;
  var IDLE_MS = 60000;      // any screen drops back to the start after this
  var DONE_MS = 15000;      // "printing" message stays up this long

  var sb = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
  var $ = function (id) { return document.getElementById(id); };
  var video = $("cam");

  // ---------- Settings kept on this machine ----------
  function store(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; }
  }
  var params = new URLSearchParams(location.search);
  if (params.get("key")) {
    store("booth_key", params.get("key"));
    params.delete("key");
    history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params : ""));
  }
  function deviceKey() { return store("booth_key") || ""; }

  // ---------- Screens ----------
  var current = "attract", idleTimer = null, pass = null;
  function show(id) {
    ["attract", "email", "hello", "shoot", "review", "msg"].forEach(function (s) { $(s).classList.toggle("hidden", s !== id); });
    $("shade").classList.toggle("hidden", id === "shoot");
    current = id;
    poke();
  }
  function poke() {
    clearTimeout(idleTimer);
    if (current === "attract" || current === "shoot") return;
    idleTimer = setTimeout(function () {
      if (current === "review") printStrips(); else reset();
    }, IDLE_MS);
  }
  document.addEventListener("pointerdown", poke, true);
  function reset() { pass = null; typed = ""; renderTyped(); show("attract"); }

  function message(band, title, text, bad, ms) {
    $("msgBand").textContent = band;
    $("msgTitle").textContent = title;
    $("msgText").textContent = text || "";
    $("msg").classList.toggle("bad", !!bad);
    show("msg");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(reset, ms || 7000);
  }

  // ---------- Camera ----------
  async function startCamera() {
    var want = store("booth_camera");
    var constraints = { audio: false, video: { width: { ideal: 1920 }, height: { ideal: 1080 } } };
    if (want) constraints.video.deviceId = { exact: want };
    try {
      if (video.srcObject) video.srcObject.getTracks().forEach(function (t) { t.stop(); });
      video.srcObject = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (e) {
      if (want) { store("booth_camera", ""); return startCamera(); }
      message("Booth", "No camera.", "Plug the camera in, then tap the top-right corner five times for settings.", true, 600000);
    }
  }

  // ---------- Ticket QR scanning (only while waiting) ----------
  var qrCanvas = document.createElement("canvas"), qrCtx = qrCanvas.getContext("2d", { willReadFrequently: true });
  var detector = ("BarcodeDetector" in window) ? new BarcodeDetector({ formats: ["qr_code"] }) : null;
  var lastCode = "", lastCodeAt = 0, busy = false;
  async function scanTick() {
    if (current === "attract" && !busy && video.videoWidth) {
      var code = null;
      try {
        if (detector) {
          var found = await detector.detect(video);
          if (found.length) code = found[0].rawValue;
        } else {
          var w = 640, h = Math.round(video.videoHeight * w / video.videoWidth);
          qrCanvas.width = w; qrCanvas.height = h;
          qrCtx.drawImage(video, 0, 0, w, h);
          var hit = jsQR(qrCtx.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: "dontInvert" });
          if (hit) code = hit.data;
        }
      } catch (e) { /* keep scanning */ }
      if (code && !(code === lastCode && Date.now() - lastCodeAt < 8000)) {
        lastCode = code; lastCodeAt = Date.now();
        unlock(code);
      }
    }
    setTimeout(scanTick, detector ? 150 : 250);
  }

  // ---------- Unlock ----------
  var REASONS = {
    no_ticket: ["Hmm.", "No ticket for tonight on that. Try the email you bought with, or ask the door. They know everything."],
    used: ["Already had your go.", "One per ticket. Sisyphus would push the boulder again. You can't. Enjoy the show."],
    key: ["Booth isn't set up.", "Staff: open the booth with its setup link."],
    closed: ["Booth's closed.", "Back soon."]
  };
  async function unlock(code) {
    if (busy) return;
    busy = true;
    message("Checking", "One sec.", "", false, 20000);
    var res = await sb.rpc("exp_scan", { p_key: deviceKey(), p_experience: EXPERIENCE, p_code: code });
    busy = false;
    var r = res.data;
    if (res.error || !r) return message("Booth", "Something hiccuped.", "Try again in a moment.", true);
    if (!r.ok) {
      var why = REASONS[r.reason] || REASONS.no_ticket;
      return message("Photo Booth", why[0], why[1], true, 8000);
    }
    pass = r;
    $("helloShow").textContent = r.show_title;
    $("helloName").textContent = r.name ? "Hi, " + r.name + "." : "You're in.";
    $("helloLeft").textContent = r.left > 1
      ? "Your order has " + r.left + " strips left. Pick how many after the photos."
      : "One strip on this ticket.";
    show("hello");
  }

  // ---------- Email keyboard ----------
  var typed = "";
  var ROWS = [
    "1234567890".split(""),
    "qwertyuiop".split(""),
    "asdfghjkl".split("").concat(["@"]),
    "zxcvbnm".split("").concat([".", "_", "-"]),
    ["@gmail.com", "@icloud.com", "@yahoo.com", "@hotmail.com", ".com"],
    ["Back", "Clear", "⌫", "Go"]
  ];
  function renderTyped() { $("typed").textContent = typed; }
  ROWS.forEach(function (row) {
    var r = document.createElement("div");
    r.className = "kb-row";
    row.forEach(function (k) {
      var b = document.createElement("button");
      b.className = "key" + (k.length > 1 ? " wide" : "") + (k === "Go" ? " go" : "");
      b.textContent = k;
      b.addEventListener("click", function () {
        if (k === "⌫") typed = typed.slice(0, -1);
        else if (k === "Clear") typed = "";
        else if (k === "Back") return reset();
        else if (k === "Go") { if (typed.indexOf("@") > 0 || typed === "test") unlock(typed); return; }
        else typed += k;
        renderTyped();
      });
      r.appendChild(b);
    });
    $("kb").appendChild(r);
  });
  $("toEmail").addEventListener("click", function () { typed = ""; renderTyped(); show("email"); });

  // ---------- Shooting ----------
  var frames = [], retakes = 0;
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var NOTES = ["Photo 1 of 4", "Photo 2. Do something.", "Photo 3. Weirder.", "Last one. Make it count."];

  function grab() {
    // Crop the frame to 3:2 from the middle, mirrored like the preview.
    var vw = video.videoWidth, vh = video.videoHeight, ratio = 3 / 2;
    var sw = vw, sh = Math.round(vw / ratio);
    if (sh > vh) { sh = vh; sw = Math.round(vh * ratio); }
    var c = document.createElement("canvas");
    c.width = 1080; c.height = 720;
    var x = c.getContext("2d");
    x.translate(c.width, 0); x.scale(-1, 1);
    x.drawImage(video, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, c.width, c.height);
    return c;
  }

  async function shoot() {
    frames = [];
    show("shoot");
    var dots = $("dots").children;
    for (var i = 0; i < SHOTS; i++) {
      for (var d = 0; d < SHOTS; d++) dots[d].classList.toggle("on", d < i);
      $("shotNote").textContent = NOTES[i];
      for (var n = COUNT_FROM; n > 0; n--) { $("count").textContent = n; await wait(900); }
      $("count").textContent = "";
      frames.push(grab());
      $("flash").classList.add("go");
      await wait(80);
      $("flash").classList.remove("go");
      await wait(i < SHOTS - 1 ? 900 : 500);
    }
    dots[SHOTS - 1].classList.add("on");
    await review();
  }

  // ---------- The strip ----------
  var C = { bg: "#2b2929", slate: "#4a6c86", white: "#ffffff", muted: "#d9d6d6", gray: "#918f90" };
  function fitFont(x, text, weight, size, family, max) {
    do { x.font = weight + " " + size + "px " + family; size -= 2; } while (x.measureText(text).width > max && size > 14);
  }
  function drawStrip() {
    var W = 600, H = 1800, pad = 30, fw = 540, fh = 360, gap = 18;
    var c = document.createElement("canvas");
    c.width = W; c.height = H;
    var x = c.getContext("2d");
    x.fillStyle = C.bg; x.fillRect(0, 0, W, H);
    frames.forEach(function (f, i) { x.drawImage(f, pad, pad + i * (fh + gap), fw, fh); });

    var head = "'Josefin Sans', 'Century Gothic', sans-serif", body = "Assistant, 'Segoe UI', sans-serif";
    var title = (pass && pass.show_title || "Sisyphus").toUpperCase();
    x.textAlign = "center"; x.textBaseline = "middle";

    // Show name on a tilted slate band with white rules, as on the menus.
    if ("letterSpacing" in x) x.letterSpacing = "4px";
    fitFont(x, title, 700, 34, head, 440);
    var bw = Math.min(x.measureText(title).width + 56, 540), bh = 58, by = 1590;
    x.save();
    x.translate(W / 2, by); x.rotate(-1.5 * Math.PI / 180);
    x.fillStyle = C.white;
    x.fillRect(-bw / 2, -bh / 2 - 9, bw, 3); x.fillRect(-bw / 2, bh / 2 + 6, bw, 3);
    x.fillStyle = C.slate; x.fillRect(-bw / 2, -bh / 2, bw, bh);
    x.fillStyle = C.white; x.fillText(title, 0, 3);
    x.restore();

    if ("letterSpacing" in x) x.letterSpacing = "2px";
    x.fillStyle = C.muted; x.font = "600 26px " + body;
    x.fillText(pass && pass.show_date || "", W / 2, 1662);
    if ("letterSpacing" in x) x.letterSpacing = "10px";
    x.fillStyle = C.white; x.font = "700 46px " + head;
    x.fillText("SISYPHUS", W / 2 + 5, 1722);
    if ("letterSpacing" in x) x.letterSpacing = "0px";
    x.fillStyle = C.gray; x.font = "italic 400 21px " + body;
    x.fillText("One must imagine Sisyphus happy.", W / 2, 1770);
    return c;
  }
  function drawSheet(strip) {
    // 4x6 at 300 dpi: the strip twice, side by side, for the printer's 2-inch cut.
    var c = document.createElement("canvas");
    c.width = 1200; c.height = 1800;
    var x = c.getContext("2d");
    x.drawImage(strip, 0, 0); x.drawImage(strip, 600, 0);
    return c;
  }

  var stripCanvas = null, wantCount = 1;
  async function review() {
    await document.fonts.ready;
    stripCanvas = drawStrip();
    $("stripPreview").src = stripCanvas.toDataURL("image/jpeg", 0.9);
    var max = Math.max(1, Math.min(pass.left || 1, 6));
    wantCount = Math.min(2, max);
    var pick = $("countPick");
    pick.innerHTML = "";
    for (var n = 1; n <= max; n++) {
      (function (n) {
        var b = document.createElement("button");
        b.textContent = n;
        b.className = n === wantCount ? "on" : "";
        b.addEventListener("click", function () {
          wantCount = n;
          Array.prototype.forEach.call(pick.children, function (el, i) { el.className = i + 1 === n ? "on" : ""; });
        });
        pick.appendChild(b);
      })(n);
    }
    $("countNote").textContent = max > 1 ? "One for everyone in the picture." : "This one's yours.";
    pick.classList.toggle("hidden", max < 2);
    $("retakeBtn").classList.toggle("hidden", retakes >= 1);
    show("review");
  }

  var printing = false;
  async function printStrips() {
    if (printing || !pass) return;
    printing = true;
    clearTimeout(idleTimer);
    var res = await sb.rpc("exp_redeem", { p_key: deviceKey(), p_pass: pass.pass, p_uses: wantCount });
    var granted = res.data || 0;
    if (res.error || !granted) {
      printing = false;
      return message("Photo Booth", "That pass timed out.", "Scan your ticket again to print.", true);
    }
    var sheets = Math.ceil(granted / 2);
    var url = drawSheet(stripCanvas).toDataURL("image/jpeg", 0.95);
    var box = $("print");
    box.innerHTML = "";
    var loads = [];
    for (var i = 0; i < sheets; i++) {
      var img = new Image();
      loads.push(new Promise(function (r) { img.onload = r; img.onerror = r; }));
      img.src = url;
      box.appendChild(img);
    }
    await Promise.all(loads);
    message("Printing", granted === 1 ? "Your strip is printing." : granted + " strips printing.",
            "They drop out of the slot in a few seconds. Don't shake them, that's Polaroids.", false, DONE_MS);
    await wait(300);
    window.print();          // silent with Chrome --kiosk-printing
    printing = false;
    pass = null; retakes = 0;
  }

  $("startShoot").addEventListener("click", function () { retakes = 0; shoot(); });
  $("retakeBtn").addEventListener("click", function () { retakes++; shoot(); });
  $("printBtn").addEventListener("click", printStrips);

  // ---------- Staff settings: five taps in the top-right corner ----------
  var taps = 0, tapTimer = null;
  $("corner").addEventListener("click", function () {
    taps++; clearTimeout(tapTimer);
    tapTimer = setTimeout(function () { taps = 0; }, 1500);
    if (taps >= 5) { taps = 0; openStaff(); }
  });
  async function openStaff() {
    var sel = $("camSel"), devices = await navigator.mediaDevices.enumerateDevices();
    sel.innerHTML = "";
    devices.filter(function (d) { return d.kind === "videoinput"; }).forEach(function (d, i) {
      var o = document.createElement("option");
      o.value = d.deviceId; o.textContent = d.label || ("Camera " + (i + 1));
      o.selected = d.deviceId === store("booth_camera");
      sel.appendChild(o);
    });
    $("keyIn").value = deviceKey();
    $("staff").classList.remove("hidden");
  }
  $("staffSave").addEventListener("click", function () {
    store("booth_camera", $("camSel").value);
    store("booth_key", $("keyIn").value.trim());
    $("staff").classList.add("hidden");
    startCamera();
  });
  $("staffClose").addEventListener("click", function () { $("staff").classList.add("hidden"); });
  $("staffTest").addEventListener("click", function () { $("staff").classList.add("hidden"); unlock("test"); });

  // Keep the screen awake.
  async function stayAwake() { try { await navigator.wakeLock.request("screen"); } catch (e) { /* not supported */ } }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) stayAwake(); });

  startCamera().then(scanTick);
  stayAwake();
  reset();
  if (!deviceKey()) message("Booth", "Booth isn't set up.", "Staff: open the booth with its setup link.", true, 600000);
})();
