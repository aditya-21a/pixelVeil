# PixelVeil Architecture Diagrams

This document contains the visual architecture of the PixelVeil pipeline, outlining the dual-pass processing, recovery mechanisms, and privacy safety layer.

## 1. High-Level Architecture
The three-pass pipeline strictly separating forward tracking, offline recovery, and redaction rendering.

```mermaid
graph TD
    A[Input Video] --> B[Pass 1: Forward Processing]
    subgraph Pass 1
        B --> C[Full-frame SCRFD]
        C --> D[Candidate Validation]
        D --> E[Forward Tracker]
        E --> F[Track Analysis]
        F --> G[Record Evidence]
    end
    
    G --> H[Pass 2: Offline Recovery]
    subgraph Pass 2
        H --> I[Suspicious Region ROI]
        I --> J[Targeted SCRFD]
        J --> K[Gap Resolution]
        K --> L[Track-start Backward Search]
        L --> M[Final Track Timeline]
    end
    
    M --> N[Pass 3: Redaction]
    subgraph Pass 3
        N --> O[Privacy Safety Layer]
        O --> P[Adaptive Redaction]
        P --> Q[Encode H.264]
    end
    Q --> R[Output Video]
```

**WHY IT EXISTS:** Segregates real-time forward tracking from computationally intensive targeted recovery, ensuring efficiency while maintaining high recall.
**COMPUTATIONAL COST:** GPU constrained for inference, memory constrained during offline recovery phase (buffering tracks).

## 2. Detailed Face Detection Pipeline (Per-Frame)
The logic executed for every single frame during the forward pass.

```mermaid
graph TD
    A[Frame Input] --> B[Decode]
    B --> C[Full-frame SCRFD 640x640]
    C --> D[Basic geometric assessment<br>tiny faces marked UNCERTAIN]
    D --> E[Boundary strip detection policy]
    E --> F[Forward Kalman Tracker update]
    F --> G[Track state classification]
    G --> H[Record Evidence State]
```

**INPUT:** Raw video frame.
**DECISION:** Does this detection or track behavior warrant secondary scrutiny?
**OUTPUT:** Validated full-frame detections and queues for ROI targeting.

## 3. Suspicious Frame Detection & Routing
Criteria for routing regions to the targeted recovery pipeline.

```mermaid
graph TD
    A[Track Analysis] --> B{Suspicion Conditions}
    B --> C[Track enters COASTING<br>detection dropout]
    B --> D[Boundary proximity<br>face near frame edge]
    B --> E[Low confidence detection<br>below threshold but above noise floor]
    B --> F[Rapid scale change]
    B --> G[Track just confirmed<br>trigger backward search]
    
    C --> H[Flag Suspicious]
    D --> H
    E --> H
    F --> H
    G --> H
```

**WHY IT EXISTS:** SCRFD failures are predictable (edges, rapid scaling, occlusions). Identifying these triggers targeted intervention.

## 4. Targeted ROI Recovery
The selective inference pipeline for suspicious regions.

```mermaid
graph TD
    A[Suspicious region identified] --> B[Generate ROI coordinates<br>from track prediction or boundary strip]
    B --> C[Crop region with overlap margin]
    C --> D[Run SCRFD on crop<br>higher effective resolution]
    D --> E[Adjust confidence threshold for cropped context]
    E --> F[Map detections back to full-frame coordinates]
    F --> G[Merge with full-frame detections NMS]
    G --> H[Validate candidates]
```

**RESEARCH EVIDENCE:** Running inference on crops effectively increases resolution, recovering small faces that full-frame (640x640) downsizing obscures. (Validation: A)

## 5. Tracking State Machine
Track lifecycle handling immediate confirmation for strict privacy. The `TENTATIVE` state is bypassed/removed entirely since `min_hits=1`.

```mermaid
stateDiagram-v2
    [*] --> NO_TRACK
    NO_TRACK --> CONFIRMED : detection passes validation (min_hits=1)
    
    CONFIRMED --> CONFIRMED : detected
    CONFIRMED --> COASTING : missed
    
    COASTING --> CONFIRMED : re-detected or recovered
    COASTING --> EXPIRED : max_missing exceeded OR displacement exceeded OR off-screen
```

**DECISION:** `min_hits=1` is chosen because missing a face for even one frame violates the core privacy mandate, favoring false positives over false negatives. The state machine is thus simplified.

## 6. Mid-Track Gap Recovery (Offline)
Interpolation and validation of missed detections between known track states.

```mermaid
graph TD
    A[Detect gap: ✓ ✓ ✓ ? ? ✓ ✓ ✓] --> B[GSI interpolation between known endpoints]
    B --> C[Uncertainty profile: hourglass<br>tight at edges, peak in middle]
    C --> D[Cycle consistency check]
    D --> E{Valid?}
    E -- Yes --> F[Fill gap with interpolated positions]
    E -- No --> G[Fall back to protective redaction<br>at last known + uncertainty expansion]
```

**FAILURE MODE:** Non-linear movement during the gap. Mitigated by uncertainty expansion and cycle consistency.

## 7. Track-Start Recovery (Offline)
Backward searching to catch faces before they were confidently detected.

```mermaid
graph TD
    A[New track confirmed at frame N] --> B[Search backward from N-1 to max 0, N-20]
    B --> C[For each frame:]
    subgraph Iteration
        C --> D[Generate search ROI from forward-projected position + adaptive padding]
        D --> E[Run targeted SCRFD on ROI]
        E --> F{Detected?}
        F -- Yes --> G[Extend track backward, continue]
        F -- No --> H[Apply uncertainty-expanded protective redaction]
        H --> I{Uncertainty too large?}
        I -- Yes --> J[Stop backward search]
        I -- No --> C
    end
    G --> K[Cycle consistency validation<br>forward-backward normalized error]
```

## 8. Privacy/Redaction Pipeline
Final output generation with guaranteed occlusion.

```mermaid
graph TD
    A[Track bbox] --> B[Head expansion<br>25% horizontal, 45% top, 15% bottom]
    B --> C[Uncertainty dilation<br>from tracker covariance, max 1.5x]
    C --> D[Adaptive pixelation<br>block_size = 0.08 × head_width]
    D --> E[Gaussian noise overlay]
    E --> F[Feathered edges<br>min 16px for H.264 macroblock]
    F --> G[Write to output frame]
```

**PARAMETERS:**
- Head expansion: H (25%), T (45%), B (15%) [Validation: C]
- Max dilation: 1.5x [Validation: D]
- Macroblock edge feathering: 16px [Validation: B]

## 9. Compute Architecture (GTX 1650)
Hardware utilization split between GPU and CPU.

```mermaid
graph TD
    subgraph GPU_Tasks [GPU Tasks]
        A[SCRFD inference<br>full-frame + targeted ROI]
        B[Video decode<br>if hardware-accelerated]
    end
    
    subgraph CPU_Tasks [CPU Tasks]
        C[Candidate validation]
        D[Kalman tracker update]
        E[Association Hungarian]
        F[Gap detection / interpolation]
        G[Redaction rendering]
        H[OCR RapidOCR]
        I[PII matching]
        J[Video encoding ffmpeg]
    end
    
    subgraph CPU_GPU_Boundary [CPU-GPU Boundary]
        K[Frame upload for SCRFD]
        L[Detection results download]
        M[ROI crops upload for targeted inference]
    end
    
    GPU_Tasks <--> CPU_GPU_Boundary
    CPU_Tasks <--> CPU_GPU_Boundary
```

## 10. Brand-New Face Problem Flow
Edge case handling for delayed detection of a new face.

```mermaid
graph TD
    subgraph Frame N & N+1
        A[Face exists, SCRFD misses, no track] --> B[Boundary strip detection runs]
        B --> C{Location?}
        C -- Near edge --> D[Boundary ROI queued]
        C -- Center --> E[NO MECHANISM acknowledged gap]
    end
    
    subgraph Frame N+2
        F[SCRFD detects face] --> G[New track created]
        G --> H[Immediately CONFIRMED min_hits=1]
        H --> I[Backward search triggered<br>Searches N+1, N]
        I --> J{Found via targeted ROI?}
        J -- Yes --> K[Track extended backward]
        J -- No --> L[Protective redaction applied at predicted position]
    end
    
    E -.-> F
    D -.-> F
```

**FAILURE MODE:** Central face appearing suddenly (e.g. turning around) missed for 1-2 frames before detection. Mitigated by backward search applying protective redaction at predicted position.
