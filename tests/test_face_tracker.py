import pytest
from core.face_tracker import FaceTracker, TrackState

def test_tentative_creation_and_expiration():
    tracker = FaceTracker()
    frame_shape = (500, 500, 3)
    
    # Frame 1: 1 detection
    out = tracker.update([(100, 100, 50, 50)], frame_shape)
    assert len(out) == 1
    assert len(tracker.tracks) == 1
    assert tracker.tracks[0].state == TrackState.TENTATIVE
    
    # Frame 2: Missed
    out = tracker.update([], frame_shape)
    assert len(out) == 0
    assert len(tracker.tracks) == 0
    
def test_confirmation_and_coasting():
    tracker = FaceTracker(min_hits_to_confirm=3, max_missing_frames=2)
    frame_shape = (500, 500, 3)
    
    # Frame 1: Tentative
    tracker.update([(100, 100, 50, 50)], frame_shape)
    assert tracker.tracks[0].state == TrackState.TENTATIVE
    
    # Frame 2: Tentative
    tracker.update([(102, 102, 50, 50)], frame_shape)
    assert tracker.tracks[0].state == TrackState.TENTATIVE
    
    # Frame 3: Confirmed
    tracker.update([(104, 104, 50, 50)], frame_shape)
    assert tracker.tracks[0].state == TrackState.CONFIRMED
    
    # Frame 4: Missed (Coasting 1)
    out = tracker.update([], frame_shape)
    assert len(out) == 1
    assert tracker.tracks[0].state == TrackState.COASTING
    
    # Frame 5: Missed (Coasting 2)
    out = tracker.update([], frame_shape)
    assert len(out) == 1
    assert tracker.tracks[0].state == TrackState.COASTING
    
    # Frame 6: Missed (Expired)
    out = tracker.update([], frame_shape)
    assert len(out) == 0
    assert len(tracker.tracks) == 0

def test_reacquisition():
    tracker = FaceTracker(min_hits_to_confirm=2)
    frame_shape = (500, 500, 3)
    
    tracker.update([(100, 100, 50, 50)], frame_shape)
    tracker.update([(100, 100, 50, 50)], frame_shape) # Confirmed
    
    # Miss for 2 frames
    tracker.update([], frame_shape)
    tracker.update([], frame_shape)
    
    assert len(tracker.tracks) == 1
    assert tracker.tracks[0].state == TrackState.COASTING
    
    # Reacquire
    tracker.update([(105, 105, 50, 50)], frame_shape)
    assert len(tracker.tracks) == 1
    assert tracker.tracks[0].state == TrackState.CONFIRMED

def test_hard_gates_reject_implausible():
    tracker = FaceTracker(min_hits_to_confirm=2)
    frame_shape = (500, 500, 3)
    
    tracker.update([(100, 100, 50, 50)], frame_shape)
    tracker.update([(100, 100, 50, 50)], frame_shape) # Confirmed
    
    # New detection far away should NOT connect to this track
    tracker.update([(400, 400, 50, 50)], frame_shape)
    
    assert len(tracker.tracks) == 2
    # The first one should be coasting because it didn't match
    assert tracker.tracks[0].state == TrackState.COASTING
    # The second one is tentative
    assert tracker.tracks[1].state == TrackState.TENTATIVE

def test_negative_reacquisition_leaves_and_enters():
    tracker = FaceTracker(min_hits_to_confirm=2, max_missing_frames=2)
    frame_shape = (500, 500, 3)
    
    # Person A
    tracker.update([(100, 100, 50, 50)], frame_shape)
    tracker.update([(100, 100, 50, 50)], frame_shape) # Confirmed
    
    # Leaves frame for > max_missing_frames
    tracker.update([], frame_shape)
    tracker.update([], frame_shape)
    tracker.update([], frame_shape) # Expired
    
    assert len(tracker.tracks) == 0
    
    # Person B enters same location
    tracker.update([(100, 100, 50, 50)], frame_shape)
    assert len(tracker.tracks) == 1
    assert tracker.tracks[0].state == TrackState.TENTATIVE

def test_detector_replay_various_dropouts():
    # Simulate a face moving steadily left-to-right
    # and test 1, 5, 10, 15 frame dropouts
    frame_shape = (1080, 1920, 3)
    
    for dropout_len in [1, 5, 10, 15]:
        tracker = FaceTracker(min_hits_to_confirm=2, max_missing_frames=15, velocity_damping=1.0)
        
        # Warmup: 5 frames of steady movement
        for i in range(5):
            x = 100 + i * 10
            tracker.update([(x, 500, 100, 100)], frame_shape)
            
        assert len(tracker.tracks) == 1
        assert tracker.tracks[0].state == TrackState.CONFIRMED
        
        # Dropout
        for i in range(dropout_len):
            out = tracker.update([], frame_shape)
            assert len(out) == 1
            assert tracker.tracks[0].state == TrackState.COASTING
            
        # Verify it coasted in the right direction
        final_box = out[0]
        # x should be roughly 100 + 4*10 + dropout_len * 10
        expected_x = 140 + dropout_len * 10
        assert abs(final_box[0] - expected_x) < 5
        
        # Reacquire
        reacquire_x = expected_x + 10
        tracker.update([(reacquire_x, 500, 100, 100)], frame_shape)
        assert len(tracker.tracks) == 1
        assert tracker.tracks[0].state == TrackState.CONFIRMED
