import os
import csv
import numpy as np
import torch
from facenet_pytorch import InceptionResnetV1, MTCNN
from PIL import Image
from sklearn.metrics import roc_curve, auc

# --- Configuration ---
IMG_ROOT = "H:/IT-project/data/lfw/lfw-deepfunneled/lfw-deepfunneled"
PAIRS_CSV = "H:/IT-project/data/lfw/pairs_converted.csv"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
LIMIT = None  # None for full evaluation (1000 pairs)

# --- Load model ---
print("Loading FaceNet model...")
resnet = InceptionResnetV1(pretrained='vggface2').eval().to(DEVICE)
mtcnn = MTCNN(image_size=160, keep_all=False, device=str(DEVICE))

embedding_cache = {}

def get_embedding(img_path):
    if img_path in embedding_cache:
        return embedding_cache[img_path]
    img = Image.open(img_path).convert("RGB")
    face = mtcnn(img)
    if face is None:
        embedding_cache[img_path] = None
        return None
    with torch.no_grad():
        emb = resnet(face.unsqueeze(0).to(DEVICE))
    emb_np = emb.squeeze(0).cpu().numpy()
    embedding_cache[img_path] = emb_np
    return emb_np

def load_pairs(csv_path, limit=None):
    """Parse pairs CSV (4 columns: name1, img1, name2, img2) ensuring balanced positive and negative pairs."""
    pos_pairs = []
    neg_pairs = []
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if not row or len(row) < 4:
                continue
            name1, img1, name2, img2 = row[0], int(row[1]), row[2], int(row[3])
            path1 = os.path.join(IMG_ROOT, name1, f"{name1}_{img1:04d}.jpg")
            path2 = os.path.join(IMG_ROOT, name2, f"{name2}_{img2:04d}.jpg")
            if name1 == name2:
                pos_pairs.append((path1, path2))
            else:
                neg_pairs.append((path1, path2))

    if limit is not None:
        half = limit // 2
        pos_pairs = pos_pairs[:half]
        neg_pairs = neg_pairs[:(limit - half)]

    pairs = pos_pairs + neg_pairs
    labels = [1] * len(pos_pairs) + [0] * len(neg_pairs)
    return pairs, labels


if __name__ == "__main__":
    # --- Main evaluation ---
    print("Loading pairs...")
    pairs, labels = load_pairs(PAIRS_CSV, LIMIT)
    print(f"Evaluating {len(pairs)} pairs on {DEVICE}")

    embeddings_1 = []
    embeddings_2 = []

    for i, (p1, p2) in enumerate(pairs):
        if not os.path.exists(p1) or not os.path.exists(p2):
            print(f"[Warning] File not found: {p1} or {p2}")
            embeddings_1.append(np.zeros(512))
            embeddings_2.append(np.zeros(512))
            continue

        e1 = get_embedding(p1)
        e2 = get_embedding(p2)

        if e1 is None or e2 is None:
            embeddings_1.append(np.zeros(512))
            embeddings_2.append(np.zeros(512))
            continue
        embeddings_1.append(e1)
        embeddings_2.append(e2)

        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(pairs)} pairs processed")

    embeddings_1 = np.array(embeddings_1)
    embeddings_2 = np.array(embeddings_2)
    labels = np.array(labels)

    # Compute similarities
    dot_products = np.sum(embeddings_1 * embeddings_2, axis=1)
    norms_1 = np.linalg.norm(embeddings_1, axis=1)
    norms_2 = np.linalg.norm(embeddings_2, axis=1)
    nans_mask = norms_1 * norms_2 == 0  # Avoid division by zero
    similarities = np.where(nans_mask, 0, dot_products / np.maximum(norms_1 * norms_2, 1e-8))

    # Find best threshold using EER
    if len(np.unique(labels)) < 2:
        raise ValueError(f"Evaluation requires both positive and negative pairs. Found labels: {np.unique(labels)}")

    fpr, tpr, thresholds = roc_curve(labels, similarities)
    eer_index = np.nanargmin(np.abs(fpr - (1 - tpr)))
    best_threshold = thresholds[eer_index]

    # Calculate metrics
    predictions = (similarities >= best_threshold).astype(int)
    accuracy = (predictions == labels).mean()
    far = np.mean(predictions[labels == 0]) if np.any(labels == 0) else 0
    frr = np.mean(predictions[labels == 1] == 0) if np.any(labels == 1) else 0

    print("\n===== Results =====")
    print(f"Total pairs: {len(labels)}")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"FAR: {far:.4f}")
    print(f"FRR: {frr:.4f}")
    print(f"EER Threshold: {best_threshold:.4f}")
    print(f"EER: {1 - tpr[eer_index]:.4f}")

    # Save results
    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "baseline_faceNet_results.txt")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(f"FaceNet (VGGFace2 pretrained)\n")
        f.write(f"Total pairs: {len(labels)}\n")
        f.write(f"Accuracy: {accuracy:.4f}\n")
        f.write(f"FAR: {far:.4f}\n")
        f.write(f"FRR: {frr:.4f}\n")
        f.write(f"Threshold: {best_threshold:.4f}\n")

    print(f"\nResults saved to {output_path}")