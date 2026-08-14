# PixelVeil Architecture Decisions

This document records every major architectural decision with full justification.

### DEC-01: SCRFD-500M as sole detector (no YuNet, no MediaPipe in production)
**Decision**: Use SCRFD-500M only as the sole face detector.
**Reason**: Need a highly reliable, robust, and performant detector to form the foundation of the pipeline. YuNet is currently broken (ISSUE-010) and MediaPipe misses angled faces (ISSUE-002).
**Research evidence**: Phase 1 established SCRFD's superior WIDER FACE Hard AP. Local benchmark confirmed SCRFD CUDA ≈67 FPS, CPU ≈29.5 FPS.
**Alternative considered**: YuNet, MediaPipe, or a multi-model ensemble.
**Why alternative rejected**: YuNet is broken, MediaPipe provides poor coverage on angles, and an ensemble introduces unnecessary computational cost.
**Confidence**: HIGH — experimentally validated on PixelVeil.
**Open validation needed**: None for the core detector selection.

### DEC-02: Selective ROI inference instead of full-frame SAHI
**Decision**: Only run targeted high-resolution SCRFD on suspicious regions, NOT global tiling every frame.
**Reason**: Full-frame SAHI is too computationally expensive for the target hardware (GTX 1650).
**Research evidence**: Phase 2 established 5-tile SAHI multiplies GFLOPs by 5x. Phase 7 confirms GTX 1650 cannot sustain this.
**Alternative considered**: Full-frame SAHI every frame.
**Why alternative rejected**: Computationally infeasible on baseline target hardware.
**Confidence**: MEDIUM — literature-supported.
**Open validation needed**: ROI extraction cost on GTX 1650 must be benchmarked.

### DEC-03: Kalman Filter tracker replacing custom constant-velocity model
**Decision**: Replace current custom tracker with a proper Linear Kalman Filter with covariance tracking.
**Reason**: Current O(N!) branch-and-bound logic is a scalability bottleneck. Kalman Filter provides uncertainty estimation required for gap recovery.
**Research evidence**: Phase 4 recommends ByteTrack/OC-SORT style trackers with Kalman state.
**Alternative considered**: Keep the current custom tracker.
**Why alternative rejected**: Poor scalability and lacks the uncertainty state needed to properly execute gap recovery.
**Confidence**: HIGH — literature strongly supports Kalman for this use case.
**Open validation needed**: Parameter tuning for process/measurement noise matrices.

### DEC-04: Two-pass architecture (detection pass + offline recovery pass)
**Decision**: Pipeline will use two passes: Pass 1 does full-frame SCRFD + tracking. Pass 2 handles suspicious region recovery + gap filling.
**Reason**: Separating detection from recovery allows complex spatial and temporal recovery heuristics to run without bottlenecking the main tracker logic.
**Research evidence**: Phase 5/6 establish offline recovery needs future evidence. Phase 7 confirms recovery can run at slower FPS offline.
**Alternative considered**: Single-pass with inline recovery.
**Why alternative rejected**: Inline recovery complicates state management and slows down the primary sequential processing unnecessarily.
**Confidence**: MEDIUM — conceptually sound.
**Open validation needed**: Recovery pass cost and disk I/O overhead have not been benchmarked.

### DEC-05: Boundary-region scanning for brand-new face problem
**Decision**: On every frame, run low-cost boundary strip detection (edges of frame) to catch entering faces.
**Reason**: There is no deterministic CV signal to prove an object is present if it was never detected. Therefore, boundary scanning is the only proactive mechanism to catch faces as they enter before they fully materialize in the frame.
**Research evidence**: Phase 1 identified zero-padding artifacts causing edge failures. Phase 6 confirmed no reliable way to detect unseen faces retroactively without some forward signal.
**Alternative considered**: Periodic full-frame tiled inference, or image-driven suspicion.
**Why alternative rejected**: Full-frame tiled inference is too expensive; image-driven suspicion provides no reliable signal for never-detected faces.
**Confidence**: MEDIUM — boundary scanning is a reasonable approach.
**Open validation needed**: Parameters such as strip width and scan frequency are unvalidated.

### DEC-06: GSI-based mid-track gap interpolation (not RTS, not linear)
**Decision**: Use Gaussian-Smoothed Interpolation for mid-track gaps instead of RTS smoother or linear interpolation.
**Reason**: Motion of biological subjects (faces) is non-linear and noisy; linear interpolation fails on noise and RTS smoothers struggle with irregular motion.
**Research evidence**: Phase 5 found RTS fails on irregular biological motion. GSI models non-linear dynamics. Linear interpolation fails on noisy data.
**Alternative considered**: RTS smoother, linear interpolation.
**Why alternative rejected**: RTS smoother fails on non-linear motion, and linear interpolation fails on noisy data.
**Confidence**: MEDIUM — literature-supported.
**Open validation needed**: Has not been experimentally validated within the PixelVeil context.

### DEC-07: Backward targeted SCRFD for track-start recovery (max 20 frames)
**Decision**: When a new track is confirmed, search backward up to 20 frames using targeted SCRFD at the predicted prior position.
**Reason**: To recover potential initial missed detections before the face was formally tracked, minimizing privacy leakage at track onset.
**Research evidence**: Phase 6 found empirical recovery ceiling at 20 frames. 95% terminated by frame 26. Cycle consistency validates results.
**Alternative considered**: Unlimited backward search, or no backward search.
**Why alternative rejected**: Unlimited search yields diminishing returns and false positive risks. No backward search results in guaranteed privacy leakage.
**Confidence**: MEDIUM — literature-supported.
**Open validation needed**: The 20-frame limit needs PixelVeil-specific validation.

### DEC-08: Adaptive pixelation with noise overlay
**Decision**: Use adaptive pixelation (block size scales with face width) plus a Gaussian noise overlay for redaction.
**Reason**: To prevent advanced AI recovery techniques (like CodeFormer) from restoring the face, while maintaining visual aesthetics.
**Research evidence**: Phase 8 found Gaussian blur gives 95.9% re-ID. Pure pixelation vulnerable to CodeFormer. Mosaic+noise disrupts latent mappings.
**Alternative considered**: Gaussian blur, fixed pixelation, or solid black box.
**Why alternative rejected**: Gaussian blur is compromised, fixed pixelation is vulnerable, and a solid black box causes excessive false redaction.
**Confidence**: MEDIUM.
**Open validation needed**: Noise disruption efficacy is a hypothesis and not proven for PixelVeil.

### DEC-09: Privacy-biased confirmation (min_hits=1)
**Decision**: Set min_hits_to_confirm=1. A single detection immediately creates a confirmed track that gets redacted.
**Reason**: Prioritize absolute privacy. A delay in confirmation leaks frames.
**Research evidence**: Phase 3 found min_hits=1 yields +15-20% recall at <1% precision cost. Current min_hits=3 means first 2 frames of a face are leaked.
**Alternative considered**: min_hits=3 (current pipeline), min_hits=2.
**Why alternative rejected**: Both alternatives explicitly leak frames before the track is confirmed.
**Confidence**: MEDIUM — literature-supported and privacy-critical.
**Open validation needed**: May increase false positive tracks; false positive rate needs measurement.

### DEC-10: No ReID / facial recognition embeddings
**Decision**: Track faces purely by spatial association (IoU + centroid + Mahalanobis). Do not use appearance embeddings.
**Reason**: Ensures privacy by design and avoids heavy VRAM overhead.
**Research evidence**: Phase 4 found low-res face crops lack discriminative features. CNN embeddings consume excessive VRAM on target GTX 1650.
**Alternative considered**: Deep ReID features.
**Why alternative rejected**: Computationally expensive and faces are often too small for reliable embedding generation anyway.
**Confidence**: HIGH — justified by both privacy principles and compute limits.
**Open validation needed**: None.

### DEC-11: No TensorRT in v1
**Decision**: Keep ONNX Runtime for v1. Do not implement TensorRT.
**Reason**: TensorRT adds significant engineering and deployment complexity for limited practical gain in the current offline use case.
**Research evidence**: Phase 7 found TensorRT gives 1.5-2x speedup, but SCRFD CUDA already runs at 67 FPS. PixelVeil is offline, so real-time is not required.
**Alternative considered**: Implement TensorRT backend.
**Why alternative rejected**: Tradeoff between engineering complexity and performance benefit is unfavorable for v1 offline processing.
**Confidence**: HIGH — ONNX Runtime performance is sufficient.
**Open validation needed**: None.

### DEC-12: Feathered redaction edges (minimum 16px)
**Decision**: All redaction boundaries must have alpha-blended feathering of at least 16 pixels (one H.264 macroblock).
**Reason**: Prevents H.264 compression ringing (Gibbs phenomenon), which can leak depth maps and edge information around the redaction boundary.
**Research evidence**: Phase 8 found sharp boundaries trigger H.264 compression ringing, leaking depth maps.
**Alternative considered**: Sharp redaction boundaries.
**Why alternative rejected**: Causes information leakage through codec artifacts.
**Confidence**: MEDIUM — literature-supported.
**Open validation needed**: The precise degree of leakage prevention must be quantified for PixelVeil's specific encoding settings.

### DEC-13: Head expansion policy (asymmetric, uncertainty-aware)
**Decision**: Expand detection bbox asymmetrically: 25% horizontal, 45% above, 15% below. Add uncertainty-based dynamic dilation from tracker covariance.
**Reason**: Raw bounding boxes often leave peripheral biometrics (ears, chin, hair) exposed. Uncertainty dilation accounts for tracker drift.
**Research evidence**: Phase 8 established raw bboxes leave peripheral biometrics exposed. Current fixed expansion is reasonable baseline.
**Alternative considered**: Fixed expansion only (current), pose-dependent expansion.
**Why alternative rejected**: Pose-dependent expansion requires pose estimation models not in the pipeline. Fixed expansion fails to account for tracker uncertainty during coasting.
**Confidence**: MEDIUM — fixed values work empirically.
**Open validation needed**: Uncertainty dilation mathematics need practical validation.

### DEC-14: Synchronous pipeline with decode/encode optimization
**Decision**: Keep synchronous single-thread pipeline but eliminate double encoding by writing H.264 directly via ffmpeg pipe.
**Reason**: Avoid unnecessary complexity of multi-threading while fixing the largest I/O bottleneck.
**Research evidence**: Phase 7 identified double encoding as a major bottleneck. Current approach writes mp4v then re-encodes to H.264.
**Alternative considered**: Multi-threaded pipeline, or keep current double encoding.
**Why alternative rejected**: Multi-threading introduces excessive complexity for an offline tool. Double encoding is wasteful and slow.
**Confidence**: HIGH — clear bottleneck with a straightforward fix.
**Open validation needed**: None, ffmpeg pipe is a standard approach.

### DEC-15: Bounded privacy protection policy
**Decision**: During coasting/recovery, protect with uncertainty-expanded region. Maximum protection duration: 30 frames. Maximum spatial expansion: 1.5x original detection size.
**Reason**: Prevents indefinite ghost redactions when faces leave the frame, while ensuring sufficient coverage when they are temporarily occluded.
**Research evidence**: Phase 3 found max_age=30 is literature-supported. Phase 8 found max expansion cap of 1.5x.
**Alternative considered**: Indefinite protection (ghost redaction), immediate stop.
**Why alternative rejected**: Indefinite protection causes permanent false redactions. Immediate stop causes severe privacy leakage during transient occlusions.
**Confidence**: MEDIUM.
**Open validation needed**: The 30-frame limit and 1.5x expansion are reasonable starting values (Parameter Class C) and need tuning.
