import math

def _iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0:
        return 0.0

    boxAArea = boxA[2] * boxA[3]
    boxBArea = boxB[2] * boxB[3]
    return interArea / float(boxAArea + boxBArea - interArea)

def _centroid(box):
    return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0

def _distance(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def _linear_sum_assignment(cost_matrix):
    """
    Finds the minimum cost assignment using a recursive branch-and-bound approach.
    Suitable for small N (e.g. <= 15), which is true for face detection in our cases.
    Returns lists of row_indices and col_indices.
    """
    if not cost_matrix or not cost_matrix[0]:
        return [], []
    
    nrows = len(cost_matrix)
    ncols = len(cost_matrix[0])
    
    best_cost = float('inf')
    best_assignment = {}

    # Pad matrix to square to ensure all elements are assigned if possible
    size = max(nrows, ncols)
    padded = [[0.0] * size for _ in range(size)]
    for r in range(nrows):
        for c in range(ncols):
            padded[r][c] = cost_matrix[r][c]
            
    def solve_square(r, current_cost, assigned_cols):
        nonlocal best_cost, best_assignment
        if current_cost >= best_cost:
            return
        if r == size:
            best_cost = current_cost
            best_assignment = assigned_cols.copy()
            return
            
        for c in range(size):
            if c not in assigned_cols:
                cost = padded[r][c]
                assigned_cols[c] = r
                solve_square(r + 1, current_cost + cost, assigned_cols)
                del assigned_cols[c]

    solve_square(0, 0.0, {})
    
    row_ind = []
    col_ind = []
    for c, r in best_assignment.items():
        if r < nrows and c < ncols:
            if cost_matrix[r][c] != float('inf'):
                row_ind.append(r)
                col_ind.append(c)
    
    return row_ind, col_ind


class TrackState:
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    COASTING = "COASTING"
    EXPIRED = "EXPIRED"

class Track:
    _id_counter = 0

    def __init__(self, bbox):
        Track._id_counter += 1
        self.id = Track._id_counter
        self.bbox = list(bbox)  # [x, y, w, h] float or int
        self.velocity = [0.0, 0.0, 0.0, 0.0]
        self.state = TrackState.TENTATIVE
        self.hits = 1
        self.missing_frames = 0
        self.total_displacement = 0.0

    def predict(self, damping, max_displacement, frame_shape):
        """Update bbox using damped velocity."""
        # Damping
        for i in range(4):
            self.velocity[i] *= damping
        
        # Max per-frame displacement cap
        dx, dy, dw, dh = self.velocity
        disp = math.hypot(dx, dy)
        if disp > max_displacement:
            scale = max_displacement / disp
            dx *= scale
            dy *= scale
            self.velocity[0] = dx
            self.velocity[1] = dy
            
        self.bbox[0] += self.velocity[0]
        self.bbox[1] += self.velocity[1]
        self.bbox[2] += self.velocity[2]
        self.bbox[3] += self.velocity[3]
        
        self.total_displacement += math.hypot(self.velocity[0], self.velocity[1])
        
        # Clamp to frame (allow partial off-screen, but keep w, h positive)
        fh, fw = frame_shape[:2]
        self.bbox[0] = max(-self.bbox[2]/2, min(self.bbox[0], fw - self.bbox[2]/2))
        self.bbox[1] = max(-self.bbox[3]/2, min(self.bbox[1], fh - self.bbox[3]/2))
        self.bbox[2] = max(1.0, self.bbox[2])
        self.bbox[3] = max(1.0, self.bbox[3])

    def update(self, bbox, smoothing_alpha):
        """Update with a new detection."""
        new_x, new_y, new_w, new_h = bbox
        # Reconstruct the position from the previous frame before predict() was called
        old_x = self.bbox[0] - self.velocity[0]
        old_y = self.bbox[1] - self.velocity[1]
        old_w = self.bbox[2] - self.velocity[2]
        old_h = self.bbox[3] - self.velocity[3]
        
        sm_x = old_x + smoothing_alpha * (new_x - old_x)
        sm_y = old_y + smoothing_alpha * (new_y - old_y)
        sm_w = old_w + smoothing_alpha * (new_w - old_w)
        sm_h = old_h + smoothing_alpha * (new_h - old_h)
        
        # Velocity is the change in the *smoothed* position vs previous frame
        self.velocity = [
            sm_x - old_x,
            sm_y - old_y,
            sm_w - old_w,
            sm_h - old_h
        ]
        self.bbox = [sm_x, sm_y, sm_w, sm_h]
        
        self.hits += 1
        self.missing_frames = 0
        self.total_displacement = 0.0
        
        if self.state == TrackState.COASTING:
            self.state = TrackState.CONFIRMED


class FaceTracker:
    def __init__(
        self,
        max_missing_frames=15,
        velocity_damping=0.8,
        min_hits_to_confirm=3,
        max_displacement_per_frame=50.0,
        max_total_coast_displacement=200.0,
        smoothing_alpha=1.0 # 1.0 means snap to detection, no EMA dragging
    ):
        self.max_missing_frames = max_missing_frames
        self.velocity_damping = velocity_damping
        self.min_hits_to_confirm = min_hits_to_confirm
        self.max_displacement_per_frame = max_displacement_per_frame
        self.max_total_coast_displacement = max_total_coast_displacement
        self.smoothing_alpha = smoothing_alpha
        
        self.tracks = []
        
        # Diagnostics
        self.metrics = {
            "total_frames": 0,
            "raw_detections": 0,
            "raw_misses": 0,
            "recovered_misses": 0,
            "tracks_created": 0,
            "track_fragmentations": 0, # when a confirmed track expires
            "track_switches": 0, # omitted or approx
            "coasting_frames": 0,
            "association_failures": 0
        }

    def _compute_cost(self, track, det_bbox):
        """
        Compute cost for Hungarian assignment. Returns float('inf') if hard gates are violated.
        """
        t_bbox = track.bbox
        
        # Hard gates
        iou = _iou(t_bbox, det_bbox)
        dist = _distance(_centroid(t_bbox), _centroid(det_bbox))
        
        scale_ratio = max(t_bbox[2]/det_bbox[2], det_bbox[2]/t_bbox[2])
        aspect_t = t_bbox[2] / max(1.0, t_bbox[3])
        aspect_d = det_bbox[2] / max(1.0, det_bbox[3])
        aspect_diff = abs(aspect_t - aspect_d)

        # Gate thresholds
        max_dist = max(t_bbox[2], t_bbox[3]) * 1.5
        
        if dist > max_dist:
            return float('inf')
        if scale_ratio > 2.0:
            return float('inf')
        if aspect_diff > 1.0:
            return float('inf')
        
        # Cost metric: combine normalized distance and (1 - iou)
        norm_dist = dist / max(1.0, max_dist)
        cost = norm_dist + (1.0 - iou)
        return cost

    def update(self, detections, frame_shape):
        self.metrics["total_frames"] += 1
        self.metrics["raw_detections"] += len(detections)
        if len(detections) == 0:
            self.metrics["raw_misses"] += 1

        # Predict active tracks
        for trk in self.tracks:
            trk.predict(self.velocity_damping, self.max_displacement_per_frame, frame_shape)
            
        # Build cost matrix
        cost_matrix = []
        for trk in self.tracks:
            row = []
            for det in detections:
                row.append(self._compute_cost(trk, det))
            cost_matrix.append(row)
            
        row_ind, col_ind = _linear_sum_assignment(cost_matrix)
        
        unmatched_tracks = set(range(len(self.tracks))) - set(row_ind)
        unmatched_dets = set(range(len(detections))) - set(col_ind)
        
        self.metrics["association_failures"] += len(unmatched_tracks) + len(unmatched_dets)

        # Update matched tracks
        for r, c in zip(row_ind, col_ind):
            trk = self.tracks[r]
            trk.update(detections[c], self.smoothing_alpha)
            if trk.state == TrackState.TENTATIVE and trk.hits >= self.min_hits_to_confirm:
                trk.state = TrackState.CONFIRMED

        # Handle unmatched tracks
        for r in unmatched_tracks:
            trk = self.tracks[r]
            trk.missing_frames += 1
            if trk.state == TrackState.TENTATIVE:
                # TENTATIVE expires instantly on miss to prevent ghosting false positives
                trk.state = TrackState.EXPIRED
            elif trk.state == TrackState.CONFIRMED:
                trk.state = TrackState.COASTING
                
            if trk.state == TrackState.COASTING:
                self.metrics["coasting_frames"] += 1
                self.metrics["recovered_misses"] += 1
                # Check expiration limits
                if trk.missing_frames > self.max_missing_frames:
                    trk.state = TrackState.EXPIRED
                elif trk.total_displacement > self.max_total_coast_displacement:
                    trk.state = TrackState.EXPIRED
                elif trk.bbox[2] > frame_shape[1] or trk.bbox[3] > frame_shape[0]:
                    trk.state = TrackState.EXPIRED
                elif trk.bbox[0] < -trk.bbox[2] or trk.bbox[0] > frame_shape[1]:
                    # Center completely off screen
                    trk.state = TrackState.EXPIRED

            if trk.state == TrackState.EXPIRED and trk.hits >= self.min_hits_to_confirm:
                self.metrics["track_fragmentations"] += 1

        # Create new tracks for unmatched detections
        for c in unmatched_dets:
            new_trk = Track(detections[c])
            new_trk.hits = 1 
            if self.min_hits_to_confirm <= 1:
                new_trk.state = TrackState.CONFIRMED
            else:
                new_trk.state = TrackState.TENTATIVE
            self.tracks.append(new_trk)
            self.metrics["tracks_created"] += 1
            
        # Filter out EXPIRED tracks
        self.tracks = [t for t in self.tracks if t.state != TrackState.EXPIRED]
        
        # Return bounding boxes for all active tracks
        output_boxes = []
        for t in self.tracks:
            x, y, w, h = t.bbox
            output_boxes.append((int(x), int(y), int(w), int(h)))
            
        return output_boxes
