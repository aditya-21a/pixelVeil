# PixelVeil Implementation Roadmap

This document outlines the detailed implementation tasks for the PixelVeil architecture improvements. Tasks are strictly ordered for sequential execution.

## PHASE P0 — BASELINE & EVALUATION

### TASK-P0-01
- **TITLE**: Evaluation Harness
- **PRIORITY**: P0
- **DEPENDENCIES**: None
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: `tools/evaluate.py`, `tests/evaluation_corpus/`
- **IMPLEMENTATION DETAILS**: Build the evaluation harness *before* changing architecture. It must establish GROUND TRUTH (Face existence / bbox / visibility) against System output. Must measure BOTH detection performance and privacy coverage. Metrics: bbox IoU, face-center error (normalized by face size), coverage rate, privacy leakage frames, false positive area, false redaction duration. Metrics must be bucketed by: face-size, edge-distance, occlusion, motion, source of detection, source of recovered protection. Record longest unprotected run and first-visible-frame leakage.
- **TESTS**: Unit tests for evaluation metrics.
- **BENCHMARK**: N/A
- **ACCEPTANCE CRITERIA**: Harness can output quantitative privacy and performance metrics, explicitly distinguishing "Was the face detected?" from "Was the actual face region protected?".
- **FAILURE CONDITIONS**: None.
- **ROLLBACK CONDITION**: None.

### TASK-P0-02
- **TITLE**: Baseline Pipeline Profile
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-P0-01
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Run the evaluation harness on the current pipeline to establish the baseline for recall, precision, and processing speed. Do this before any optimization.
- **TESTS**: N/A
- **BENCHMARK**: Baseline metrics recorded.
- **ACCEPTANCE CRITERIA**: Baseline established.
- **FAILURE CONDITIONS**: N/A
- **ROLLBACK CONDITION**: N/A

### TASK-P0-03
- **TITLE**: Hungarian Association Optimization
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-P0-02
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: The current `_linear_sum_assignment` is O(N!) recursive brute force. Replace with scipy's O(N^3) Hungarian implementation.
- **TESTS**: All existing tracker tests must pass.
- **BENCHMARK**: Measure association time with 1, 5, 10, 15 faces.
- **ACCEPTANCE CRITERIA**: All tests pass, O(N^3) performance, identical results for <5 faces.
- **FAILURE CONDITIONS**: If scipy not available, implement Munkres directly.
- **ROLLBACK CONDITION**: Revert to branch-and-bound.

### TASK-P0-04
- **TITLE**: Candidate Validation Instrumentation
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-P0-02
- **FILES TO MODIFY**: `core/candidate_validator.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Add recall-biased geometric validation (e.g. marking <20px as UNCERTAIN rather than REJECT) and log validation outcomes.
- **TESTS**: Unit tests for validation states.
- **BENCHMARK**: False positive reduction rate vs recall.
- **ACCEPTANCE CRITERIA**: Tiny faces are not blindly rejected; validation states are logged.
- **FAILURE CONDITIONS**: N/A
- **ROLLBACK CONDITION**: Revert to current logic.

### TASK-P0-05
- **TITLE**: Single-Pass H.264 Encoding
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-P0-02
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Current pipeline writes mp4v via OpenCV then re-encodes to H.264 via ffmpeg. Instead, pipe raw frames directly to ffmpeg subprocess stdin. Expected benefit: reduce encoding overhead. Measured benefit: determined by benchmark.
- **TESTS**: All video pipeline tests must pass. Output must be playable H.264/yuv420p.
- **BENCHMARK**: Measure encoding time reduction against baseline profile.
- **ACCEPTANCE CRITERIA**: Single encode pass, identical output quality.
- **FAILURE CONDITIONS**: If ffmpeg pipe fails, fall back to current double-encode.
- **ROLLBACK CONDITION**: Revert to double encoding.

## PHASE P1 — TRACKING

### TASK-P1-01
- **TITLE**: Linear Kalman Filter
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-P0-04
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: `core/kalman_tracker.py` (optional)
- **IMPLEMENTATION DETAILS**: Replace current constant-velocity + damping model with proper Linear Kalman Filter. State vector: `[x, y, w, h, vx, vy, vw, vh]`. Constant velocity model. Process noise Q and measurement noise R as tunable parameters. Track covariance matrix P for uncertainty estimation. Critical: The tracker MUST expose covariance P for downstream uncertainty-aware expansion.
- **TESTS**: Unit tests for predict/update cycle. Test convergence. Test uncertainty growth during coasting.
- **BENCHMARK**: Compare tracking quality vs current tracker on test videos.
- **ACCEPTANCE CRITERIA**: Smooth tracking, proper uncertainty growth, all existing tests adapted.
- **FAILURE CONDITIONS**: If Kalman diverges, add process noise tuning.
- **ROLLBACK CONDITION**: Keep current tracker.

### TASK-P1-02
- **TITLE**: Mahalanobis Gating
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-P1-01
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Replace current hard-gate association (distance + IoU) with Mahalanobis distance gating using tracker covariance. Initial threshold: 9.48 (status: starting value, must sweep to find optimal threshold for our specific state/measurement dimensionality). Keep IoU as secondary cost metric.
- **TESTS**: Association tests with various scenarios. Crossing faces test.
- **BENCHMARK**: Track switches and fragmentations vs current.
- **ACCEPTANCE CRITERIA**: Fewer track switches, proper gating of impossible associations.
- **FAILURE CONDITIONS**: If Mahalanobis too aggressive, add fallback to IoU.
- **ROLLBACK CONDITION**: Revert to current hard gates.

### TASK-P1-03
- **TITLE**: Canonical Spatial-Kinematic Association
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-P1-02
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Implement canonical association combining Linear Kalman prediction, Mahalanobis gating, IoU cost, and Hungarian assignment. Optionally, split by confidence thresholds to recover partially visible faces.

## PHASE P2 — DETECTION RECOVERY

### TASK-P2-01
- **TITLE**: Boundary Recovery Policy
- **PRIORITY**: P2
- **DEPENDENCIES**: TASK-P1-03
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: `core/boundary_scanner.py`
- **IMPLEMENTATION DETAILS**: Implement configurable boundary scanning policies (e.g., 4 strips, 2 horizontal, 2 vertical, sampled). Frame -> Boundary Recovery Policy -> [scan / skip / alternate / sample]. Benchmark compute cost vs edge-entry recall.
- **TESTS**: Test with faces entering from each edge.
- **BENCHMARK**: Compute cost vs Edge-entry face recall.
- **ACCEPTANCE CRITERIA**: Selected policy detects edge entries without blowing compute budget.
- **FAILURE CONDITIONS**: If too slow, reduce strip width or scan frequency.
- **ROLLBACK CONDITION**: Remove boundary scanning.

### TASK-P2-02
- **TITLE**: Suspicion Classification
- **PRIORITY**: P2
- **DEPENDENCIES**: TASK-P2-01
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: `core/suspicion_detector.py`
- **IMPLEMENTATION DETAILS**: Classify frames/regions as suspicious based on: track entering COASTING, boundary proximity, low confidence detection, rapid scale change. Queue suspicious regions for targeted ROI recovery.
- **TESTS**: Unit tests for each suspicion trigger.
- **BENCHMARK**: Suspicion detection accuracy.
- **ACCEPTANCE CRITERIA**: All genuine detection dropouts flagged as suspicious.
- **FAILURE CONDITIONS**: If false suspicion rate too high, tune thresholds.
- **ROLLBACK CONDITION**: Remove suspicion detection.

### TASK-P2-03
- **TITLE**: Targeted ROI SCRFD
- **PRIORITY**: P2
- **DEPENDENCIES**: TASK-P2-02
- **FILES TO MODIFY**: `core/face_detector.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Support extracting specific high-resolution crops from the frame and running inference only on those crops, re-mapping coordinates back to the full frame.

## PHASE P3 — OFFLINE GAP RECOVERY

### TASK-P3-01
- **TITLE**: Gap Detection
- **PRIORITY**: P3
- **DEPENDENCIES**: TASK-P2-03
- **FILES TO MODIFY**: `core/gap_resolver.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: After Pass 1 completes, detect temporal gaps in the tracking timeline where a track was lost and then re-acquired. Prepare endpoints for recovery.

### TASK-P3-02
- **TITLE**: GSI Mid-Track Recovery
- **PRIORITY**: P3
- **DEPENDENCIES**: TASK-P3-01
- **FILES TO MODIFY**: `core/gap_resolver.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Apply Gaussian-Smoothed Interpolation (GSI) for remaining unresolved mid-track gaps. Track uncertainty using hourglass profile. Must measurably outperform linear interpolation.

### TASK-P3-03
- **TITLE**: Track-Start Backward Recovery
- **PRIORITY**: P3
- **DEPENDENCIES**: TASK-P3-02
- **FILES TO MODIFY**: `core/gap_resolver.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: When a track's first confirmed frame is not frame 0, search backward up to a configurable budget. Generate search ROI from forward-projected position + adaptive padding. Validate with cycle consistency.

## PHASE P4 — PRIVACY SAFETY

### TASK-P4-01
- **TITLE**: Evidence/Action Finalization
- **PRIORITY**: P4
- **DEPENDENCIES**: TASK-P3-03
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Ensure strict translation from tracking state (`evidence_state` + `provenance`) to rendering intent (`privacy_action`).

### TASK-P4-02
- **TITLE**: Covariance-Based Expansion
- **PRIORITY**: P4
- **DEPENDENCIES**: TASK-P4-01
- **FILES TO MODIFY**: `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Compute covariance-derived confidence region -> convert ellipse to axis-aligned margin -> apply configurable confidence level -> clamp using experimentally derived expansion policy.

### TASK-P4-03
- **TITLE**: Bounded Protection
- **PRIORITY**: P4
- **DEPENDENCIES**: TASK-P4-02
- **FILES TO MODIFY**: `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Limit indefinite ghost redactions. Protect with uncertainty-expanded region up to configurable limits (initial exp: 30 frames, 1.5x spatial expansion).

## PHASE P5 — REDACTION

### TASK-P5-01
- **TITLE**: Adaptive Pixelation
- **PRIORITY**: P5
- **DEPENDENCIES**: TASK-P4-03
- **FILES TO MODIFY**: `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Dynamically calculate pixelation block size per frame per face based on bounding box width (e.g., max(4, int(0.08 * face_width))).

### TASK-P5-02
- **TITLE**: Noise/Disruption Experiment
- **PRIORITY**: P5
- **DEPENDENCIES**: TASK-P5-01
- **FILES TO MODIFY**: `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Implement and benchmark additive noise (e.g., Gaussian overlay) to disrupt AI reconstruction models (CodeFormer/Revelio).

### TASK-P5-03
- **TITLE**: Feathering
- **PRIORITY**: P5
- **DEPENDENCIES**: TASK-P5-02
- **FILES TO MODIFY**: `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Alpha-blend redaction edges (configured width, e.g. 16px) to avoid H.264 macroblock ringing.

## PHASE P6 — PERFORMANCE

### TASK-P6-01
- **TITLE**: End-to-End Profiling
- **PRIORITY**: P6
- **DEPENDENCIES**: TASK-P5-03
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Profile the full locked architecture to identify processing bottlenecks.

### TASK-P6-02
- **TITLE**: ROI Batching
- **PRIORITY**: P6
- **DEPENDENCIES**: TASK-P6-01
- **FILES TO MODIFY**: `core/face_detector.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Implement batch inference for targeted ROIs during Pass 2 to saturate the GPU.

### TASK-P6-03
- **TITLE**: Pipeline Parallelism
- **PRIORITY**: P6
- **DEPENDENCIES**: TASK-P6-02
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Separate I/O, tracking, and rendering into parallel threads/processes if sequential execution misses target FPS.

### TASK-P6-04
- **TITLE**: TensorRT Decision
- **PRIORITY**: P6
- **DEPENDENCIES**: TASK-P6-03
- **FILES TO MODIFY**: `core/face_detector.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: If pipeline parallelism doesn't achieve performance targets, validate TensorRT implementation for the SCRFD models.

## PHASE P7 — FINAL VALIDATION

### TASK-P7-01
- **TITLE**: Ablation
- **PRIORITY**: P7
- **DEPENDENCIES**: TASK-P6-04
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Systematically disable components (e.g., backward recovery, GSI) to validate their contribution to privacy vs compute cost.

### TASK-P7-02
- **TITLE**: Hard-Case Evaluation
- **PRIORITY**: P7
- **DEPENDENCIES**: TASK-P7-01
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Test against the most severe test cases (motion blur, low light, heavy occlusion) to establish the operational bounds.

### TASK-P7-03
- **TITLE**: Privacy Attack Evaluation
- **PRIORITY**: P7
- **DEPENDENCIES**: TASK-P7-02
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Run facial recognition models against the redacted outputs to confirm the redaction guarantees hold.

### TASK-P7-04
- **TITLE**: Regression Suite
- **PRIORITY**: P7
- **DEPENDENCIES**: TASK-P7-03
- **FILES TO MODIFY**: `tests/`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Ensure the continuous integration suite properly asserts the privacy-critical rules (e.g., min_hits=1) to prevent future regression.