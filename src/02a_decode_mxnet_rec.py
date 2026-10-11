"""
CASIA-WebFace tải từ 1 số mirror Kaggle được đóng gói ở định dạng MXNet
RecordIO (train.rec + train.idx + property), KHÔNG phải ảnh .jpg rời như
mặc định 02b_sample_casia.py giả định.

Script này đọc trực tiếp file nhị phân .rec/.idx bằng Python thuần (KHÔNG cần mxnet),
CHỌN NGẪU NHIÊN N người rồi CHỈ trích xuất đúng ảnh của những người đó
-> xuất thẳng ra data/casia_subset/<label>/*.jpg (đúng định dạng mà 03_finetune.py cần).

Chạy (ví dụ):
  python src/02a_decode_mxnet_rec.py --n_people 400 --min_images 10 --max_images 30
"""
import argparse
import io
import random
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def read_idx_file(idx_path: Path):
    """Đọc file .idx dạng: <index>\t<byte_offset>"""
    offsets = {}
    with open(idx_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                offsets[int(parts[0])] = int(parts[1])
    return offsets


def read_record(f, offset: int):
    """
    Đọc một record tại offset trong file .rec:
    - 4 bytes magic (0xced7230a)
    - 4 bytes lflag ((cflag << 29) | length)
    - header: flag (uint32), label (float32), id (uint64), id2 (uint64) = 24 bytes
    - nếu flag > 0: đọc thêm flag * 4 bytes float
    - phần còn lại là image bytes (JPEG)
    """
    f.seek(offset)
    magic, lflag = struct.unpack("<II", f.read(8))
    if magic != 0xCED7230A:
        raise ValueError(f"Sai magic number tại offset {offset}: {hex(magic)}")
    length = lflag & ((1 << 29) - 1)
    data = f.read(length)

    flag, label, id1, id2 = struct.unpack("<IfQQ", data[:24])
    pos = 24
    extra_label = None
    if flag > 0:
        extra_len = flag * 4
        extra_label = struct.unpack(f"<{flag}f", data[pos : pos + extra_len])
        pos += extra_len

    img_bytes = data[pos:]
    return flag, label, extra_label, id1, id2, img_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rec_dir", type=str, default="data/casia/casia-webface",
                        help="Thư mục chứa train.rec + train.idx + property")
    parser.add_argument("--dest", type=str, default="data/casia_subset",
                        help="Thư mục đích để lưu ảnh subset")
    parser.add_argument("--n_people", type=int, default=400,
                        help="Số người muốn lấy")
    parser.add_argument("--min_images", type=int, default=10,
                        help="Số ảnh tối thiểu/người")
    parser.add_argument("--max_images", type=int, default=30,
                        help="Số ảnh tối đa/người")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)

    rec_dir = Path(args.rec_dir)
    idx_path = rec_dir / "train.idx"
    rec_path = rec_dir / "train.rec"

    if not idx_path.exists() or not rec_path.exists():
        raise SystemExit(
            f"✗ Không tìm thấy train.idx hoặc train.rec trong {rec_dir}.\n"
            f"Kiểm tra lại đường dẫn --rec_dir."
        )

    print(f"Đang đọc chỉ mục: {idx_path}...")
    t0 = time.time()
    offsets = read_idx_file(idx_path)
    print(f"Đã đọc {len(offsets)} bản ghi trong {time.time() - t0:.2f}s")

    label_to_indices = defaultdict(list)

    with open(rec_path, "rb") as f:
        # Kiểm tra xem có bản ghi đánh chỉ mục ID ở cuối file không (InsightFace pre-indexed identities)
        # Thông thường InsightFace lưu ID records có flag = 2 và extra_label = (start_idx, end_idx)
        has_id_index = False
        all_keys = sorted(offsets.keys())

        # Thử kiểm tra các record cuối
        sample_keys = [k for k in all_keys if k > len(all_keys) - 20000]
        if sample_keys:
            flag, _, extra, _, _, _ = read_record(f, offsets[sample_keys[-1]])
            if flag == 2 and extra is not None and len(extra) == 2:
                has_id_index = True

        if has_id_index:
            print("Phát hiện danh mục chỉ mục ID có sẵn (InsightFace index table), đang nạp danh sách người...")
            for k in all_keys:
                flag, label, extra, id1, _, _ = read_record(f, offsets[k])
                if flag == 2 and extra is not None and len(extra) == 2:
                    start_idx, end_idx = int(extra[0]), int(extra[1])
                    lbl_id = int(label) if label > 0 else int(id1)
                    # Gán danh sách idx ảnh thuộc về người này
                    idxs = list(range(start_idx, end_idx))
                    if idxs:
                        label_to_indices[lbl_id] = idxs
        else:
            print("Đang quét tiêu đề các bản ghi để nhóm theo danh tính (không giải mã ảnh)...")
            for i, idx in enumerate(all_keys):
                flag, label, extra, _, _, _ = read_record(f, offsets[idx])
                if flag == 0:
                    label_to_indices[int(label)].append(idx)
                if (i + 1) % 50000 == 0:
                    print(f"  Đã quét {i + 1}/{len(all_keys)} bản ghi...")

    print(f"Tổng số người (nhãn) tìm thấy: {len(label_to_indices)}")

    # Lọc người có đủ số ảnh tối thiểu
    valid_labels = [lbl for lbl, idxs in label_to_indices.items() if len(idxs) >= args.min_images]
    print(f"Số người đủ điều kiện (>= {args.min_images} ảnh): {len(valid_labels)}")

    if len(valid_labels) == 0:
        raise SystemExit("✗ Không có người nào đủ điều kiện. Thử giảm --min_images.")

    if len(valid_labels) < args.n_people:
        print(f"⚠ Chỉ có {len(valid_labels)} người đủ điều kiện, ít hơn --n_people ({args.n_people}).")
        print(f"Sẽ lấy toàn bộ {len(valid_labels)} người.")
        selected_labels = valid_labels
    else:
        selected_labels = random.sample(valid_labels, args.n_people)

    dest_root = Path(args.dest)
    dest_root.mkdir(parents=True, exist_ok=True)

    print(f"\nĐang trích xuất ảnh cho {len(selected_labels)} người vào {dest_root}...")
    total_saved = 0
    t_start = time.time()

    with open(rec_path, "rb") as f:
        for i, label in enumerate(selected_labels):
            idxs = label_to_indices[label]
            chosen_idxs = idxs if len(idxs) <= args.max_images else random.sample(idxs, args.max_images)

            person_dir = dest_root / f"person_{label:05d}"
            person_dir.mkdir(parents=True, exist_ok=True)

            for j, idx in enumerate(chosen_idxs):
                if idx not in offsets:
                    continue
                flag, _, _, _, _, img_bytes = read_record(f, offsets[idx])
                if not img_bytes:
                    continue

                out_img_path = person_dir / f"{label:05d}_{j:03d}.jpg"
                out_img_path.write_bytes(img_bytes)
                total_saved += 1

            if (i + 1) % 50 == 0 or (i + 1) == len(selected_labels):
                print(f"  Tiến độ: {i + 1}/{len(selected_labels)} người ({total_saved} ảnh)...")

    elapsed = time.time() - t_start
    print(f"\n✓ Hoàn tất! Đã trích xuất {len(selected_labels)} người, tổng cộng {total_saved} ảnh ({elapsed:.1f}s).")
    print(f"Dữ liệu sẵn sàng tại: {dest_root}")
    print("Bước tiếp theo: Chạy src/03_finetune.py để bắt đầu huấn luyện.")


if __name__ == "__main__":
    main()
