# PixelVeil — v1 Build Roadmap

## 1. What We're Building

A **Windows desktop app** called **PixelVeil**. User drags in an already-recorded video file (from OBS, Loom, QuickTime, or anything else — no change to their recording workflow). The app processes it **entirely locally, nothing uploaded**, and outputs a version with:

- Faces automatically detected and blurred
- On-screen PII text (emails, phone numbers, card numbers, IPs) automatically detected via OCR and either:
  - **Blurred/boxed**, or
  - **Replaced with realistic fake placeholder data** ("Test User 1," "john.doe@example.com") — this is PixelVeil's core differentiator, since no existing competitor does this for video
- User-defined static zones (drag-select a screen region once — e.g. "always cover this CRM panel" — applied for the whole video)

No manual editing, no timeline, no re-checking frame by frame. Press process, get a clean file.

**Explicitly NOT in v1:** selective "keep this face unblurred," age-based filtering, live/in-recording redaction, browser extension, web/cloud version, audio or document redaction, editing UI, batch processing (single file at a time for now).

---

## 2. Target Buyer

QA engineers and customer support teams who record bug-report and demo videos containing real customer data (dashboards, tickets, CRM panels) and need it clean before sharing internally or with vendors.

---

## 3. USP

> "Don't just black out sensitive data — replace it with realistic placeholder text, so your videos stay watchable. Face blur and PII text detection, fully local, nothing uploaded."

This is a verified gap: every competitor found in research does blur/pixelate/box only, and does either faces (video tools) or PII text (image/screenshot tools) — never both together, and never with fake-data replacement, on video.

---

## 4. Tech Stack

| Component | Choice | Why |
|---|---|---|
| Core language | **Python** | Deepest, most AI-agent-friendly ecosystem for the actual hard problems here (CV, OCR) |
| Face detection | `face_recognition` (dlib-based) or `mediapipe` | Mature, well-documented, easy to prompt an agent to implement correctly |
| OCR | `pytesseract` (Tesseract OCR) | Most widely documented Python OCR library, good agent support |
| PII pattern matching | Python `re` (regex) for emails/phones/cards/IPs | Simple, reliable, no ML needed for structured data |
| Video I/O & frame processing | `opencv-python` (`cv2`) | Standard for frame-by-frame video read/write/draw operations |
| GUI (v1) | `Tkinter` (built into Python) or `PyQt5` if Tkinter feels too limited | Single-language stack, no Electron/Node bridge complexity |
| Packaging (later, once core works) | `PyInstaller` → single Windows `.exe` | Standard path from Python script to distributable Windows app |
| Payments (once monetizing) | Stripe Checkout + a simple license-key check | Self-serve, no sales calls needed |

**Build philosophy for this phase:** get the core processing pipeline (face blur + OCR PII detection + placeholder replacement) working correctly as plain Python scripts first — no GUI polish, no packaging — before wrapping it in any interface. Prove the "does it actually redact everything it claims to" question before spending time on UX.

---

## 5. Core Pipeline (build order)

1. Read video file frame-by-frame with OpenCV.
2. Run face detection on each frame (or every Nth frame for speed) → draw blur over detected face regions.
3. Run OCR on each frame (or sampled frames) → get text + bounding boxes.
4. Regex-match OCR text against PII patterns (email, phone, card number, IP).
5. For each match: either draw a blur/box, or draw a solid box with rendered placeholder text on top, based on user's selected mode.
6. Apply any user-marked static zones to every frame regardless of detection.
7. Write processed frames back out to a new video file.
8. Wrap steps 1-7 behind a minimal GUI: file picker, mode toggle (blur vs. fake-data), zone-marking tool, "Process" button, progress bar, done.

**Definition of done for v1:** drag in a test video with a visible face and a fake typed email/phone number → output video has both handled correctly, with zero manual editing needed afterward.

---

## 6. Pricing (Freemium)

| Tier | Price | Includes |
|---|---|---|
| Free | $0 | Limited video length/count per month (e.g. 3 videos, max 5 min each), blur mode only |
| Pro | $12–15/month | Unlimited videos, fake-data replacement mode, custom static zones saved as presets |

---

## 7. Marketing / Getting First Users

1. **Validate before/during build**: post the concept (short demo GIF once basic pipeline works) in r/QualityAssurance, r/CustomerSuccess, r/sysadmin, Indie Hackers — gauge real interest before going all-in on polish.
2. **Product Hunt launch** once v1 is stable and has a working demo.
3. **Community participation** (not ads) in QA/support tooling spaces — Zendesk, Intercom, Jira-adjacent communities.
4. **SEO content**: "how to blur sensitive info in screen recordings," "redact PII from bug report videos" — currently low-competition search terms.
5. **Twitter/X build-in-public**: the fake-data-replacement feature is visually demo-able — show before/after clips, this is inherently shareable content.

---

## 8. Competitors (confirmed via research)

| Competitor | Covers | Gap PixelVeil fills |
|---|---|---|
| blurfacefree, FaceHide, Blurit, VideoPilot | Face blur in video, local/free | None do OCR-based PII text detection on video |
| blur-face.com, BlurShot, ToolHaven | PII text detection, local/free | Image/screenshot only, not video |
| VIDIZMO, CaseGuard, SecureRedact | Enterprise compliance redaction (video, audio, docs) | Enterprise-priced, post-processing editors, not built for prosumer/indie QA teams |

**No existing tool combines face blur + OCR PII detection + fake-data replacement on video, locally, for this price point.**

---

## 9. Realistic Earnings Expectation

- **Year 1, if validated and marketed consistently**: $500–$3,000 MRR (roughly 30–200 paying users at $12–15/mo)
- **18–24 months, if it gains traction in QA/support circles**: $5,000–$15,000 MRR
- **Worst case**: niche too small or marketing doesn't land, $0–500 MRR — this is why community validation happens alongside the build, not after

This is a solo indie income project, not a venture-scale business. Treat it as a real "start of something," not a lottery ticket.

---

## 9b. v2 Milestone — Child-Only Face Detection Mode

**Status:** Confirmed for v2, after the base v1 pipeline (all-face blur + OCR PII detection) is working and validated. Not in v1 scope.

**What it does:** A separate mode, selectable alongside "Blur all faces" — user picks one or the other per run:
- **"Blur all faces"** (existing v1 behavior) — every detected face is blurred.
- **"Blur children only"** (new, v2) — face detection runs as normal, then an age-estimation pass runs on each detected face; only faces estimated as under the (padded-upward) age threshold get blurred, adult faces stay visible.

**Design principle — non-negotiable:** when the age model's confidence is low, default to treating the face as a child and blur it. Over-blurring an adult is an acceptable cosmetic miss; failing to blur an actual child is not acceptable. Threshold should be padded upward (e.g. treat anything estimated under ~20 as "blur," not a hard cutoff at 18) to absorb model error on the low-confidence boundary.

**Explicitly dropped:** female-only / gender-based face filtering — no clear safety justification for the added bias/accuracy risk, cut from scope entirely.

**Tech addition needed:** an age-estimation model on top of the existing face-detection step (e.g. an age-gender ONNX model or InsightFace's age branch), run only on already-detected faces — no new detection pipeline needed, just an added classification pass.

---

## 10. Immediate Next Steps

1. Set up Python environment: `opencv-python`, `face_recognition` (or `mediapipe`), `pytesseract` (+ Tesseract binary installed), `pillow`.
2. Build the core pipeline as a plain script (no GUI) — test on 2-3 sample videos with fake PII planted in them.
3. Once face blur + PII detection + placeholder replacement all work correctly on test videos, wrap in a minimal Tkinter GUI.
4. Post progress + a demo clip in target communities to gauge real interest before investing in packaging/polish/payments.
