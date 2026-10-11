"""
Bước fine-tune: freeze phần lớn backbone (MobileFaceNet hoặc IR-SE50) pretrained,
chỉ train các lớp cuối + ArcFace head trên tập dữ liệu của bạn (mặc định: data/casia_subset).

Trước khi chạy, cần có:
  - external/InsightFace_Pytorch  (đã clone)
  - Trọng số pretrained:
      + model_ir_se50.pth (IR-SE50, ~175MB)
      hoặc
      + mobilefacenet.pth (MobileFaceNet, ~4MB)
    đặt tại external/InsightFace_Pytorch/work_space/model/
  - data/casia_subset/<person_id>/*.jpg  (đã trích xuất từ 02a_decode_mxnet_rec.py)

Chạy (ví dụ):
  python src/03_finetune.py --model_type ir_se50 --epochs 10 --batch_size 32 --lr 0.001
"""
import argparse
import csv
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split
from torchvision import transforms
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_PATH = PROJECT_ROOT / "external" / "InsightFace_Pytorch"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(REPO_PATH) not in sys.path:
    sys.path.insert(0, str(REPO_PATH))

try:
    from model import MobileFaceNet, Backbone, Arcface
except ImportError:
    from external.InsightFace_Pytorch.model import MobileFaceNet, Backbone, Arcface

from facenet_pytorch import MTCNN

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ----------------------------------------------------------------------
# 1. Dataset: đọc ảnh, hỗ trợ ảnh đã align sẵn 112x112 hoặc chạy MTCNN
# ----------------------------------------------------------------------
class FaceDataset(Dataset):
    def __init__(self, raw_dir: str, cache_dir: str, mtcnn: MTCNN = None, skip_mtcnn: bool = True):
        self.raw_dir = Path(raw_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mtcnn = mtcnn
        self.skip_mtcnn = skip_mtcnn

        self.classes = sorted([d.name for d in self.raw_dir.iterdir() if d.is_dir()])
        self.class_to_idx = {name: i for i, name in enumerate(self.classes)}

        self.samples = []  # list of (raw_img_path, cache_img_path, label)
        for person in self.classes:
            person_dir = self.raw_dir / person
            (self.cache_dir / person).mkdir(parents=True, exist_ok=True)
            for img_path in sorted(list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png"))):
                cache_path = self.cache_dir / person / img_path.name
                self.samples.append((img_path, cache_path, self.class_to_idx[person]))

        self.to_tensor = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
        ])
        self.resize_112 = transforms.Resize((112, 112))

        print(f"Dataset: {len(self.classes)} người, {len(self.samples)} ảnh (nguồn: {self.raw_dir})")

    def __len__(self):
        return len(self.samples)

    def _get_aligned(self, raw_path: Path, cache_path: Path):
        # Nếu đã align sẵn (như ảnh trích xuất từ InsightFace .rec), nạp thẳng
        if self.skip_mtcnn:
            img = Image.open(raw_path).convert("RGB")
            if img.size != (112, 112):
                img = self.resize_112(img)
            return img

        if cache_path.exists():
            return Image.open(cache_path).convert("RGB")

        img = Image.open(raw_path).convert("RGB")
        if self.mtcnn is not None:
            face_tensor = self.mtcnn(img)
            if face_tensor is not None:
                face_img = transforms.ToPILImage()((face_tensor * 0.5 + 0.5).clamp(0, 1))
                face_img.save(cache_path)
                return face_img

        # Dự phòng: nếu MTCNN không tìm thấy mặt, resize ảnh gốc về 112x112 thay vì bỏ mẫu
        img = self.resize_112(img)
        img.save(cache_path)
        return img

    def __getitem__(self, idx):
        raw_path, cache_path, label = self.samples[idx]
        img = self._get_aligned(raw_path, cache_path)
        return self.to_tensor(img), label


def clean_collate(batch):
    """Bỏ qua các mẫu rỗng (nếu có)."""
    batch = [b for b in batch if b[0] is not None and b[0].abs().sum() > 0]
    if len(batch) == 0:
        return None, None
    imgs = torch.stack([b[0] for b in batch])
    labels = torch.tensor([b[1] for b in batch])
    return imgs, labels


# ----------------------------------------------------------------------
# 2. Đóng băng (freeze) phần lớn backbone — chỉ train N% lớp cuối
# ----------------------------------------------------------------------
def freeze_backbone(model: nn.Module, unfreeze_ratio: float = 0.2):
    named_params = list(model.named_parameters())
    n_total = len(named_params)
    n_unfreeze = max(1, int(n_total * unfreeze_ratio))
    cutoff = n_total - n_unfreeze

    for i, (name, p) in enumerate(named_params):
        p.requires_grad = i >= cutoff

    n_trainable = sum(p.requires_grad for _, p in named_params)
    print(f"Freeze backbone: {n_total - n_trainable}/{n_total} tham số bị đóng băng, "
          f"{n_trainable}/{n_total} tham số sẽ được train.")


# ----------------------------------------------------------------------
# 3. Vòng lặp train / validate
# ----------------------------------------------------------------------
def run_epoch(model, head, loader, optimizer, scaler, criterion, train=True):
    model.train(train)
    head.train(train)

    total_loss, total_correct, total_samples = 0.0, 0, 0

    for imgs, labels in loader:
        if imgs is None:
            continue
        imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)

        with torch.set_grad_enabled(train):
            with torch.cuda.amp.autocast(enabled=(DEVICE == "cuda")):
                embeddings = model(imgs)

            # Arcface head và loss chạy ở float32 để ổn định số học và tránh lệch kiểu dữ liệu
            logits = head(embeddings.float(), labels)
            loss = criterion(logits, labels)

            if train:
                optimizer.zero_grad()
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()

        total_loss += loss.item() * imgs.size(0)
        total_correct += (logits.argmax(1) == labels).sum().item()
        total_samples += imgs.size(0)

    if total_samples == 0:
        return 0.0, 0.0
    return total_loss / total_samples, total_correct / total_samples


def main():
    default_ir_weights = REPO_PATH / "work_space" / "model" / "model_ir_se50.pth"
    default_mobile_weights = REPO_PATH / "work_space" / "model" / "mobilefacenet.pth"

    default_model_type = "ir_se50" if default_ir_weights.exists() else "mobilefacenet"
    default_weights_path = str(default_ir_weights if default_ir_weights.exists() else default_mobile_weights)

    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", type=str, default="data/casia_subset")
    parser.add_argument("--cache_dir", type=str, default="data/processed/casia_aligned")
    parser.add_argument("--model_type", type=str, default=default_model_type,
                        choices=["ir_se50", "mobilefacenet"],
                        help="Kiến trúc mô hình: ir_se50 (Backbone IR-SE50) hoặc mobilefacenet")
    parser.add_argument("--weights", type=str, default=default_weights_path,
                        help="Đường dẫn file .pth trọng số pretrained")
    parser.add_argument("--skip_mtcnn", action="store_true", default=True,
                        help="Bỏ qua MTCNN nếu ảnh đã align sẵn 112x112 (mặc định True)")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--unfreeze_ratio", type=float, default=0.2)
    parser.add_argument("--embedding_size", type=int, default=512)
    parser.add_argument("--val_split", type=float, default=0.15)
    parser.add_argument("--num_workers", type=int, default=0,
                        help="Số worker DataLoader (trên Windows khuyến nghị 0 để tránh lỗi IPC)")
    args = parser.parse_args()

    print(f"--- BẮT ĐẦU CẤU HÌNH HUẤN LUYỆN ---")
    print(f"Thiết bị chạy: {DEVICE}")
    print(f"Kiến trúc: {args.model_type}")
    print(f"Trọng số pretrained: {args.weights}")

    weights_path = Path(args.weights)
    if not weights_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy file trọng số tại: {weights_path}.\n"
            f"Hãy kiểm tra lại đường dẫn --weights."
        )

    Path("models/checkpoints").mkdir(parents=True, exist_ok=True)
    Path("results").mkdir(parents=True, exist_ok=True)

    # --- Dataset ---
    mtcnn = None
    if not args.skip_mtcnn:
        mtcnn = MTCNN(image_size=112, margin=0, device=DEVICE)

    full_dataset = FaceDataset(args.data_dir, args.cache_dir, mtcnn=mtcnn, skip_mtcnn=args.skip_mtcnn)

    if len(full_dataset) == 0:
        raise ValueError(
            f"Thư mục dữ liệu {args.data_dir} đang trống!\n"
            f"Hãy chạy: python src/02a_decode_mxnet_rec.py trước để tạo dữ liệu tập con."
        )

    n_val = int(len(full_dataset) * args.val_split)
    n_train = len(full_dataset) - n_val
    train_ds, val_ds = random_split(full_dataset, [n_train, n_val])

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.num_workers, collate_fn=clean_collate)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                            num_workers=args.num_workers, collate_fn=clean_collate)

    # --- Model ---
    if args.model_type == "ir_se50":
        model = Backbone(50, 0.6, "ir_se").to(DEVICE)
    else:
        model = MobileFaceNet(args.embedding_size).to(DEVICE)

    state_dict = torch.load(str(weights_path), map_location=DEVICE)
    model.load_state_dict(state_dict)
    print(f"✓ Đã nạp thành công trọng số pretrained từ: {weights_path}")

    freeze_backbone(model, args.unfreeze_ratio)

    head = Arcface(embedding_size=args.embedding_size,
                   classnum=len(full_dataset.classes)).to(DEVICE)

    criterion = nn.CrossEntropyLoss()
    trainable_params = [p for p in model.parameters() if p.requires_grad] + list(head.parameters())
    optimizer = torch.optim.Adam(trainable_params, lr=args.lr)
    scaler = torch.cuda.amp.GradScaler(enabled=(DEVICE == "cuda"))

    # --- Training loop ---
    log_path = Path("results/training_log.csv")
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["epoch", "train_loss", "train_acc", "val_loss", "val_acc", "time_sec"])

    best_val_acc = 0.0
    print(f"\n--- BẮT ĐẦU VÒNG LẶP HUẤN LUYỆN ({args.epochs} EPOCHS) ---")
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss, train_acc = run_epoch(model, head, train_loader, optimizer, scaler, criterion, train=True)
        val_loss, val_acc = run_epoch(model, head, val_loader, optimizer, scaler, criterion, train=False)
        elapsed = time.time() - t0

        print(f"[Epoch {epoch:02d}/{args.epochs:02d}] "
              f"train_loss={train_loss:.4f} train_acc={train_acc:.4f} | "
              f"val_loss={val_loss:.4f} val_acc={val_acc:.4f} | {elapsed:.1f}s")

        with open(log_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([epoch, train_loss, train_acc, val_loss, val_acc, round(elapsed, 1)])

        # Lưu checkpoint mỗi epoch
        torch.save(model.state_dict(), f"models/checkpoints/epoch_{epoch}.pth")

        # Lưu model tốt nhất theo val_acc
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(model.state_dict(), "models/best_model.pth")
            print(f"  -> Model tốt nhất mới (val_acc={val_acc:.4f}), đã lưu vào models/best_model.pth")

    print(f"\n✓ Hoàn tất fine-tune. Best val_acc = {best_val_acc:.4f}")
    print("Model tốt nhất được lưu tại: models/best_model.pth")


if __name__ == "__main__":
    main()
