"""
Đánh giá model ArcFace IR-SE50 đã fine-tune (models/best_model.pth) trên tập LFW,
so sánh trực tiếp với kết quả FaceNet baseline (01_baseline_eval.py).

Chỉ số đánh giá:
  - Accuracy: % cặp ảnh phân loại đúng (cùng người / khác người)
  - FAR (False Accept Rate): tỷ lệ nhận nhầm người lạ
  - FRR (False Reject Rate): tỷ lệ từ chối nhầm người quen
  - EER (Equal Error Rate): điểm FAR == FRR, càng thấp càng tốt
  - AUC: diện tích dưới đường ROC

Chạy:
  python src/04_evaluate.py --model_path models/best_model.pth
  python src/04_evaluate.py --model_path models/best_model.pth --compare_baseline results/baseline_faceNet_results.txt
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import torch
from PIL import Image
from sklearn.metrics import roc_curve, auc

# --- Đường dẫn project và repo InsightFace ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_PATH = PROJECT_ROOT / "external" / "InsightFace_Pytorch"

# Load model.py trực tiếp từ đường dẫn tuyệt đối (tránh lỗi import mơ hồ)
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("insightface_model", REPO_PATH / "model.py")
_mod  = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
Backbone = _mod.Backbone

from facenet_pytorch import MTCNN

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ------------------------------------------------------------------
# Đường dẫn mặc định (khớp với cấu trúc project)
# ------------------------------------------------------------------
DEFAULT_IMG_ROOT   = str(PROJECT_ROOT / "data/lfw/lfw-deepfunneled/lfw-deepfunneled")
DEFAULT_PAIRS_CSV  = str(PROJECT_ROOT / "data/lfw/pairs_converted.csv")
DEFAULT_MODEL_PATH = str(PROJECT_ROOT / "models/best_model.pth")
DEFAULT_BASELINE   = str(PROJECT_ROOT / "results/baseline_faceNet_results.txt")


# ------------------------------------------------------------------
# Load mô hình IR-SE50 fine-tuned
# ------------------------------------------------------------------
def load_model(model_path: str):
    model = Backbone(50, 0.6, "ir_se").to(DEVICE)
    state_dict = torch.load(model_path, map_location=DEVICE)
    model.load_state_dict(state_dict)
    model.eval()
    print(f"✓ Đã nạp model từ: {model_path}")
    return model


# ------------------------------------------------------------------
# Trích xuất embedding (face detect bằng MTCNN, resize 112x112)
# ------------------------------------------------------------------
def build_embedding_fn(model, mtcnn):
    cache = {}

    def get_embedding(img_path: str):
        if img_path in cache:
            return cache[img_path]

        try:
            img = Image.open(img_path).convert("RGB")
        except Exception:
            cache[img_path] = None
            return None

        # Cố gắng detect + align khuôn mặt bằng MTCNN
        face = mtcnn(img)
        if face is None:
            # Dự phòng: resize thẳng về 112x112 nếu không detect được mặt
            import torchvision.transforms as T
            face = T.Compose([
                T.Resize((112, 112)),
                T.ToTensor(),
                T.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
            ])(img)

        with torch.no_grad():
            emb = model(face.unsqueeze(0).to(DEVICE))
        emb_np = emb.squeeze(0).cpu().numpy()
        cache[img_path] = emb_np
        return emb_np

    return get_embedding


# ------------------------------------------------------------------
# Đọc file CSV cặp ảnh (giống 01_baseline_eval.py)
# ------------------------------------------------------------------
def load_pairs(csv_path: str, img_root: str, limit=None):
    pos_pairs, neg_pairs = [], []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # bỏ header
        for row in reader:
            if not row or len(row) < 4:
                continue
            name1, img1, name2, img2 = row[0], int(row[1]), row[2], int(row[3])
            path1 = os.path.join(img_root, name1, f"{name1}_{img1:04d}.jpg")
            path2 = os.path.join(img_root, name2, f"{name2}_{img2:04d}.jpg")
            if name1 == name2:
                pos_pairs.append((path1, path2))
            else:
                neg_pairs.append((path1, path2))

    if limit is not None:
        half = limit // 2
        pos_pairs = pos_pairs[:half]
        neg_pairs = neg_pairs[:(limit - half)]

    pairs  = pos_pairs + neg_pairs
    labels = [1] * len(pos_pairs) + [0] * len(neg_pairs)
    return pairs, labels


# ------------------------------------------------------------------
# Tính cosine similarity và các chỉ số đánh giá
# ------------------------------------------------------------------
def compute_metrics(embeddings_1, embeddings_2, labels):
    e1 = np.array(embeddings_1)
    e2 = np.array(embeddings_2)
    y  = np.array(labels)

    # Cosine similarity
    norms_1 = np.linalg.norm(e1, axis=1, keepdims=True)
    norms_2 = np.linalg.norm(e2, axis=1, keepdims=True)
    e1_norm = e1 / np.maximum(norms_1, 1e-8)
    e2_norm = e2 / np.maximum(norms_2, 1e-8)
    similarities = np.sum(e1_norm * e2_norm, axis=1)

    # ROC / EER
    fpr, tpr, thresholds = roc_curve(y, similarities)
    roc_auc = auc(fpr, tpr)

    eer_idx       = np.nanargmin(np.abs(fpr - (1 - tpr)))
    eer           = float(fpr[eer_idx])  # ≈ FRR ở điểm EER
    best_threshold = float(thresholds[eer_idx])

    # Accuracy / FAR / FRR tại ngưỡng EER
    predictions = (similarities >= best_threshold).astype(int)
    accuracy    = float((predictions == y).mean())
    far         = float(np.mean(predictions[y == 0])) if np.any(y == 0) else 0.0
    frr         = float(np.mean(predictions[y == 1] == 0)) if np.any(y == 1) else 0.0

    return {
        "accuracy":  accuracy,
        "far":       far,
        "frr":       frr,
        "eer":       eer,
        "threshold": best_threshold,
        "auc":       roc_auc,
        "fpr":       fpr,
        "tpr":       tpr,
    }


# ------------------------------------------------------------------
# Đọc kết quả baseline (FaceNet) để so sánh
# ------------------------------------------------------------------
def load_baseline_results(path: str):
    results = {}
    if not os.path.exists(path):
        return results
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                key, val = line.split(":", 1)
                try:
                    results[key.strip().lower()] = float(val.strip())
                except ValueError:
                    results[key.strip().lower()] = val.strip()
    return results


# ------------------------------------------------------------------
# In bảng so sánh
# ------------------------------------------------------------------
def print_comparison(metrics: dict, baseline: dict, model_name: str = "IR-SE50 Fine-tuned"):
    print("\n" + "=" * 62)
    print(f"{'CHỈ SỐ':<22} {'FaceNet (baseline)':>18} {model_name:>18}")
    print("=" * 62)

    rows = [
        ("Accuracy",  "accuracy",  "accuracy"),
        ("FAR",       "far",       "far"),
        ("FRR",       "frr",       "frr"),
        ("EER",       "eer",       "eer"),
        ("Threshold", "threshold", "threshold"),
    ]

    for label, key_base, key_ft in rows:
        base_val = baseline.get(key_base, "N/A")
        ft_val   = metrics.get(key_ft, "N/A")
        base_str = f"{base_val:.4f}" if isinstance(base_val, float) else str(base_val)
        ft_str   = f"{ft_val:.4f}"   if isinstance(ft_val,   float) else str(ft_val)

        # Đánh dấu cải thiện (↑ accuracy/AUC, ↓ FAR/FRR/EER)
        arrow = ""
        if isinstance(base_val, float) and isinstance(ft_val, float):
            if key_base == "accuracy":
                arrow = " ↑" if ft_val > base_val else (" ↓" if ft_val < base_val else "")
            else:
                arrow = " ↓" if ft_val < base_val else (" ↑" if ft_val > base_val else "")

        print(f"  {label:<20} {base_str:>18} {ft_str + arrow:>20}")

    print("=" * 62)
    print(f"  {'AUC':<20} {'N/A':>18} {metrics['auc']:.4f}")
    print("=" * 62)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_path", type=str, default=DEFAULT_MODEL_PATH,
                        help="Đường dẫn file .pth model đã fine-tune")
    parser.add_argument("--img_root", type=str, default=DEFAULT_IMG_ROOT,
                        help="Thư mục gốc ảnh LFW")
    parser.add_argument("--pairs_csv", type=str, default=DEFAULT_PAIRS_CSV,
                        help="File CSV chứa các cặp ảnh đánh giá")
    parser.add_argument("--limit", type=int, default=None,
                        help="Giới hạn số cặp đánh giá (mặc định: toàn bộ)")
    parser.add_argument("--compare_baseline", type=str, default=DEFAULT_BASELINE,
                        help="Đường dẫn file kết quả baseline để so sánh")
    parser.add_argument("--output", type=str,
                        default=str(PROJECT_ROOT / "results/finetuned_arcface_results.txt"),
                        help="File lưu kết quả đánh giá")
    args = parser.parse_args()

    print(f"{'='*62}")
    print(f"  ĐÁNH GIÁ MODEL ARCFACE IR-SE50 FINE-TUNED TRÊN LFW")
    print(f"{'='*62}")
    print(f"Thiết bị: {DEVICE}")
    print(f"Model:    {args.model_path}")

    # --- Kiểm tra tồn tại file ---
    for path, name in [(args.model_path, "model_path"),
                       (args.img_root,   "img_root"),
                       (args.pairs_csv,  "pairs_csv")]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Không tìm thấy {name}: {path}")

    # --- Load ---
    model = load_model(args.model_path)
    mtcnn = MTCNN(image_size=112, margin=0, device=DEVICE)
    get_embedding = build_embedding_fn(model, mtcnn)

    # --- Đọc cặp ảnh ---
    print(f"\nĐang đọc cặp ảnh từ: {args.pairs_csv}")
    pairs, labels = load_pairs(args.pairs_csv, args.img_root, args.limit)
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    print(f"Tổng cặp: {len(pairs)}  (cùng người: {n_pos}, khác người: {n_neg})")

    # --- Trích xuất embeddings ---
    print("\nĐang trích xuất embeddings...")
    t0 = time.time()
    embs_1, embs_2, valid_labels = [], [], []
    skipped = 0

    for i, ((p1, p2), lbl) in enumerate(zip(pairs, labels)):
        if not os.path.exists(p1) or not os.path.exists(p2):
            skipped += 1
            continue

        e1 = get_embedding(p1)
        e2 = get_embedding(p2)

        if e1 is None or e2 is None:
            skipped += 1
            continue

        embs_1.append(e1)
        embs_2.append(e2)
        valid_labels.append(lbl)

        if (i + 1) % 100 == 0 or (i + 1) == len(pairs):
            elapsed = time.time() - t0
            print(f"  {i + 1}/{len(pairs)} cặp  ({elapsed:.1f}s)")

    total_time = time.time() - t0
    total_faces = len(valid_labels) * 2
    avg_latency_ms = (total_time / max(1, total_faces)) * 1000
    fps = total_faces / max(0.001, total_time)

    print(f"\nHoàn tất trích xuất: {len(valid_labels)} cặp hợp lệ, bỏ qua {skipped} cặp.")
    print(f"Thời gian trung bình: {avg_latency_ms:.2f} ms/khuôn mặt (~{fps:.1f} FPS)")

    if len(valid_labels) < 2 or len(set(valid_labels)) < 2:
        raise ValueError("Không đủ cặp hợp lệ để tính ROC curve. Kiểm tra lại img_root và pairs_csv.")

    # --- Tính chỉ số ---
    print("\nĐang tính toán các chỉ số đánh giá...")
    metrics = compute_metrics(embs_1, embs_2, valid_labels)

    # --- So sánh với baseline ---
    baseline = load_baseline_results(args.compare_baseline)

    print_comparison(metrics, baseline)

    # --- In chi tiết ---
    delta_acc = ""
    if "accuracy" in baseline and isinstance(baseline["accuracy"], float):
        delta = metrics["accuracy"] - baseline["accuracy"]
        sign  = "+" if delta >= 0 else ""
        delta_acc = f"  (so với baseline FaceNet: {sign}{delta:.4f})"

    print(f"\n>>> Accuracy     = {metrics['accuracy']:.4f}{delta_acc}")
    print(f">>> EER          = {metrics['eer']:.4f}  (càng thấp càng tốt)")
    print(f">>> AUC          = {metrics['auc']:.4f}  (càng cao càng tốt)")
    print(f">>> Latency      = {avg_latency_ms:.2f} ms/face")
    print(f">>> Throughput   = {fps:.1f} FPS")

    # --- Lưu kết quả ---
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("ArcFace IR-SE50 Fine-tuned\n")
        f.write(f"Model: {args.model_path}\n")
        f.write(f"Total pairs evaluated: {len(valid_labels)}\n")
        f.write(f"Accuracy:    {metrics['accuracy']:.4f}\n")
        f.write(f"FAR:         {metrics['far']:.4f}\n")
        f.write(f"FRR:         {metrics['frr']:.4f}\n")
        f.write(f"EER:         {metrics['eer']:.4f}\n")
        f.write(f"Threshold:   {metrics['threshold']:.4f}\n")
        f.write(f"AUC:         {metrics['auc']:.4f}\n")
        f.write(f"Latency:     {avg_latency_ms:.2f} ms/face\n")
        f.write(f"Throughput:  {fps:.1f} FPS\n")
        if "accuracy" in baseline and isinstance(baseline["accuracy"], float):
            delta = metrics["accuracy"] - baseline["accuracy"]
            f.write(f"\nDelta vs FaceNet baseline (Accuracy): {'+' if delta >= 0 else ''}{delta:.4f}\n")

    print(f"\nKết quả đã lưu vào: {args.output}")



if __name__ == "__main__":
    main()
