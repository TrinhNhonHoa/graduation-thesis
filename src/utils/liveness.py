"""
Module Kiểm Tra Khuôn Mặt Sống / Chống Giả Mạo (Face Anti-Spoofing & Liveness Detection).
Phục vụ mục tiêu 1.1.5 & 1.2.3 trong Luận văn tốt nghiệp:
Ngăn chặn các hình thức gian lận chấm công bằng:
  1. Ảnh in trên giấy (Print attack)
  2. Ảnh hoặc video phát trên màn hình điện thoại/máy tính bảng (Replay/Screen attack)

Phương pháp kết hợp:
  - Phân tích kết cấu da & độ nét (Laplacian Variance & Texture sharpness)
  - Phân tích hiện tượng nhiễu Moiré & phổ tần số cao (Fourier Transform - FFT)
  - Phân tích phân bố không gian màu da tự nhiên (YCbCr / HSV Color distribution)
  - Phân tích vi chuyển động và tính đàn hồi của các điểm mốc khuôn mặt (Landmark dynamics)
"""
import time
import cv2
import numpy as np
from PIL import Image


class LivenessDetector:
    def __init__(self, liveness_threshold: float = 0.60):
        self.threshold = liveness_threshold
        # Lưu lịch sử vị trí landmarks và bounding box theo thời gian để kiểm tra chuyển động
        self.history = {}  # {session_id: list of landmark states}
        self.cleanup_time = time.time()

    def _cleanup_history(self):
        """Dọn dẹp lịch sử cũ sau mỗi 60 giây."""
        now = time.time()
        if now - self.cleanup_time > 60:
            self.history.clear()
            self.cleanup_time = now

    def _check_laplacian_sharpness(self, face_bgr: np.ndarray) -> tuple[float, float]:
        """
        Đo phương sai Laplacian để kiểm tra độ tương phản và kết cấu bề mặt.
        - Ảnh in giấy hoặc màn hình chất lượng thấp thường bị mờ (variance quá thấp)
        - Hoặc nhiễu hạt in ấn quá thô (variance bất thường)
        """
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        var = float(laplacian.var())

        # Ngưỡng tối ưu cho webcam thông thường: 80 - 1500
        if var < 60:
            score = max(0.0, var / 60.0 * 0.5)
        elif var > 2500:
            score = 0.5  # Nhiễu hạt in ấn quá gắt
        else:
            score = min(1.0, 0.6 + (var - 60) / 400.0 * 0.4)
        return score, var

    def _check_fft_screen_moire(self, face_bgr: np.ndarray) -> tuple[float, float]:
        """
        Phân tích miền tần số Fourier 2D để phát hiện nhiễu Moiré (lưới điểm ảnh của màn hình).
        Màn hình điện thoại/máy tính có các dải tần số cao tuần hoàn đặc trưng.
        """
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (128, 128))
        f = np.fft.fft2(resized)
        fshift = np.fft.fftshift(f)
        magnitude_spectrum = 20 * np.log(np.abs(fshift) + 1e-8)

        # Tính tỷ lệ năng lượng ở vùng viền tần số cao so với vùng trung tâm
        h, w = magnitude_spectrum.shape
        cy, cx = h // 2, w // 2
        r_inner = 20
        r_outer = 50

        y, x = np.ogrid[:h, :w]
        dist_from_center = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)

        mask_mid_high = (dist_from_center >= r_inner) & (dist_from_center <= r_outer)
        high_energy_ratio = float(np.mean(magnitude_spectrum[mask_mid_high]) / (np.mean(magnitude_spectrum) + 1e-8))

        # Da thật có phổ tần số liên tục mềm mại, màn hình LCD có gợn sóng sắc nhọn
        if high_energy_ratio > 1.45:
            score = 0.4  # Khả năng cao là màn hình kỹ thuật số
        elif high_energy_ratio < 0.85:
            score = 0.5  # Ảnh quá phẳng / mờ
        else:
            score = 0.95
        return score, high_energy_ratio

    def _check_skin_color_distribution(self, face_bgr: np.ndarray) -> tuple[float, dict]:
        """
        Kiểm tra tính sinh lý học của màu da trong không gian YCrCb và HSV.
        - Da người thật có dải sắc thái Cr và Cb nằm trong vùng elip sinh học xác định.
        - Màn hình điện thoại thường phát tán nhiều ánh sáng xanh (blue shift)
          và phản xạ ánh sáng trắng (specular reflection).
        """
        ycrcb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2YCrCb)
        hsv = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2HSV)

        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        sat = hsv[:, :, 1]

        # Vùng da người chuẩn: Cr ∈ [133, 173], Cb ∈ [77, 127]
        skin_mask = (cr >= 130) & (cr <= 175) & (cb >= 75) & (cb <= 130)
        skin_ratio = float(np.mean(skin_mask))

        # Kiểm tra độ lóa màn hình (vùng quá sáng Saturation thấp, Value rất cao)
        val = hsv[:, :, 2]
        glare_mask = (val > 245) & (sat < 30)
        glare_ratio = float(np.mean(glare_mask))

        if glare_ratio > 0.12:
            # Hiện tượng phản xạ ánh sáng trên kính điện thoại
            color_score = 0.4
        elif skin_ratio > 0.40:
            color_score = min(1.0, 0.7 + skin_ratio * 0.3)
        else:
            color_score = max(0.3, skin_ratio * 1.5)

        return color_score, {"skin_ratio": round(skin_ratio, 3), "glare_ratio": round(glare_ratio, 3)}

    def _check_micro_motion(self, session_key: str, landmarks: np.ndarray) -> tuple[float, str]:
        """
        Kiểm tra vi chuyển động khuôn mặt giữa các frame liên tiếp:
        - Ảnh in / màn hình để cố định: khoảng cách landmark hoàn toàn bằng 0 (chết tĩnh).
        - Người thật: có vi dao động mắt, hô hấp, cử động đầu tự nhiên (độ xê dịch 0.5px - 15px).
        """
        self._cleanup_history()
        history = self.history.setdefault(session_key, [])
        now = time.time()
        history.append({"time": now, "landmarks": landmarks})

        # Chỉ giữ lịch sử trong vòng 5 giây
        history = [h for h in history if now - h["time"] <= 5.0]
        self.history[session_key] = history

        if len(history) < 2:
            return 0.85, "Đang khởi tạo chuỗi frame"

        prev_lm = history[-2]["landmarks"]
        curr_lm = landmarks

        # Tính độ dịch chuyển trung bình của 5 điểm mốc
        disp = float(np.mean(np.linalg.norm(curr_lm - prev_lm, axis=1)))

        if disp < 0.05:
            # Quá tĩnh - có thể là ảnh chụp được gá cố định
            return 0.45, "Cảnh báo: Khuôn mặt quá tĩnh (nghi ngờ ảnh cố định)"
        elif disp > 60.0:
            # Chuyển động quá giật
            return 0.70, "Chuyển động mạnh"
        else:
            # Vi chuyển động tự nhiên của người sống
            return 0.95, "Chuyển động tự nhiên"

    def check_liveness(
        self,
        frame_rgb: Image.Image | np.ndarray,
        box: np.ndarray | None,
        landmarks: np.ndarray | None,
        session_key: str = "default",
    ) -> dict:
        """
        Đánh giá độ sống (Liveness Score) của khuôn mặt.
        Trả về:
          - is_live: True/False
          - liveness_score: [0.0 - 1.0]
          - liveness_pct: [0% - 100%]
          - details: chi tiết từng phép thử (độ nét, moire, màu da, chuyển động)
          - message: thông báo giải thích
        """
        if isinstance(frame_rgb, Image.Image):
            frame_np = np.array(frame_rgb)
        else:
            frame_np = frame_rgb

        # Chuyển sang BGR cho OpenCV
        frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)
        h, w, _ = frame_bgr.shape

        if box is None:
            return {
                "is_live": False,
                "liveness_score": 0.0,
                "liveness_pct": 0.0,
                "message": "Không tìm thấy hộp giới hạn khuôn mặt.",
            }

        # Cắt vùng khuôn mặt
        x1, y1, x2, y2 = [int(v) for v in box]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if (x2 - x1) < 20 or (y2 - y1) < 20:
            return {
                "is_live": False,
                "liveness_score": 0.0,
                "liveness_pct": 0.0,
                "message": "Khuôn mặt quá nhỏ hoặc ở quá xa camera.",
            }

        face_crop = frame_bgr[y1:y2, x1:x2]

        # 1. Phân tích độ nét & kết cấu (Laplacian Variance)
        sharp_score, lap_var = self._check_laplacian_sharpness(face_crop)

        # 2. Phân tích Moiré & phổ tần số Fourier (FFT)
        fft_score, high_ratio = self._check_fft_screen_moire(face_crop)

        # 3. Phân tích phân bố sắc tố da (YCbCr / HSV)
        color_score, color_details = self._check_skin_color_distribution(face_crop)

        # 4. Phân tích vi chuyển động tự nhiên nếu có landmarks
        if landmarks is not None and len(landmarks) > 0:
            motion_score, motion_msg = self._check_micro_motion(session_key, landmarks)
        else:
            motion_score, motion_msg = 0.75, "Không có landmarks"

        # Tính điểm tổng hợp (Weighted Ensemble)
        weights = {
            "sharpness": 0.25,
            "fft_moire": 0.25,
            "skin_color": 0.30,
            "micro_motion": 0.20,
        }

        total_score = (
            sharp_score * weights["sharpness"]
            + fft_score * weights["fft_moire"]
            + color_score * weights["skin_color"]
            + motion_score * weights["micro_motion"]
        )
        total_score = round(min(1.0, max(0.0, total_score)), 3)

        is_live = total_score >= self.threshold

        if is_live:
            msg = "Xác thực người thật (Live Person)"
        else:
            if color_details["glare_ratio"] > 0.12 or fft_score < 0.5:
                msg = "Cảnh báo: Nghi ngờ màn hình thiết bị phát lại (Replay Attack)!"
            elif sharp_score < 0.45:
                msg = "Cảnh báo: Nghi ngờ ảnh in hoặc hình ảnh không rõ nét (Print Attack)!"
            else:
                msg = "Cảnh báo: Khuôn mặt không đạt tiêu chuẩn kiểm tra độ sống (Anti-Spoofing failed)!"

        return {
            "is_live": is_live,
            "liveness_score": total_score,
            "liveness_pct": round(total_score * 100, 1),
            "message": msg,
            "details": {
                "sharpness_score": round(sharp_score, 3),
                "laplacian_var": round(lap_var, 1),
                "fft_score": round(fft_score, 3),
                "color_score": round(color_score, 3),
                "motion_score": round(motion_score, 3),
                "motion_msg": motion_msg,
                "skin_ratio": color_details["skin_ratio"],
                "glare_ratio": color_details["glare_ratio"],
            },
        }


# Khởi tạo singleton instance
liveness_detector = LivenessDetector(liveness_threshold=0.60)
