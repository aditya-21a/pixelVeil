import unittest
from tools.evaluate import (
    GroundTruthFace,
    SystemOutputFace,
    SystemOutputRegion,
    Evaluator,
    calculate_iou,
    calculate_center_error,
    calculate_coverage_rate
)

class TestEvaluationMetrics(unittest.TestCase):
    
    def test_calculate_iou(self):
        boxA = (0, 0, 100, 100)
        boxB = (50, 50, 100, 100)
        # Intersection is 50x50 = 2500
        # Union is 10000 + 10000 - 2500 = 17500
        # IoU = 2500 / 17500 = 1/7 ~= 0.142857
        iou = calculate_iou(boxA, boxB)
        self.assertAlmostEqual(iou, 1/7, places=5)
        
        # Disjoint
        boxC = (200, 200, 50, 50)
        self.assertEqual(calculate_iou(boxA, boxC), 0.0)
        
        # Identical
        self.assertEqual(calculate_iou(boxA, boxA), 1.0)
        
    def test_calculate_center_error(self):
        gt_box = (0, 0, 100, 100) # center is (50, 50), max(w,h) = 100
        pred_box = (25, 25, 50, 50) # center is (50, 50)
        
        err = calculate_center_error(gt_box, pred_box)
        self.assertEqual(err, 0.0)
        
        pred_box2 = (0, 50, 100, 100) # center is (50, 100)
        # dist is 50. Normalized is 50 / 100 = 0.5
        err2 = calculate_center_error(gt_box, pred_box2)
        self.assertEqual(err2, 0.5)

    def test_calculate_coverage_rate(self):
        gt_box = (0, 0, 100, 100) # Area 10000
        
        # Single fully covering region
        regions = [(0, 0, 100, 100)]
        self.assertEqual(calculate_coverage_rate(gt_box, regions), 1.0)
        
        # Single partially covering region
        regions = [(0, 0, 50, 100)] # covers left half (5000)
        self.assertEqual(calculate_coverage_rate(gt_box, regions), 0.5)
        
        # Multiple overlapping regions
        regions = [
            (0, 0, 50, 100), # covers left half
            (25, 0, 50, 100) # covers from 25 to 75
        ]
        # Total coverage should be from 0 to 75 -> 75%
        self.assertEqual(calculate_coverage_rate(gt_box, regions), 0.75)
        
        # Disjoint region
        regions = [(200, 200, 50, 50)]
        self.assertEqual(calculate_coverage_rate(gt_box, regions), 0.0)
        
    def test_evaluator_integration(self):
        evaluator = Evaluator(coverage_threshold=0.95)
        
        # Frame 0: 1 GT face, detected and redacted properly
        gt_faces = [GroundTruthFace(face_id="f1", bbox=(10, 10, 100, 100), visibility="VISIBLE")]
        sys_faces = [SystemOutputFace(bbox=(10, 10, 100, 100))]
        sys_regions = [SystemOutputRegion(bbox=(5, 5, 110, 110))]
        
        evaluator.evaluate_frame(0, gt_faces, sys_faces, sys_regions)
        
        summary = evaluator.get_summary()
        self.assertEqual(summary["privacy_leakage_frames"], 0)
        self.assertEqual(summary["false_positive_area"], 0.0) # The region overlaps GT face
        
        # Frame 1: GT face moves, system misses detection but region still covers some (privacy leak)
        gt_faces = [GroundTruthFace(face_id="f1", bbox=(50, 50, 100, 100), visibility="VISIBLE")]
        sys_faces = [] # Detection missed
        sys_regions = [SystemOutputRegion(bbox=(5, 5, 110, 110))] # Redaction lags
        
        evaluator.evaluate_frame(1, gt_faces, sys_faces, sys_regions)
        summary = evaluator.get_summary()
        self.assertEqual(summary["privacy_leakage_frames"], 1)
        self.assertEqual(summary["false_redaction_duration_frames"], 0) # Still overlaps so not a FP
        
        # Frame 2: Completely false positive detection and redaction
        gt_faces = [GroundTruthFace(face_id="f1", bbox=(300, 300, 100, 100), visibility="VISIBLE")]
        sys_faces = [SystemOutputFace(bbox=(10, 10, 50, 50))]
        sys_regions = [SystemOutputRegion(bbox=(10, 10, 50, 50))] # FP region
        
        evaluator.evaluate_frame(2, gt_faces, sys_faces, sys_regions)
        summary = evaluator.get_summary()
        self.assertEqual(summary["privacy_leakage_frames"], 2)
        self.assertEqual(summary["false_positive_area"], 2500.0)
        self.assertEqual(summary["false_redaction_duration_frames"], 1)

if __name__ == '__main__':
    unittest.main()
