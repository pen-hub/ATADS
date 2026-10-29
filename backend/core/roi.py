"""ROI geometry shared by validation, inference and tracking."""
import cv2
import numpy as np


def validate_polygon(points):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or not 3 <= len(p) <= 32:
        raise ValueError('ROI cần 3–32 điểm')
    if not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise ValueError('Tọa độ ROI phải nằm trong [0, 1]')
    if len(set(map(tuple, p))) != len(p):
        raise ValueError('ROI có điểm trùng')
    def cross(a, b, c):
        u, v = b-a, c-a
        return float(u[0]*v[1]-u[1]*v[0])
    def intersects(a, b, c, d):
        if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]): return False
        if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]): return False
        return cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0
    for i in range(len(p)):
        for j in range(i+1, len(p)):
            if j == i+1 or (i == 0 and j == len(p)-1): continue
            if intersects(p[i], p[(i+1)%len(p)], p[j], p[(j+1)%len(p)]):
                raise ValueError('Các cạnh ROI không được tự cắt hoặc chạm nhau')
    if abs(cv2.contourArea(p.astype(np.float32))) < 0.001:
        raise ValueError('ROI quá nhỏ hoặc gần thẳng hàng (tối thiểu 0,1% ảnh)')


def contains(roi, box, width, height):
    if not roi or not roi.get('enabled'): return True
    x1,y1,x2,y2 = box
    y = (y1+y2)/2 if roi.get('anchor') == 'center' else y2
    return cv2.pointPolygonTest(np.asarray(roi['points'], np.float32),
                               ((x1+x2)/(2*width), y/height), False) >= 0


def crop_mask(frame, roi):
    if not roi or not roi.get('enabled'): return frame, (0, 0)
    h,w = frame.shape[:2]
    p = np.asarray(roi['points']) * [w,h]
    x0,y0 = np.floor(p.min(axis=0)).astype(int)
    x1,y1 = np.ceil(p.max(axis=0)).astype(int)
    x0,y0 = max(0,x0),max(0,y0)
    x1,y1 = min(w,x1),min(h,y1)
    crop = frame[y0:y1,x0:x1].copy()
    mask = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.rint(p-[x0,y0]).astype(np.int32)], 255)
    crop[mask == 0] = 0
    return crop, (x0,y0)


def mask_full(frame, roi):
    crop, (x,y) = crop_mask(frame, roi)
    if not roi or not roi.get('enabled'): return frame
    result = np.zeros_like(frame)
    result[y:y+crop.shape[0], x:x+crop.shape[1]] = crop
    return result
