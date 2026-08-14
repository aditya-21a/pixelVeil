# PixelVeil: Research-to-Architecture Mapping

This document explicitly maps every foundational research finding and parameter to its corresponding architectural decision in the PixelVeil pipeline. It is designed to answer the fundamental question: *Why was it built this way?*

All numerical parameters are marked with their validation status:
- **[A]**: PixelVeil-validated
- **[B]**: Literature/Benchmark supported
- **[C]**: Reasonable starting value (requires validation)
- **[D]**: Arbitrary

---

## 1. Object Detection Component

**WHY IT EXISTS**: To accurately localize faces across various scales and occlusion states in the input video stream, serving as the foundational input for the entire redaction pipeline.
**INPUT**: Video frames (scaled or tiled), configuration parameters (confidence threshold).
**DECISION**: Determine which regions of the frame contain faces, maximizing recall without overwhelming downstream filters with false positives.
**OUTPUT**: A set of bounding boxes (x1, y1, x2, y2) with confidence scores.
**FAILURE MODE**: Missed detections on small/occluded faces, false positives from background clutter, or failure due to VRAM exhaustion.
**RESEARCH EVIDENCE**: Phase 1, Phase 2, and Phase 7 findings.
**COMPUTATIONAL COST**: High (O(N) based on input resolution/tiles; dominates pipeline compute).

### 1.1 Architectural Pruning & Feature Branches
- **Research finding**: Architectural Pruning [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: To meet consumer GPU constraints, high-res feature branches (Stride-4) are often pruned. Stride-4 alone accounts for ~68% of computational cost. Without it, model is blind to distant faces.
- **→ implication**: A globally downscaled 4K frame to 640x640 will lose small faces permanently if Stride-4 is missing.
- **→ architecture decision**: Do not rely on a single global downscaled pass for high-resolution input if small faces are expected.
- **→ implementation task**: Implement a tiling or selective ROI detection strategy instead of pure global downscaling.
- **→ validation experiment**: Compare Hard AP on WIDER FACE using global 640x640 vs Tiled inference.

### 1.2 Boundary Artifacts
- **Research finding**: Zero-Padding Boundary Artifacts [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Padding edges with zeros causes severe artifacts, signal dilution, and positional bias. Catastrophic detection failures on faces entering the frame.
- **→ implication**: Faces cropped tightly or near frame borders will have suppressed confidence scores.
- **→ architecture decision**: Avoid zero-padding when tiling; ensure overlap and use edge-aware suppression handling.
- **→ implementation task**: Implement tiled inference with overlapping regions and merge bounding boxes carefully near edges.
- **→ validation experiment**: Test detection recall on a dataset of faces partially entering/exiting the camera frame.

### 1.3 Sample Imbalance
- **Research finding**: Sample Imbalance [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Training data biased toward large centered faces. Models learn structural priors that break when faces are >30% occluded.
- **→ implication**: Detection confidence will plummet during heavy occlusion.
- **→ architecture decision**: Do not rely solely on the detector to maintain tracks during occlusion; shift responsibility to the tracker.
- **→ implementation task**: Implement robust tracking (PixelVeil Spatial-Kinematic Association) that tolerates missing detections.
- **→ validation experiment**: Track faces moving behind obstacles (e.g., pillars) and measure ID switch/fragmentation rate.

### 1.4 Minimum Resolution Limit
- **Research finding**: 32-pixel threshold [B: Literature]: Detection accuracy deteriorates exponentially below 32px face size.
- **→ implication**: Inputs must be scaled such that target faces remain ≥ 32px.
- **→ architecture decision**: Mark detections below an absolute minimum size as UNCERTAIN rather than rejecting them, deferring to temporal evidence.
- **→ implementation task**: Implement `min_face_size` as an initial experimental threshold (e.g., 20px) [B].
- **→ validation experiment**: Measure precision-recall curves across face sizes from 10px to 50px.

### 1.5 Model Selection (WIDER FACE)
- **Research finding**: WIDER FACE Hard: SCRFD-0.5GF achieves 68.50% Hard AP. SCRFD-10GF achieves 83.05%.
- **→ implication**: The lightweight model is significantly worse at hard (small/occluded) faces.
- **→ architecture decision**: SCRFD family is locked; 0.5GF is the current baseline, model size remains an experiment.
- **→ implementation task**: Make model size an explicit P0 experiment. Benchmark recall vs inference time of SCRFD-0.5GF vs 2.5GF/10GF on PixelVeil test corpus before locking the final model.
- **→ validation experiment**: Compare privacy coverage vs processing time for 0.5GF vs 10GF.

### 1.6 Input-Resolution Problem
- **Research finding**: Input-Resolution Problem: A 16x16 face becomes sub-pixel at Stride-32. Globally downscaling 4K to 640x640 destroys high-frequency spatial information.
- **→ implication**: Direct downscaling is mathematically destructive to distant subjects.
- **→ architecture decision**: Full-frame SAHI is rejected as default. Selective ROI (Targeted Recovery) is the target architecture.
- **→ implementation task**: Add targeted ROI inference for suspicious regions rather than full-frame tiling.
- **→ validation experiment**: Verify small face recall using selective ROI on 4K footage.

### 1.7 Tiling and Confidence Calibration
- **Research finding**: Confidence inflation on crops [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Tightly cropping removes background noise, inflating confidence (e.g., 0.55 full-frame → 0.98 on crop). Static thresholds fail across domains.
- **→ implication**: A static 0.5 threshold might be too low for crops and too high for full frames.
- **→ architecture decision**: Calibrate confidence thresholds based on crop context.
- **→ implementation task**: Implement dynamic confidence thresholds (e.g., ~0.50 full-frame ≈ ~0.75 on tight crops [C]).
- **→ validation experiment**: Plot confidence score distributions for the same face in full-frame vs tight crop.

### 1.8 Full-frame SAHI Compute Limits
- **Research finding**: Full-frame SAHI on every frame [REJECTED]: Unoptimized SAHI on every frame violates thermal/compute limits on consumer GPUs. 5 tiles = 5x GFLOPs.
- **→ implication**: Tiling every frame is too expensive.
- **→ architecture decision**: Use selective ROI based on track priors, or limit tiling to keyframes.
- **→ implementation task**: Implement Tracker-driven selective ROI detection.
- **→ validation experiment**: Measure FPS and GPU temperature over a 1-hour 4K video using full SAHI vs Selective ROI.

### 1.9 Hardware Acceleration & Batching
- **Research finding**: TensorRT provides 1.5-2x speedup over PyTorch, 20-50% lower latency than ONNX Runtime. Batch 4-8 maximizes throughput. OOM at batch >8 for larger models on 6GB. [SUPPORTED BY LITERATURE NOT PV-VALIDATED]
- **→ implication**: Synchronous single-frame ONNX is bottlenecking the current pipeline.
- **→ architecture decision**: TensorRT is deferred pending an end-to-end benchmark. Batch processing can be evaluated.
- **→ implementation task**: Benchmark PyTorch vs ONNX Runtime vs TensorRT.
- **→ validation experiment**: Benchmark throughput (FPS) on GTX 1650 before committing to TensorRT complexity.

---

## 2. Validation & Filtering Component

**WHY IT EXISTS**: To prune false positives generated by the detector before they pollute the tracker or redaction output.
**INPUT**: Raw bounding boxes from the detector.
**DECISION**: Accept or reject a bounding box based on geometric, motion, and temporal heuristics.
**OUTPUT**: Filtered bounding boxes.
**FAILURE MODE**: Rejecting valid faces (false negatives) or passing persistent artifacts (false positives).
**RESEARCH EVIDENCE**: Phase 3 findings.
**COMPUTATIONAL COST**: Very Low (O(1) geometric checks, O(N) Mahalanobis checks).

### 2.1 Cascading Validation
- **Research finding**: Three-phase cascading validation [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Geometric → Motion (Mahalanobis) → Temporal state machine.
- **→ implication**: Validating sequentially saves compute and structurally isolates failure modes.
- **→ architecture decision**: Implement a strict three-stage pipeline.
- **→ implementation task**: Build `GeometricValidator`, `MotionValidator`, and `TemporalValidator` classes.
- **→ validation experiment**: Profile execution time and precision impact of each stage.

### 2.2 Geometric Constraints
- **Research finding**: Geometric Stage 1 prunes ~80% background noise in O(1). Aspect ratio range: 0.5 to 2.0 [B]. 20px = initial uncertainty threshold, NOT a rejection threshold [B].
- **→ implication**: Cheap math can eliminate the vast majority of junk detections.
- **→ architecture decision**: Enforce geometric boundaries on raw bounding boxes, marking size outliers as UNCERTAIN rather than rejecting.
- **→ implementation task**: Add aspect ratio and uncertainty size checks before passing to tracker.
- **→ validation experiment**: Measure % of false positives dropped by geometric checks alone.

### 2.3 Temporal Confirmation (Privacy focus)
- **Research finding**: min_hits=1 for privacy [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Dropping confirmation to 1 frame yields +15-20% recall at <1% precision cost.
- **→ implication**: Waiting for `min_hits=3` (current codebase state) leaks faces for 2 frames.
- **→ architecture decision**: Change tracker state machine to confirm immediately. The `TENTATIVE` state is bypassed/removed entirely.
- **→ implementation task**: Update tracker to use `min_hits=1` and remove the `TENTATIVE` state.
- **→ validation experiment**: Frame-by-frame visual inspection to ensure no 1-frame face leaks exist, and measure false positive rate.

---

## 3. Object Tracking & Motion Prediction Component

**WHY IT EXISTS**: To maintain identity persistence across frames, bridge detection gaps during occlusion, and smooth erratic bounding box movements.
**INPUT**: Filtered bounding boxes per frame.
**DECISION**: Associate new boxes to existing tracks or create new ones; predict location if detection is missing.
**OUTPUT**: Continuous trajectories (tracks) with associated bounding boxes.
**FAILURE MODE**: ID switches, lost tracks during occlusion, or unbounded drift during coasting.
**RESEARCH EVIDENCE**: Phase 4 and Phase 5 findings.
**COMPUTATIONAL COST**: Low-Medium (Depending on assignment algorithm and smoothing).

### 3.1 Tracker Selection & Algorithm
- **Research finding**: ByteTrack/OC-SORT style tracking recommended [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Strong spatial/mathematical heuristics without CNN feature extractors. Good for single-class face tracking on consumer GPUs. Linear Constant Velocity Kalman filter remains standard.
- **→ implication**: The current custom tracker (branch-and-bound, exponential damping) is sub-optimal and slow (O(N!)).
- **→ architecture decision**: Replace custom tracker with PixelVeil Spatial-Kinematic Association (Kalman + feasibility gates + Mahalanobis + IoU/geometry cost + Hungarian).
- **→ implementation task**: Implement canonical association combining these mathematical components.
- **→ validation experiment**: Benchmark against ByteTrack/OC-SORT as baselines to ensure the custom formulation matches or exceeds their performance on heavily occluded datasets.

### 3.2 Two-Stage Association
- **Research finding**: Two-stage association [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Cascaded spatial proximity + IoU. Trusts low-confidence detections during partial visibility.
- **→ implication**: Discarding low-confidence detections outright breaks tracks.
- **→ architecture decision**: Keep low-confidence boxes (e.g., 0.1 to 0.5) solely for optional secondary track association, not track creation.
- **→ implementation task**: Implement optional low-confidence secondary association.
- **→ validation experiment**: Track faces walking behind trees; verify track persistence using low-confidence boxes.

### 3.3 Anomaly Detection (Mahalanobis)
- **Research finding**: Mahalanobis gating: 9.48 (95% confidence, 4 DOF) [B: Literature].
- **→ implication**: Bounding boxes that jump impossibly far should be rejected as anomalies.
- **→ architecture decision**: Use Mahalanobis distance between Kalman prediction and observation to gate associations.
- **→ implementation task**: Implement Mahalanobis gating in the assignment cost matrix.
- **→ validation experiment**: Introduce synthetic noise boxes and verify the tracker rejects them.

### 3.4 ReID and Embeddings
- **Research finding**: No ReID/embeddings [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Low-res face crops lack discriminative features. CNN embeddings consume excessive VRAM.
- **→ implication**: Visual feature matching is too expensive and unreliable for small faces.
- **→ architecture decision**: Rely purely on motion/spatial heuristics for tracking.
- **→ implementation task**: Explicitly remove/avoid embedding-based ReID networks (like OSNet/FastReID).
- **→ validation experiment**: Benchmark VRAM usage (must stay under 4GB/6GB limit).

### 3.5 Filling Mid-Track Gaps
- **Research finding**: GSI (Gaussian-Smoothed Interpolation) + OCM superior [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Better than Linear Interpolation and RTS smoother. RTS fails on irregular biological motion. Bidirectional filtering exploits future observations.
- **→ implication**: Real-time forward-only prediction drifts wildly (31-114px error [B]). Offline processing allows looking into the future.
- **→ architecture decision**: Utilize a bidirectional smoother (GSI) post-tracking to fix gaps and erratic motion.
- **→ implementation task**: Implement a post-processing pass applying GSI to all tracks.
- **→ validation experiment**: Measure bounding box IoU against ground truth during a 10-frame occlusion gap.

---

## 4. Recovery & Backfilling Component

**WHY IT EXISTS**: To retroactively find faces that were missed at the very beginning of a track (e.g., entering the frame or emerging from heavy occlusion) to minimize privacy leakage under defined benchmark conditions.
**INPUT**: Confirmed track trajectories.
**DECISION**: Search backward in time from the start of a track to find earlier instances of the face.
**OUTPUT**: Extended track histories.
**FAILURE MODE**: Leaking the first few frames of a face before the detector triggers, or recovering false positives.
**RESEARCH EVIDENCE**: Phase 6 findings.
**COMPUTATIONAL COST**: Medium (Requires localized re-detection/tracking).

### 4.1 Cooperative Detection and Tracking (CDT)
- **Research finding**: Cooperative Detection and Tracking (CDT) [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: First confirmed bbox as spatial anchor for backward Siamese search. Backward recovery ceiling: 20 frames [B].
- **→ implication**: We can use the first confident detection to find the face in the preceding frames.
- **→ architecture decision**: Implement an asynchronous backward recovery pass for newly confirmed tracks.
- **→ implementation task**: Build a localized backward search up to `max_backward_frames` (20 [B]).
- **→ validation experiment**: Test video of a person quickly walking into frame; verify the very first visible frame is redacted.

### 4.2 Brand-New Face Problem
- **Research finding**: Brand-new face problem: NO reliable deterministic CV signal to prove a completely occluded object is physically present vs outside frame. [SUPPORTED BY LITERATURE NOT PV-VALIDATED — NEGATIVE FINDING]
- **→ implication**: We cannot mathematically prove a face is behind a wall before it ever appears.
- **→ architecture decision**: Accept that recovery is limited to partial visibility prior to the first detection, and cannot invent bounding boxes from thin air.
- **→ implementation task**: Constrain backward recovery to terminate when feature quality drops below 0.01 [B].
- **→ validation experiment**: Ensure backward recovery does not paint masks on blank walls before a person enters the room.

### 4.3 Cycle Consistency
- **Research finding**: Cycle consistency validation [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: Forward-backward validation must use a normalized metric (e.g. error / face_diagonal), not a rigid 1-pixel threshold.
- **→ implication**: A rigid 1-pixel threshold will fail on large faces and high-resolution video.
- **→ architecture decision**: Validate backward recovered boxes by tracking them forward again and computing a normalized error.
- **→ implementation task**: Implement forward-backward consistency check with a tunable normalized threshold.
- **→ validation experiment**: Measure false positive rate of backward recovery across different face scales.

---

## 5. Redaction & Rendering Component

**WHY IT EXISTS**: To permanently and irreversibly destroy identity information in the video while maintaining visual coherence.
**INPUT**: Finalized, smoothed track bounding boxes and original video frames.
**DECISION**: How to obscure the pixel data inside the bounding boxes to defeat both human and AI re-identification.
**OUTPUT**: Final encoded video file.
**FAILURE MODE**: AI-based de-anonymization (CodeFormer, Revelio) reconstructs the face, or hard mask edges leak depth maps.
**RESEARCH EVIDENCE**: Phase 8 findings.
**COMPUTATIONAL COST**: Medium (Image processing, video encoding).

### 5.1 Defeating AI Reconstruction
- **Research finding**: Gaussian blur compromised [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: 95.9% re-ID. Pure pixelation vulnerable [SUPPORTED BY LITERATURE NOT PV-VALIDATED]: CodeFormer can reconstruct. Mosaic + Gaussian noise disrupts latent mappings [HYPOTHESIS to be tested].
- **→ implication**: Standard blur and pixelation are insecure against modern AI, but exact disruption mechanisms must be benchmarked.
- **→ architecture decision**: Implement a compound redaction algorithm combining adaptive pixelation with additive noise as an experiment.
- **→ implementation task**: Update redactor to test `Mosaic + Gaussian Noise`.
- **→ validation experiment**: Run CodeFormer/Revelio against redacted output and measure AdaFace similarity (<0.50 CelebA [B]). Ensure visual artifacts don't degrade non-face regions.

### 5.2 Adaptive Pixelation
- **Research finding**: Adaptive pixelation: Block size must scale with true head width. Adaptive pixelation scalar: 0.08 * W_head [B]. Base pixelation threshold: 4x4 pixels [B].
- **→ implication**: Static block sizes leave large faces identifiable and turn small faces into solid blocks.
- **→ architecture decision**: Dynamically calculate pixelation block size per frame per face based on bounding box width, treated as an experimental parameter sweep.
- **→ implementation task**: Implement `block_size = max(4, int(0.08 * face_width))` as a configurable baseline for the parameter sweep.
- **→ validation experiment**: Visually verify block proportionality on faces ranging from 30px to 800px wide.

### 5.3 Mask Edges & H.264 Ringing
- **Research finding**: H.264 compression ringing: Sharp redaction boundaries leak depth maps. Alpha-blended feathering >= 1 macroblock (16px). [SUPPORTED BY LITERATURE NOT PV-VALIDATED]
- **→ implication**: Hard-edged masks allow structural reconstruction of the face boundary.
- **→ architecture decision**: All redaction masks must have feathered edges exceeding H.264 macroblock sizes.
- **→ implementation task**: Enforce a minimum feather radius of 16px [B] and use elliptical masks.
- **→ validation experiment**: Examine H.264 compressed output for I-frame macroblock ringing around redaction edges.

### 5.4 Spatial Expansion & Uncertainty
- **Research finding**: Tracker uncertainty confidence Z: 2.58 [C]. Max mask expansion: 1.5x [C].
- **→ implication**: The tracker's exact box might miss the nose or hair, especially during fast motion.
- **→ architecture decision**: Expand the redaction mask based on velocity and tracker covariance, up to a safety limit.
- **→ implementation task**: Implement dynamic expansion based on Kalman state uncertainty (current static expansion is 25% sides, 45% top, 15% bottom).
- **→ validation experiment**: Frame-by-frame review of high-velocity head turns to ensure no features breach the mask.
