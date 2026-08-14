# PixelVeil Implementation Roadmap

This document outlines the detailed implementation tasks for the PixelVeil architecture improvements. Tasks are ordered for sequential execution.

## PHASE P0: Foundation and Evaluation (No New Architecture)

### TASK-P01
- **TITLE**: Create Evaluation Harness
- **PRIORITY**: P0
- **DEPENDENCIES**: None
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: `tools/evaluate.py`, `tests/evaluation_corpus/`
- **IMPLEMENTATION DETAILS**: Build the evaluation harness *before* changing architecture. Must measure bbox IoU, face-center error, coverage rate, privacy leakage frames, and false positive area.
- **TESTS**: Unit tests for evaluation metrics.
- **BENCHMARK**: N/A
- **ACCEPTANCE CRITERIA**: Harness can run on a test video and output quantitative privacy and performance metrics.
- **FAILURE CONDITIONS**: None.
- **ROLLBACK CONDITION**: None.

### TASK-P02
- **TITLE**: Replace Branch-and-Bound with scipy.optimize.linear_sum_assignment
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-P01
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: The current `_linear_sum_assignment` is O(N!) recursive brute force. Replace with scipy's O(N^3) Hungarian implementation.
- **TESTS**: All existing tracker tests must pass.
- **BENCHMARK**: Measure association time with 1, 5, 10, 15 faces.
- **ACCEPTANCE CRITERIA**: All tests pass, O(N^3) performance, identical results for <5 faces.
- **FAILURE CONDITIONS**: If scipy not available, implement Munkres directly.
- **ROLLBACK CONDITION**: Revert to branch-and-bound.

### TASK-P03
- **TITLE**: Profile Current Pipeline
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-P01, TASK-P02
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Run the evaluation harness on the current pipeline to establish the baseline for recall, precision, and processing speed.
- **TESTS**: N/A
- **BENCHMARK**: Baseline metrics recorded.
- **ACCEPTANCE CRITERIA**: Baseline established.
- **FAILURE CONDITIONS**: N/A
- **ROLLBACK CONDITION**: N/A

### TASK-P04
- **TITLE**: Eliminate Double Video Encoding
- **PRIORITY**: P0
- **DEPENDENCIES**: None
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Current pipeline writes mp4v via OpenCV then re-encodes to H.264 via ffmpeg. Instead, pipe raw frames directly to ffmpeg subprocess stdin. This eliminates ~50% of encoding time.
- **TESTS**: All video pipeline tests must pass. Output must be playable H.264/yuv420p.
- **BENCHMARK**: Measure encoding time reduction.
- **ACCEPTANCE CRITERIA**: Single encode pass, identical output quality.
- **FAILURE CONDITIONS**: If ffmpeg pipe fails, fall back to current double-encode.
- **ROLLBACK CONDITION**: Revert to double encoding.

### TASK-P05
- **TITLE**: Implement Candidate Validation Instrumentation
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-P01
- **FILES TO MODIFY**: `core/candidate_validator.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Add recall-biased geometric validation (e.g. marking <20px as UNCERTAIN rather than REJECT) and log validation outcomes.
- **TESTS**: Unit tests for validation states.
- **BENCHMARK**: False positive reduction rate vs recall.
- **ACCEPTANCE CRITERIA**: Tiny faces are not blindly rejected; validation states are logged.
- **FAILURE CONDITIONS**: N/A
- **ROLLBACK CONDITION**: Revert to current logic.

## PHASE P1: Kalman Filter Tracker

### TASK-P1-1
- **TITLE**: Implement Linear Kalman Filter
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-A01
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: `core/kalman_tracker.py` (optional)
- **IMPLEMENTATION DETAILS**: Replace current constant-velocity + damping model with proper Linear Kalman Filter. State vector: `[x, y, w, h, vx, vy, vw, vh]`. Constant velocity model. Process noise Q and measurement noise R as tunable parameters. Track covariance matrix P for uncertainty estimation. Critical: The tracker MUST expose covariance P for downstream uncertainty-aware expansion.
- **TESTS**: Unit tests for predict/update cycle. Test convergence. Test uncertainty growth during coasting.
- **BENCHMARK**: Compare tracking quality vs current tracker on test videos.
- **ACCEPTANCE CRITERIA**: Smooth tracking, proper uncertainty growth, all existing tests adapted.
- **FAILURE CONDITIONS**: If Kalman diverges, add process noise tuning.
- **ROLLBACK CONDITION**: Keep current tracker.

### TASK-P1-2
- **TITLE**: Improved Association with Mahalanobis Gating
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-B01
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Replace current hard-gate association (distance + IoU) with Mahalanobis distance gating using tracker covariance. Threshold: 9.48 (chi-squared 95%, 4 DOF). Keep IoU as secondary cost metric.
- **TESTS**: Association tests with various scenarios. Crossing faces test.
- **BENCHMARK**: Track switches and fragmentations vs current.
- **ACCEPTANCE CRITERIA**: Fewer track switches, proper gating of impossible associations.
- **FAILURE CONDITIONS**: If Mahalanobis too aggressive, add fallback to IoU.
- **ROLLBACK CONDITION**: Revert to current hard gates.

### TASK-P1-3
- **TITLE**: Implement Canonical Association
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-P1-2
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Implement canonical association combining Linear Kalman prediction, Mahalanobis gating, IoU cost, and Hungarian assignment. Optionally, split by confidence thresholds to recover partially visible faces. Do not simply copy ByteTrack; tailor it and benchmark it against the baseline.
- **TESTS**: Test with low-confidence detections. Test partial occlusion scenarios.
- **BENCHMARK**: Recall improvement on difficult test videos vs baseline.
- **ACCEPTANCE CRITERIA**: Low-confidence detections properly associated with existing tracks without excessive false tracks.
- **FAILURE CONDITIONS**: If false associations increase, tune confidence split threshold or fallback to simpler association.
- **ROLLBACK CONDITION**: Revert to single-stage or prior association.

## PHASE C: Candidate Validation

### TASK-C01
- **TITLE**: Geometric Validation Gate
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-B01
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: `core/candidate_validator.py`
- **IMPLEMENTATION DETAILS**: Validate detection candidates against geometric constraints: minimum size (20x20), aspect ratio (0.5-2.0). Run as first filter after detection. O(1) per candidate.
- **TESTS**: Unit tests with valid faces, tiny noise, extreme aspect ratios.
- **BENCHMARK**: False positive reduction rate.
- **ACCEPTANCE CRITERIA**: Prunes ~80% of background noise. Zero valid faces rejected.
- **FAILURE CONDITIONS**: If valid small faces rejected, lower minimum size.
- **ROLLBACK CONDITION**: Remove validation gate.

### TASK-C02
- **TITLE**: Motion Plausibility Validation
- **PRIORITY**: P2
- **DEPENDENCIES**: TASK-C01, TASK-B02
- **FILES TO MODIFY**: `core/candidate_validator.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: For candidates matching existing tracks, validate motion plausibility via Mahalanobis distance. Reject candidates with D_M^2 > 9.48.
- **TESTS**: Test with smooth motion, sudden jumps, noise.
- **BENCHMARK**: Track switch reduction.
- **ACCEPTANCE CRITERIA**: Impossible motion transitions rejected.
- **FAILURE CONDITIONS**: If too aggressive, increase threshold.
- **ROLLBACK CONDITION**: Remove motion validation.

## PHASE P1-B: Boundary and Suspicious Region Detection

### TASK-P1-4
- **TITLE**: Boundary Strip Detection Policy
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-P1-1
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: `core/boundary_scanner.py`
- **IMPLEMENTATION DETAILS**: Implement configurable boundary scanning policies (e.g., 4 strips, 2 horizontal, 2 vertical, sampled). Benchmark compute cost vs edge-entry recall.
- **TESTS**: Test with faces entering from each edge. Test performance impact.
- **BENCHMARK**: Compute cost vs Edge-entry face recall.
- **ACCEPTANCE CRITERIA**: Selected policy detects edge entries without blowing compute budget.
- **FAILURE CONDITIONS**: If too slow, reduce strip width or scan frequency.
- **ROLLBACK CONDITION**: Remove boundary scanning.

### TASK-P1-5
- **TITLE**: Suspicious Region Classification
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-P1-4
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: `core/suspicion_detector.py`
- **IMPLEMENTATION DETAILS**: Classify frames/regions as suspicious based on: track entering COASTING, boundary proximity, low confidence detection, rapid scale change. Queue suspicious regions for targeted ROI recovery.
- **TESTS**: Unit tests for each suspicion trigger.
- **BENCHMARK**: Suspicion detection accuracy.
- **ACCEPTANCE CRITERIA**: All genuine detection dropouts flagged as suspicious.
- **FAILURE CONDITIONS**: If false suspicion rate too high, tune thresholds.
- **ROLLBACK CONDITION**: Remove suspicion detection.

### TASK-D03
- **TITLE**: Targeted ROI SCRFD Inference
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-D02
- **FILES TO MODIFY**: `core/face_detector.py`, `core/video_pipeline.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: For suspicious regions, crop the ROI with overlap margin, run SCRFD at higher effective resolution. Map detections back to full-frame coordinates. Merge with full-frame results using NMS. Adjust confidence threshold for cropped context (full-frame 0.5 ≈ crop 0.75).
- **TESTS**: Test ROI detection on known difficult faces.
- **BENCHMARK**: Recovery rate, latency per ROI inference.
- **ACCEPTANCE CRITERIA**: Recovers faces missed by full-frame detection.
- **FAILURE CONDITIONS**: If ROI inference too slow, batch or skip.
- **ROLLBACK CONDITION**: Remove targeted inference.

## PHASE E: Offline Recovery

### TASK-E01
- **TITLE**: Mid-Track Gap Detection
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-B01
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: `core/gap_resolver.py`
- **IMPLEMENTATION DETAILS**: After Pass 1 completes, scan all track timelines for gaps. A gap is defined as consecutive COASTING frames bounded by CONFIRMED frames on both sides.
- **TESTS**: Test gap detection with various patterns.
- **BENCHMARK**: N/A
- **ACCEPTANCE CRITERIA**: All gaps correctly identified with start/end frames.
- **FAILURE CONDITIONS**: N/A
- **ROLLBACK CONDITION**: N/A

### TASK-E02
- **TITLE**: Mid-Track Gap Interpolation (GSI)
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-E01
- **FILES TO MODIFY**: `core/gap_resolver.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: For each detected gap, apply Gaussian-Smoothed Interpolation between the last detection before the gap and the first detection after. Track uncertainty using hourglass profile. Validate with cycle consistency.
- **TESTS**: Test interpolation accuracy on known trajectories.
- **BENCHMARK**: Interpolation error, privacy coverage.
- **ACCEPTANCE CRITERIA**: Gap positions within 5px of true position for linear motion.
- **FAILURE CONDITIONS**: If GSI complex, fall back to linear interpolation with uncertainty.
- **ROLLBACK CONDITION**: Fill gaps with last-known position + expansion.

### TASK-E03
- **TITLE**: Track-Start Backward Recovery
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-D03, TASK-E01
- **FILES TO MODIFY**: `core/gap_resolver.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: When a track's first confirmed frame is not frame 0, search backward up to `max_backward_search` frames. For each backward frame, generate search ROI from forward-projected position + adaptive padding. Run targeted SCRFD. Validate with cycle consistency (forward-backward normalized error).
- **TESTS**: Test backward recovery on faces entering frame.
- **BENCHMARK**: Recovery rate vs compute cost, backward search depth.
- **ACCEPTANCE CRITERIA**: Recovers faces effectively while meeting normalized error constraints.
- **FAILURE CONDITIONS**: If cycle consistency too strict, tune the normalized error threshold.
- **ROLLBACK CONDITION**: Skip backward recovery.

## PHASE F: Uncertainty-Aware Redaction

### TASK-F01
- **TITLE**: Uncertainty-Aware Region Expansion
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-B01
- **FILES TO MODIFY**: `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Use tracker covariance matrix P to dynamically expand redaction region. `expansion = base_expansion + Z * sqrt(P)`, where Z=2.58 (99% confidence). Cap at 1.5x original size.
- **TESTS**: Test expansion at various uncertainty levels.
- **BENCHMARK**: Privacy coverage vs false redaction area.
- **ACCEPTANCE CRITERIA**: Higher uncertainty = larger protection zone. Never exceeds 1.5x cap.
- **FAILURE CONDITIONS**: If expansion too aggressive, reduce Z.
- **ROLLBACK CONDITION**: Revert to fixed expansion.

### TASK-F02
- **TITLE**: Bounded Privacy Protection Policy
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-F01
- **FILES TO MODIFY**: `core/face_tracker.py`, `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: During coasting, protect with uncertainty-expanded region. Maximum 30 frames. Maximum 1.5x expansion. After limits exceeded, mark as 'unresolved' in output metadata rather than continuing indefinite protection.
- **TESTS**: Test protection duration limits.
- **BENCHMARK**: N/A
- **ACCEPTANCE CRITERIA**: No indefinite ghost redaction. Clear termination policy.
- **FAILURE CONDITIONS**: If 30 frames insufficient, evaluate per-video.
- **ROLLBACK CONDITION**: Revert to current max_missing=15.


