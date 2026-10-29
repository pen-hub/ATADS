import unittest
import threading
from types import SimpleNamespace
import numpy as np
import torch
from ultralytics.engine.results import Results
from backend.core.roi import validate_polygon, crop_mask, contains
from backend.detection.models import ModelManager


class RoiInferenceTests(unittest.TestCase):
    def test_invalid_geometry(self):
        for points in ([[0,0],[1,1],[0,1],[1,0]], [[0,0],[1,0],[1,0]],
                       [[0,0],[.001,0],[0,.001]]):
            with self.assertRaises(ValueError): validate_polygon(points)

    def test_mask_and_offset(self):
        roi={'enabled':True,'points':[[.2,.2],[.8,.2],[.2,.8]]}
        crop,offset=crop_mask(np.full((100,100,3),255,np.uint8),roi)
        self.assertEqual(offset,(20,20))
        self.assertEqual(crop.shape,(60,60,3))
        self.assertEqual(int(crop[55,55].sum()),0)
        self.assertEqual(int(crop[5,5].sum()),765)

    def test_anchor_and_boundary(self):
        roi={'enabled':True,'points':[[0,.5],[1,.5],[1,1],[0,1]]}
        self.assertTrue(contains(roi,[10,20,30,50],100,100))
        self.assertFalse(contains({**roi,'anchor':'center'},[10,20,30,50],100,100))

    def test_detector_cropped_tracker_filtered_coordinates_restored(self):
        manager=object.__new__(ModelManager)
        manager._vehicle_lock=threading.RLock()
        manager.device='cpu'; manager.vehicle_names={0:'car'}
        calls=[]
        def predict(frame, **kwargs):
            calls.append(frame.copy())
            return [Results(frame, path='', names={0:'car'}, boxes=torch.tensor([
                [2,2,12,12,.9,0], [40,40,55,55,.9,0]],dtype=torch.float32))]
        manager.vehicle=SimpleNamespace(predict=predict)
        roi={'enabled':True,'points':[[.2,.2],[.8,.2],[.2,.8]]}
        output=manager.vehicle_track(np.full((100,100,3),255,np.uint8),conf=.5,imgsz=640,roi=roi)
        self.assertEqual(calls[0].shape,(60,60,3))
        self.assertEqual(len(output),1)
        np.testing.assert_allclose(output[0]['bbox'],[22,22,32,32],atol=.01)
        self.assertEqual(len(manager._roi_tracker.tracked_stracks),1)
        manager.vehicle.predict=lambda frame,**kw: [Results(frame,path='',names={0:'car'},boxes=torch.zeros((0,6)))]
        self.assertEqual(manager.vehicle_track(np.zeros((100,100,3),np.uint8),conf=.5,imgsz=640,roi=roi),[])
        manager.reset_tracking()
        self.assertEqual(len(manager._roi_tracker.tracked_stracks),0)
