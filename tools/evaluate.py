import math
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

@dataclass
class GroundTruthFace:
    face_id: str
    bbox: Tuple[float, float, float, float]  # (x, y, w, h)
    visibility: str = "VISIBLE"  # "VISIBLE", "OCCLUDED", "OUT_OF_FRAME"
    edge_distance: float = 0.0
    motion: float = 0.0
    
    @property
    def size_bucket(self) -> str:
        area = self.bbox[2] * self.bbox[3]
        if area < 32 * 32:
            return "tiny"
        elif area < 96 * 96:
            return "small"
        elif area < 256 * 256:
            return "medium"
        else:
            return "large"

@dataclass
class SystemOutputFace:
    bbox: Tuple[float, float, float, float]
    source_of_detection: str = "detector"
    source_of_recovered_protection: str = "none"
    confidence: float = 1.0

@dataclass
class SystemOutputRegion:
    bbox: Tuple[float, float, float, float]  # Redacted region

def box_intersection(boxA, boxB) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])
    return max(0.0, float(xB - xA)) * max(0.0, float(yB - yA))

def calculate_iou(boxA, boxB) -> float:
    interArea = box_intersection(boxA, boxB)
    if interArea == 0:
        return 0.0
    boxAArea = boxA[2] * boxA[3]
    boxBArea = boxB[2] * boxB[3]
    return interArea / float(boxAArea + boxBArea - interArea)

def calculate_center_error(gt_box, pred_box) -> float:
    gt_cx = gt_box[0] + gt_box[2] / 2
    gt_cy = gt_box[1] + gt_box[3] / 2
    pred_cx = pred_box[0] + pred_box[2] / 2
    pred_cy = pred_box[1] + pred_box[3] / 2
    dist = math.hypot(gt_cx - pred_cx, gt_cy - pred_cy)
    norm = max(gt_box[2], gt_box[3])
    return float(dist / norm) if norm > 0 else float('inf')

def calculate_coverage_rate(gt_box, regions: List[Tuple[float, float, float, float]]) -> float:
    """Calculate the percentage of gt_box covered by the union of redacted regions."""
    gt_area = gt_box[2] * gt_box[3]
    if gt_area == 0:
        return 1.0
        
    # Render onto a mask to handle overlapping regions correctly
    x, y, w, h = map(int, [math.floor(gt_box[0]), math.floor(gt_box[1]), math.ceil(gt_box[2]), math.ceil(gt_box[3])])
    if w <= 0 or h <= 0:
        return 1.0
        
    mask = np.zeros((h, w), dtype=np.uint8)
    
    for r in regions:
        rx, ry, rw, rh = r
        # Find intersection relative to gt_box
        ix1 = max(0, int(rx - x))
        iy1 = max(0, int(ry - y))
        ix2 = min(w, int(rx + rw - x))
        iy2 = min(h, int(ry + rh - y))
        
        if ix1 < ix2 and iy1 < iy2:
            mask[iy1:iy2, ix1:ix2] = 1
            
    covered_area = np.sum(mask)
    return float(covered_area) / float(w * h)

class Evaluator:
    def __init__(self, coverage_threshold=0.95):
        self.coverage_threshold = coverage_threshold
        self.metrics = {
            "bbox_iou": [],
            "center_error": [],
            "coverage_rate": [],
            "privacy_leakage_frames": 0,
            "false_positive_area": 0.0,
            "false_redaction_duration_frames": 0,
            "longest_unprotected_run": {},
            "first_frame_leakage": {}
        }
        self.buckets = {
            "size": {},
            "edge_distance": {},
            "occlusion": {},
            "motion": {},
            "source_of_detection": {},
            "source_of_recovered_protection": {}
        }
        self._current_run = {}
        self._face_seen = set()
        
    def _add_to_bucket(self, category: str, bucket_key: str, metric_name: str, value: float):
        if bucket_key not in self.buckets[category]:
            self.buckets[category][bucket_key] = {metric_name: []}
        if metric_name not in self.buckets[category][bucket_key]:
            self.buckets[category][bucket_key][metric_name] = []
        self.buckets[category][bucket_key][metric_name].append(value)
        
    def evaluate_frame(self, frame_idx: int, gt_faces: List[GroundTruthFace], 
                       system_faces: List[SystemOutputFace], system_regions: List[SystemOutputRegion]):
        
        # 1. Detection Performance (Matching GT to System Outputs)
        matched_system = set()
        for gt in gt_faces:
            if gt.visibility == "OUT_OF_FRAME":
                continue
                
            best_iou = 0.0
            best_sys_face = None
            best_sys_idx = -1
            
            for i, sys_face in enumerate(system_faces):
                if i in matched_system:
                    continue
                iou = calculate_iou(gt.bbox, sys_face.bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_sys_face = sys_face
                    best_sys_idx = i
                    
            if best_sys_idx != -1:
                matched_system.add(best_sys_idx)
                c_err = calculate_center_error(gt.bbox, best_sys_face.bbox)
                self.metrics["bbox_iou"].append(best_iou)
                self.metrics["center_error"].append(c_err)
                
                # Bucketing Detection Metrics
                self._add_to_bucket("size", gt.size_bucket, "bbox_iou", best_iou)
                self._add_to_bucket("occlusion", gt.visibility, "bbox_iou", best_iou)
                self._add_to_bucket("source_of_detection", best_sys_face.source_of_detection, "bbox_iou", best_iou)
                
            else:
                self.metrics["bbox_iou"].append(0.0)
                self._add_to_bucket("size", gt.size_bucket, "bbox_iou", 0.0)
                self._add_to_bucket("occlusion", gt.visibility, "bbox_iou", 0.0)

            # 2. Privacy Coverage
            if gt.visibility == "VISIBLE":
                regions_bboxes = [r.bbox for r in system_regions]
                cov_rate = calculate_coverage_rate(gt.bbox, regions_bboxes)
                self.metrics["coverage_rate"].append(cov_rate)
                
                self._add_to_bucket("size", gt.size_bucket, "coverage_rate", cov_rate)
                
                if best_sys_face:
                    self._add_to_bucket("source_of_recovered_protection", best_sys_face.source_of_recovered_protection, "coverage_rate", cov_rate)
                
                if cov_rate < self.coverage_threshold:
                    self.metrics["privacy_leakage_frames"] += 1
                    
                    # Longest unprotected run logic
                    if gt.face_id not in self._current_run:
                        self._current_run[gt.face_id] = 0
                    self._current_run[gt.face_id] += 1
                    
                    if gt.face_id not in self.metrics["longest_unprotected_run"]:
                        self.metrics["longest_unprotected_run"][gt.face_id] = 0
                    self.metrics["longest_unprotected_run"][gt.face_id] = max(
                        self.metrics["longest_unprotected_run"][gt.face_id],
                        self._current_run[gt.face_id]
                    )
                    
                    # First frame leakage
                    if gt.face_id not in self._face_seen:
                        self.metrics["first_frame_leakage"][gt.face_id] = True
                else:
                    self._current_run[gt.face_id] = 0
                    if gt.face_id not in self.metrics["first_frame_leakage"]:
                        self.metrics["first_frame_leakage"][gt.face_id] = False

            self._face_seen.add(gt.face_id)
            
        # 3. False Positives
        frame_fp_area = 0.0
        has_fp_this_frame = False
        for region in system_regions:
            # check if region overlaps with ANY ground truth face
            overlaps = False
            for gt in gt_faces:
                if gt.visibility == "OUT_OF_FRAME": continue
                if calculate_iou(region.bbox, gt.bbox) > 0:
                    overlaps = True
                    break
            
            if not overlaps:
                has_fp_this_frame = True
                frame_fp_area += (region.bbox[2] * region.bbox[3])
                
        self.metrics["false_positive_area"] += frame_fp_area
        if has_fp_this_frame:
            self.metrics["false_redaction_duration_frames"] += 1
            
    def get_summary(self):
        summary = {
            "mean_bbox_iou": np.mean(self.metrics["bbox_iou"]) if self.metrics["bbox_iou"] else 0.0,
            "mean_center_error": np.mean(self.metrics["center_error"]) if self.metrics["center_error"] else 0.0,
            "mean_coverage_rate": np.mean(self.metrics["coverage_rate"]) if self.metrics["coverage_rate"] else 0.0,
            "privacy_leakage_frames": self.metrics["privacy_leakage_frames"],
            "false_positive_area": self.metrics["false_positive_area"],
            "false_redaction_duration_frames": self.metrics["false_redaction_duration_frames"],
            "max_unprotected_run_overall": max(self.metrics["longest_unprotected_run"].values()) if self.metrics["longest_unprotected_run"] else 0,
            "first_frame_leakage_count": sum(1 for leaked in self.metrics["first_frame_leakage"].values() if leaked),
            "buckets": {}
        }
        
        # Aggregate buckets
        for cat, cat_dict in self.buckets.items():
            summary["buckets"][cat] = {}
            for bucket_key, metrics_dict in cat_dict.items():
                summary["buckets"][cat][bucket_key] = {}
                for m_name, vals in metrics_dict.items():
                    summary["buckets"][cat][bucket_key][f"mean_{m_name}"] = np.mean(vals) if vals else 0.0
                    
        return summary
