import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from backend.analysis.event_verifier import EventVerifier
from backend.analysis.suspicion import SuspicionAnalyzer
from backend.core.config import ConfigurationError, Settings
from backend.storage.local_storage import LocalStorageService
from backend.tracking.trajectory import TrajectoryTracker


class ConfigurationTests(unittest.TestCase):
    def test_invalid_confidence_is_rejected(self):
        settings = Settings()
        values = settings.values
        values["vehicle_confidence"] = 1.5
        with self.assertRaises(ConfigurationError):
            Settings.validate(values, settings.rules)

    def test_roi_is_persisted_and_validated(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            settings = Settings()
            settings.roi_path = Path(temp) / "roi.json"
            source_key = "a" * 64
            saved = settings.set_roi(source_key, {"enabled": True, "points": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]})
            self.assertTrue(saved["enabled"])
            self.assertEqual(settings.get_roi(source_key)["points"], saved["points"])
            with self.assertRaises(ConfigurationError):
                settings.set_roi("b" * 64, {"enabled": True, "points": [[0, 0], [0.5, 0.5], [1, 1]]})


class RoiTests(unittest.TestCase):
    def test_filter_uses_bbox_center_and_normalized_coordinates(self):
        from backend.core.pipeline import Pipeline

        pipeline = object.__new__(Pipeline)
        pipeline._roi = {"enabled": True, "points": [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]]}
        detections = [
            {"bbox": [10, 10, 30, 30], "track_id": 1},
            {"bbox": [70, 10, 90, 30], "track_id": 2},
        ]
        selected = pipeline._filter_roi(detections, 100, 100)
        self.assertEqual([item["track_id"] for item in selected], [1])


class StorageTests(unittest.TestCase):
    def test_event_survives_service_recreation_and_review(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            first = LocalStorageService(Path(temp))
            event = first.create_event(source="test.mp4", related_track_ids=[3, 4], reasons=["bbox overlap"])
            first.update_event(event["event_id"], status="REJECTED", notes="false alarm")
            second = LocalStorageService(Path(temp))
            restored = second.get_event(event["event_id"])
            self.assertEqual(restored["status"], "REJECTED")
            self.assertEqual(restored["manual_review_status"], "REJECTED")
            self.assertEqual(restored["notes"], "false alarm")
            self.assertEqual(second.list_events()[1], 1)

    def test_csv_export_writes_header(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            service = LocalStorageService(Path(temp))
            event = service.create_event(source="sample.mp4")
            exported = service.export_events([event], "csv")
            self.assertIn("event_id", exported.read_text(encoding="utf-8-sig"))


class VerificationTests(unittest.TestCase):
    def test_accident_signals_never_auto_confirm(self):
        verifier = EventVerifier({"verifier_min_confidence": 0.55,
                                  "verifier_min_positive_frames": 2,
                                  "verifier_window_seconds": 3,
                                  "uncertain_after_seconds": 2.5,
                                  "verifier_sample_interval_seconds": 0.5})
        first = verifier.add(1.0, [{"class_name": "accident", "confidence": 0.9}])
        self.assertEqual(first["status"], "SUSPECTED")
        repeated_too_soon = verifier.add(1.2, [{"class_name": "accident", "confidence": 0.7}])
        self.assertFalse(repeated_too_soon["sampled"])
        second = verifier.add(1.6, [{"class_name": "accident", "confidence": 0.7}])
        self.assertEqual(second["status"], "SUSPECTED")
        self.assertTrue(second["review_ready"])
        elapsed = verifier.add(3.6, [{"class_name": "accident", "confidence": 0.8}])
        self.assertEqual(elapsed["status"], "UNCERTAIN")

    def test_repeated_positive_samples_are_ready_for_human_review_never_confirmed(self):
        verifier = EventVerifier({"verifier_min_confidence": 0.55, "verifier_min_positive_frames": 2,
                                  "verifier_window_seconds": 3, "accident_verification_timeout_seconds": 3,
                                  "verifier_sample_interval_seconds": 0.5})
        tracks = [{"track_id": 1, "bbox": [10, 10, 30, 30]}]
        prediction = [{"class_name": "accident", "confidence": 0.8, "bbox": [0, 0, 40, 40]}]
        verifier.add(0, prediction, vehicle_tracks=tracks)
        ready = verifier.add(0.5, prediction, vehicle_tracks=tracks)
        self.assertEqual(ready["status"], "READY_FOR_REVIEW")
        self.assertNotEqual(ready["status"], "CONFIRMED")

    def test_timeout_is_three_seconds_from_first_sample(self):
        verifier = EventVerifier({"verifier_min_confidence": 0.55, "verifier_window_seconds": 3, "accident_verification_timeout_seconds": 3,
                                  "verifier_min_positive_frames": 2, "verifier_sample_interval_seconds": 0.5})
        tracks = [{"track_id": 1, "bbox": [0, 0, 10, 10]}]
        self.assertEqual(verifier.add(0, [], vehicle_tracks=tracks)["status"], "SUSPECTED")
        self.assertEqual(verifier.add(2.9, [], vehicle_tracks=tracks)["status"], "SUSPECTED")
        self.assertEqual(verifier.add(3.0, [], vehicle_tracks=tracks)["status"], "UNCERTAIN")

    def test_accident_detection_must_be_related_to_the_event_tracks(self):
        verifier = EventVerifier({"verifier_min_confidence": 0.55,
                                  "verifier_min_positive_frames": 1,
                                  "verifier_window_seconds": 3,
                                  "uncertain_after_seconds": 2.5,
                                  "verifier_sample_interval_seconds": 0.5})
        vehicle = {"track_id": 7, "bbox": [10, 10, 30, 30]}
        unrelated = verifier.add(0, [{"class_name": "accident", "confidence": 0.95,
                                      "bbox": [80, 80, 100, 100]}], vehicle_tracks=[vehicle])
        self.assertEqual(unrelated["positive_observations"], 0)
        related = verifier.add(0.5, [{"class_name": "accident", "confidence": 0.75,
                                      "bbox": [0, 0, 40, 40]}], vehicle_tracks=[vehicle])
        self.assertEqual(related["related_track_ids"], [7])
        self.assertEqual(related["positive_observations"], 1)

    def test_uncertain_timeout_uses_total_event_time_not_sliding_window(self):
        verifier = EventVerifier({"verifier_min_confidence": 0.55,
                                  "verifier_min_positive_frames": 2,
                                  "verifier_window_seconds": 1.0,
                                  "uncertain_after_seconds": 2.5,
                                  "verifier_sample_interval_seconds": 0.5})
        result = None
        for timestamp in (0, 0.5, 1.0, 1.5, 2.0, 2.5):
            result = verifier.add(timestamp, [], vehicle_tracks=[{"track_id": 1, "bbox": [0, 0, 2, 2]}])
        self.assertEqual(result["status"], "UNCERTAIN")

    def test_stable_close_tracks_do_not_raise_a_trigger(self):
        analyzer = SuspicionAnalyzer({"suspicion_iou_threshold": 0.08,
                                      "suspicion_distance_ratio": 0.5,
                                      "suspicion_consecutive_frames": 3})
        detections = [
            {"bbox": [10, 10, 40, 40], "track_id": 1},
            {"bbox": [44, 10, 74, 40], "track_id": 2},
        ]
        self.assertIsNone(analyzer.analyze(detections, 100, 100, 1))
        self.assertIsNone(analyzer.analyze(detections, 100, 100, 2))
        self.assertIsNone(analyzer.analyze(detections, 100, 100, 3))

    def test_approaching_tracks_raise_a_verification_trigger(self):
        analyzer = SuspicionAnalyzer({"suspicion_iou_threshold": 0.08,
                                      "suspicion_distance_ratio": 0.5,
                                      "suspicion_consecutive_frames": 3})
        frames = [
            [{"bbox": [10, 10, 30, 30], "track_id": 1}, {"bbox": [80, 10, 100, 30], "track_id": 2}],
            [{"bbox": [20, 10, 40, 30], "track_id": 1}, {"bbox": [65, 10, 85, 30], "track_id": 2}],
            [{"bbox": [30, 10, 50, 30], "track_id": 1}, {"bbox": [50, 10, 70, 30], "track_id": 2}],
            [{"bbox": [35, 10, 55, 30], "track_id": 1}, {"bbox": [45, 10, 65, 30], "track_id": 2}],
        ]
        for index, detections in enumerate(frames[:3], 1):
            self.assertIsNone(analyzer.analyze(detections, 100, 100, index, index / 10))
        result = analyzer.analyze(frames[3], 100, 100, 4, 0.4)
        self.assertEqual(result["track_ids"], [1, 2])
        self.assertIn("frame_index", result)

    def test_two_separate_interactions_can_trigger_two_review_events(self):
        analyzer = SuspicionAnalyzer({"suspicion_iou_threshold": 0.08,
                                      "suspicion_distance_ratio": 0.25,
                                      "suspicion_consecutive_frames": 3})
        frames = [
            [(1, 0, 10), (2, 120, 10), (3, 160, 150), (4, 280, 150)],
            [(1, 10, 10), (2, 110, 10), (3, 170, 150), (4, 270, 150)],
            [(1, 20, 10), (2, 100, 10), (3, 180, 150), (4, 260, 150)],
            [(1, 30, 10), (2, 90, 10), (3, 190, 150), (4, 250, 150)],
        ]
        result = None
        for index, frame in enumerate(frames, 1):
            detections = [{"track_id": track_id, "bbox": [x, y, x + 20, y + 20]} for track_id, x, y in frame]
            result = analyzer.analyze(detections, 400, 200, index, index / 10)
        self.assertEqual(len(result["concurrent"]), 2)


class TrajectoryTests(unittest.TestCase):
    @staticmethod
    def detection(track_id, x):
        return {"track_id": track_id, "bbox": [x, 10, x + 10, 20], "class_name": "car", "confidence": 0.9}

    def test_tracks_keep_separate_observed_bottom_center_histories(self):
        tracker = TrajectoryTracker()
        tracker.update([self.detection(1, 0), self.detection(2, 40)], frame_index=1, timestamp=0.0)
        tracker.update([self.detection(1, 10), self.detection(2, 50)], frame_index=2, timestamp=0.1)
        data = tracker.update([self.detection(1, 20), self.detection(2, 60)], frame_index=3, timestamp=0.2)
        self.assertEqual(data[1][-1]["center_x"], 25)
        self.assertEqual(data[1][-1]["center_y"], 20)
        self.assertEqual(data[2][-1]["center_x"], 65)
        self.assertEqual(tracker.direction(1), (1.0, 0.0))

    def test_long_occlusion_breaks_the_observed_segment_and_reset_clears(self):
        tracker = TrajectoryTracker(max_gap_seconds=0.5)
        tracker.update([self.detection(1, 0)], frame_index=1, timestamp=0.0)
        tracker.update([self.detection(1, 10)], frame_index=2, timestamp=0.1)
        tracker.update([], frame_index=3, timestamp=0.9)
        history = tracker.update([self.detection(1, 40)], frame_index=4, timestamp=1.0)[1]
        self.assertIn("missing", [point["observed_status"] for point in history])
        self.assertIsNone(tracker.direction(1))
        tracker.reset()
        self.assertEqual(tracker.snapshot(), {})

    def test_history_is_bounded(self):
        tracker = TrajectoryTracker(max_points=3)
        for index in range(8):
            tracker.update([self.detection(1, index)], frame_index=index, timestamp=index / 10)
        self.assertEqual(len(tracker.snapshot()[1]), 3)


class PipelineIntegrationTests(unittest.TestCase):
    def test_collision_candidate_waits_for_repeated_observed_pair_before_activation(self):
        from backend.core.pipeline import Pipeline

        pipeline = object.__new__(Pipeline)
        pipeline.rules = {"suspicion_iou_threshold": 0.08, "suspicion_distance_ratio": 0.16,
                          "candidate_min_observations": 3, "candidate_observation_seconds": 0.6,
                          "candidate_max_age_seconds": 2, "candidate_max_track_gap_seconds": 0.75}
        pipeline._pair_candidates = {}
        pipeline._latest_suspicion = None
        pipeline._diagnostics_enabled = False
        results = []
        for index in range(3):
            t = index * 0.3
            detections = [{"track_id": 1, "bbox": [10 + index, 10, 30 + index, 30], "confidence": 0.8},
                          {"track_id": 2, "bbox": [20 - index, 10, 40 - index, 30], "confidence": 0.8}]
            history = lambda x, y: [{"timestamp": t - 0.6 + index * 0.3, "observed_status": "observed"} for _ in range(3)]
            trajectories = {1: history(0, 0), 2: history(0, 0)}
            results.append(pipeline._advance_pair_candidates(detections, trajectories, 100, 100, t, index + 1))
        self.assertIsNone(results[0])
        self.assertIsNone(results[1])
        self.assertEqual(results[2]["track_ids"], [1, 2])

    def test_candidate_does_not_activate_after_long_observation_gap(self):
        from backend.core.pipeline import Pipeline

        pipeline = object.__new__(Pipeline)
        pipeline.rules = {"suspicion_iou_threshold": 0.08, "suspicion_distance_ratio": 0.16,
                          "candidate_min_observations": 2, "candidate_observation_seconds": 0.1,
                          "candidate_max_age_seconds": 2, "candidate_max_track_gap_seconds": 0.2}
        pipeline._pair_candidates = {}
        pipeline._latest_suspicion = None
        pipeline._diagnostics_enabled = False
        detections = [{"track_id": 1, "bbox": [10, 10, 30, 30]}, {"track_id": 2, "bbox": [20, 10, 40, 30]}]
        trajectory = {track_id: [{"timestamp": 0, "observed_status": "observed"},
                                 {"timestamp": 1, "observed_status": "observed"}] for track_id in (1, 2)}
        self.assertIsNone(pipeline._advance_pair_candidates(detections, trajectory, 100, 100, 0, 1))
        self.assertIsNone(pipeline._advance_pair_candidates(detections, trajectory, 100, 100, 1, 2))

    def test_video_pipeline_stores_review_events_without_auto_confirmation(self):
        from backend.core.pipeline import Pipeline

        class FakeModels:
            vehicle_inference_ms = 0.0
            accident_inference_ms = 0.0

            def __init__(self):
                self.index = 0

            def reset_tracking(self):
                self.index = 0

            def vehicle_track(self, frame, *, conf, imgsz):
                index = self.index
                self.index += 1
                first_x, second_x = 10 + 2 * index, 110 - 2 * index
                return [
                    {"track_id": 1, "bbox": [first_x, 20, first_x + 30, 60], "class_name": "car", "class_id": 1, "confidence": 0.9},
                    {"track_id": 2, "bbox": [second_x, 20, second_x + 30, 60], "class_name": "car", "class_id": 1, "confidence": 0.9},
                ]

            def accident_predict(self, frame, *, conf, imgsz):
                return [{"class_name": "accident", "class_id": 0, "confidence": 0.9, "bbox": [0, 0, 160, 90], "track_id": None}]

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            storage = LocalStorageService(root)
            uploads = root / "uploads"
            uploads.mkdir()
            path = uploads / "UP-integration.mp4"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (160, 90))
            self.assertTrue(writer.isOpened())
            for index in range(36):
                writer.write(np.full((90, 160, 3), index % 255, dtype=np.uint8))
            writer.release()
            values = Settings().values
            values["verification_interval_seconds"] = 0.5
            rules = Settings().rules
            rules.update({"suspicion_distance_ratio": 0.5, "suspicion_consecutive_frames": 3,
                          "verifier_min_confidence": 0.55, "verifier_min_positive_frames": 2,
                          "verifier_sample_interval_seconds": 0.5, "uncertain_after_seconds": 2.5,
                          "evidence_pre_seconds": 1, "evidence_post_seconds": 1})
            pipeline = Pipeline(FakeModels(), storage, SimpleNamespace(values=values, rules=rules), rules)
            try:
                pipeline.start(path.name, roi={"enabled": False, "points": []})
                deadline = time.monotonic() + 8
                while pipeline.status()["state"] == "RUNNING" and time.monotonic() < deadline:
                    time.sleep(0.05)
                pipeline._worker.tasks.join()
                events, _ = storage.list_events(limit=20)
                self.assertIsNone(pipeline.status()["last_error"])
                self.assertIsNone(pipeline.status()["last_error"])
                self.assertTrue(events, "synthetic approach should create a review event")
                self.assertTrue(all(event["status"] in {"SUSPECTED", "UNCERTAIN"} for event in events))
                self.assertTrue(all(event.get("manual_review_status") is None for event in events))
                self.assertTrue(all(event.get("trajectory") for event in events))
                self.assertTrue(any(event.get("verification", {}).get("review_ready") for event in events))
            finally:
                pipeline.stop()


if __name__ == "__main__":
    unittest.main()
