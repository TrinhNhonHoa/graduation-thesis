"""
Chọn ngẫu nhiên N người (thư mục danh tính) từ bộ CASIA-WebFace đã tải về,
copy sang data/casia_subset/ để dùng cho bước fine-tune (03_finetune.py).

Không cần dùng toàn bộ ~10,575 người của CASIA-WebFace -- vài trăm người là
đủ để fine-tune một backbone đã pretrained.

Chạy (ví dụ):
  python src/02b_sample_casia.py --n_people 400 --min_images 10 --max_images 30
"""
import argparse
import random
import shutil
from pathlib import Path


def find_identity_root(base: Path) -> Path:
    """
    Tự dò thư mục chứa các thư mục-danh-tính thật, vì file giải nén từ Kaggle
    thường lồng thêm 1-2 lớp thư mục trung gian trước khi tới các ID.
    Điều kiện nhận diện "đúng cấp": thư mục con có chứa trực tiếp ảnh .jpg
    hoặc .png bên trong (không phải lại là thư mục con nữa).
    """
    candidate = base
    for _ in range(4):
        subdirs = [d for d in candidate.iterdir() if d.is_dir()]
        if not subdirs:
            break
        first = subdirs[0]
        has_images_directly = any(first.glob("*.jpg")) or any(first.glob("*.png"))
        if has_images_directly:
            return candidate
        candidate = first
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=str, default="data/casia",
                         help="Thư mục gốc chứa CASIA-WebFace đã giải nén")
    parser.add_argument("--dest", type=str, default="data/casia_subset",
                         help="Thư mục đích để copy tập con vào")
    parser.add_argument("--n_people", type=int, default=400,
                         help="Số người muốn lấy ngẫu nhiên")
    parser.add_argument("--min_images", type=int, default=10,
                         help="Bỏ qua người có ít hơn số ảnh này (đảm bảo đủ dữ liệu/người)")
    parser.add_argument("--max_images", type=int, default=30,
                         help="Chỉ lấy tối đa số ảnh này/người (giảm dung lượng, cân bằng lớp)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--symlink", action="store_true",
                         help="Tạo symlink thay vì copy thật (tiết kiệm dung lượng ổ đĩa, "
                              "cần quyền admin trên Windows để tạo symlink)")
    args = parser.parse_args()

    random.seed(args.seed)

    source_root = find_identity_root(Path(args.source))
    dest_root = Path(args.dest)
    dest_root.mkdir(parents=True, exist_ok=True)

    print(f"Đang quét thư mục danh tính tại: {source_root}")
    all_identities = [d for d in source_root.iterdir() if d.is_dir()]
    print(f"Tổng số người tìm thấy: {len(all_identities)}")

    if len(all_identities) == 0:
        print(f"✗ Không tìm thấy thư mục danh tính nào trong {source_root}.")
        print("  -> Kiểm tra lại --source có đúng đường dẫn CASIA-WebFace đã giải nén chưa.")
        return

    # Lọc những người có đủ số ảnh tối thiểu
    valid_identities = []
    for person_dir in all_identities:
        images = list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png"))
        if len(images) >= args.min_images:
            valid_identities.append((person_dir, images))

    print(f"Số người đủ điều kiện (>= {args.min_images} ảnh): {len(valid_identities)}")

    if len(valid_identities) < args.n_people:
        print(f"⚠ Chỉ có {len(valid_identities)} người đủ điều kiện, ít hơn --n_people "
              f"({args.n_people}). Sẽ lấy hết {len(valid_identities)} người.")
        selected = valid_identities
    else:
        selected = random.sample(valid_identities, args.n_people)

    total_images_copied = 0
    for person_dir, images in selected:
        person_name = person_dir.name
        dest_person_dir = dest_root / person_name
        dest_person_dir.mkdir(parents=True, exist_ok=True)

        # Nếu vượt quá max_images, lấy ngẫu nhiên đúng số lượng cho phép
        chosen_images = images if len(images) <= args.max_images else random.sample(images, args.max_images)

        for img_path in chosen_images:
            dest_img_path = dest_person_dir / img_path.name
            if dest_img_path.exists():
                continue
            if args.symlink:
                dest_img_path.symlink_to(img_path.resolve())
            else:
                shutil.copy2(img_path, dest_img_path)
            total_images_copied += 1

    print(f"\n✓ Hoàn tất: đã copy {len(selected)} người, {total_images_copied} ảnh "
          f"vào {dest_root}")
    print("Bước tiếp theo: chạy src/03_finetune.py để fine-tune trên tập dữ liệu này.")


if __name__ == "__main__":
    main()
