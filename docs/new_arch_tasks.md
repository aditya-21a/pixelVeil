# PixelVeil Implementation Roadmap

This document outlines the detailed implementation tasks for the PixelVeil architecture improvements. Tasks are ordered for sequential execution.

## PHASE A: Foundation Improvements (No New Architecture)

### TASK-A01
- **TITLE**: Replace Branch-and-Bound with scipy.optimize.linear_sum_assignment
- **PRIORITY**: P0
- **DEPENDENCIES**: None
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: The current `_linear_sum_assignment` is O(N!) recursive brute force. Replace with scipy's O(N^3) Hungarian implementation. This is a correctness/scalability fix.
- **TESTS**: All existing tracker tests must pass. Add crowd test with 10+ faces.
- **BENCHMARK**: Measure association time with 1, 5, 10, 15 faces.
- **ACCEPTANCE CRITERIA**: All tests pass, O(N^3) performance, identical results for <5 faces.
- **FAILURE CONDITIONS**: If scipy not available, implement Munkres directly.
- **ROLLBACK CONDITION**: Revert to branch-and-bound.

### TASK-A02
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

### TASK-A03
- **TITLE**: Privacy-Biased Track Confirmation (min_hits=1)
- **PRIORITY**: P0
- **DEPENDENCIES**: None
- **FILES TO MODIFY**: `core/face_tracker.py`, `core/video_pipeline.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Change default `min_hits_to_confirm` from 3 to 1. This means a single detection immediately creates a CONFIRMED track. Privacy rationale: current setting leaks first 2 frames of every new face. Add `min_hits_to_confirm` as a configurable parameter.
- **TESTS**: Update tracker tests. Add test that single detection produces confirmed track.
- **BENCHMARK**: Measure false positive increase.
- **ACCEPTANCE CRITERIA**: First-frame redaction for all detected faces. No tentative gap.
- **FAILURE CONDITIONS**: If false positive rate unacceptable, revert to min_hits=2.
- **ROLLBACK CONDITION**: Set min_hits=3.

### TASK-A04
- **TITLE**: Improve Redaction Effectiveness
- **PRIORITY**: P1
- **DEPENDENCIES**: None
- **FILES TO MODIFY**: `core/redactor.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Replace current pixelation formula (`cells_x = max(3, int(rw^0.35))`) with adaptive pixelation (`block_size = max(4, int(0.08 * head_width))`). Add optional Gaussian noise overlay to pixelated region. Ensure feathering is >= 16 pixels.
- **TESTS**: Redaction tests. Visual verification of pixelation strength at various face sizes.
- **BENCHMARK**: Measure re-identification resistance at various face sizes.
- **ACCEPTANCE CRITERIA**: Small faces (20-40px) get strong pixelation. Large faces get proportionally larger blocks.
- **FAILURE CONDITIONS**: If noise overlay causes visual artifacts, make it optional.
- **ROLLBACK CONDITION**: Revert to current formula.

## PHASE B: Kalman Filter Tracker

### TASK-B01
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

### TASK-B02
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

### TASK-B03
- **TITLE**: ByteTrack-style Two-Stage Association
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-B02
- **FILES TO MODIFY**: `core/face_tracker.py`
- **FILES TO CREATE**: None
- **IMPLEMENTATION DETAILS**: Implement ByteTrack's key insight: first associate high-confidence detections, then associate remaining low-confidence detections with unmatched tracks. This recovers partially visible faces that would otherwise be missed.
- **TESTS**: Test with low-confidence detections. Test partial occlusion scenarios.
- **BENCHMARK**: Recall improvement on difficult test videos.
- **ACCEPTANCE CRITERIA**: Low-confidence detections properly associated with existing tracks.
- **FAILURE CONDITIONS**: If false associations increase, tune confidence split threshold.
- **ROLLBACK CONDITION**: Revert to single-stage association.

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

## PHASE D: Boundary and Suspicious Region Detection

### TASK-D01
- **TITLE**: Boundary Strip Detection
- **PRIORITY**: P0
- **DEPENDENCIES**: TASK-B01
- **FILES TO MODIFY**: `core/video_pipeline.py`
- **FILES TO CREATE**: `core/boundary_scanner.py`
- **IMPLEMENTATION DETAILS**: On each frame, extract boundary strips (edges of frame, configurable width). Run SCRFD on these strips to catch faces entering the frame that full-frame detection misses due to zero-padding artifacts. Strip width: ~10% of frame dimension, configurable. Key insight: This is the PRIMARY mechanism for the brand-new face problem. Without a prior track, there is no way to know a face was missed except by proactively scanning likely entry points.
- **TESTS**: Test with faces entering from each edge. Test performance impact.
- **BENCHMARK**: Edge-entry face recall improvement.
- **ACCEPTANCE CRITERIA**: Faces entering from edges detected within 1-2 frames.
- **FAILURE CONDITIONS**: If too slow, reduce strip width or scan frequency.
- **ROLLBACK CONDITION**: Remove boundary scanning.

### TASK-D02
- **TITLE**: Suspicious Region Classification
- **PRIORITY**: P1
- **DEPENDENCIES**: TASK-B01, TASK-D01
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
- **IMPLEMENTATION DETAILS**: When a track's first confirmed frame is not frame 0, search backward up to 20 frames. For each backward frame, generate search ROI from forward-projected position + adaptive padding. Run targeted SCRFD. Validate with cycle consistency (forward-backward < 1px error).
- **TESTS**: Test backward recovery on faces entering frame.
- **BENCHMARK**: Recovery rate, backward search depth.
- **ACCEPTANCE CRITERIA**: Recovers faces up to 10-20 frames before first detection.
- **FAILURE CONDITIONS**: If cycle consistency too strict, relax to 2-3px.
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

## PHASE G: Evaluation & Ablation

### TASK-G01
- **TITLE**: Create Evaluation Framework
- **PRIORITY**: P0
- **DEPENDENCIES**: None
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: `tests/evaluation/eval_framework.py`, `tests/evaluation/metrics.py`
- **IMPLEMENTATION DETAILS**: Create automated evaluation measuring: face recall, missed-face frames, longest unprotected run, privacy leakage frames, recovery success rate, false redaction area, track switches, track fragmentations, FPS, GPU utilization, VRAM usage.
- **TESTS**: Self-test on synthetic videos.
- **BENCHMARK**: N/A
- **ACCEPTANCE CRITERIA**: Reproducible metrics on standard test videos.
- **FAILURE CONDITIONS**: N/A
- **ROLLBACK CONDITION**: N/A

### TASK-G02
- **TITLE**: Ablation Study
- **PRIORITY**: P1
- **DEPENDENCIES**: All implementation tasks
- **FILES TO MODIFY**: None
- **FILES TO CREATE**: `tests/evaluation/ablation.py`
- **IMPLEMENTATION DETAILS**: Incrementally add each component and measure:
  - BASELINE: SCRFD full-frame + current tracker + current redaction
  - +A: Improved tracker (Kalman)
  - +B: Candidate validation
  - +C: Boundary scanning
  - +D: Targeted ROI recovery
  - +E: Mid-track gap interpolation
  - +F: Backward recovery
  - +G: Uncertainty-aware redaction
  - FULL: All components
- **TESTS**: N/A
- **BENCHMARK**: N/A
- **ACCEPTANCE CRITERIA**: Each addition shows measurable improvement on at least one metric.
- **FAILURE CONDITIONS**: N/A
- **ROLLBACK CONDITION**: N/A
