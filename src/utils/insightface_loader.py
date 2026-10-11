"""
Wrapper nạp model MobileFaceNet / IR-SE50 (ArcFace) từ repo TreB1eN/InsightFace_Pytorch
đã clone vào external/InsightFace_Pytorch.

Mục tiêu: cung cấp hàm get_embedding() có cùng "hình dạng" (interface) với
hàm trong 01_baseline_eval.py (dùng FaceNet), để có thể dùng chung code đánh
giá (evaluate_pairs) cho cả 2 backbone -> so sánh công bằng.

TRƯỚC KHI CHẠY:
1. Đã clone: git clone https://github.com/TreB1eN/InsightFace_Pytorch external/InsightFace_Pytorch
2. Đã tải file .pth (Mobilefacenet hoặc IR-SE50) từ link OneDrive trong README của repo trên,
   đặt vào: external/InsightFace_Pytorch/work_space/model/<tên_file>.pth
3. Sửa biến WEIGHTS_FILENAME bên dưới cho khớp đúng tên file bạn đã tải.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import torch
import numpy as np
from PIL import Image

# --- Cho phép import code kiến trúc từ repo đã clone ---
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_PATH = PROJECT_ROOT / "external" / "InsightFace_Pytorch"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(REPO_PATH) not in sys.path:
    sys.path.insert(0, str(REPO_PATH))

from external.InsightFace_Pytorch.model import MobileFaceNet, Backbone  # định nghĩa kiến trúc
from facenet_pytorch import MTCNN  # tái dùng MTCNN đã có để detect + align

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Tên file trọng số đã tải về trong external/InsightFace_Pytorch/work_space/model/
WEIGHTS_FILENAME = "model_ir_se50.pth"
WEIGHTS_PATH = REPO_PATH / "work_space" / "model" / WEIGHTS_FILENAME

USE_MOBILEFACENET = False  # False vì đang dùng bản IR-SE50 (model_ir_se50.pth) thay vì MobileFaceNet

mtcnn = MTCNN(image_size=112, margin=0, device=DEVICE)  # lưu ý: 112x112, không phải 160 như FaceNet

if USE_MOBILEFACENET:
    model = MobileFaceNet(512)  # 512-d embedding
else:
    model = Backbone(50, 0.6, "ir_se")  # IR-SE50

if not WEIGHTS_PATH.exists():
    raise FileNotFoundError(
        f"Không tìm thấy file trọng số tại {WEIGHTS_PATH}.\n"
        f"-> Kiểm tra lại: đã tải file .pth từ link OneDrive trong README repo chưa? "
        f"Đã đặt đúng thư mục work_space/model/ chưa? Tên file có khớp WEIGHTS_FILENAME không?"
    )

model.load_state_dict(torch.load(str(WEIGHTS_PATH), map_location=DEVICE))
model.eval().to(DEVICE)
print(f"Đã nạp model từ: {WEIGHTS_PATH}")


def get_embedding(img_path: str):
    """Cùng interface với hàm trong 01_baseline_eval.py -> dùng thay thế trực tiếp được."""
    img = Image.open(img_path).convert("RGB")
    face = mtcnn(img)
    if face is None:
        return None
    with torch.no_grad():
        embedding = model(face.unsqueeze(0).to(DEVICE))
    return embedding.cpu().numpy().flatten()


if __name__ == "__main__":
    # Test nhanh: thử trích embedding 1 ảnh bất kỳ để chắc chắn mọi thứ hoạt động
    test_img = PROJECT_ROOT / "data/lfw/lfw-deepfunneled/lfw-deepfunneled/Abel_Pacheco/Abel_Pacheco_0001.jpg"
    if Path(test_img).exists():
        emb = get_embedding(test_img)
        if emb is not None:
            print(f"✓ Trích embedding thành công, kích thước: {emb.shape}")
        else:
            print("✗ Không detect được khuôn mặt trong ảnh test.")
    else:
        print(f"⚠ Không tìm thấy ảnh test tại {test_img}, tự đổi sang 1 ảnh có thật để kiểm tra.")
