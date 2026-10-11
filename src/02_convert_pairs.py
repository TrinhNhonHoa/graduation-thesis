# src/02_convert_pairs.py
import os

LFW_DIR = "data/lfw"
OUTPUT_FILE = os.path.join(LFW_DIR, "pairs_converted.csv")

def convert_pairs():
    with open(OUTPUT_FILE, "w") as out:
        # Header (4 cột)
        out.write("name1,img1,name2,img2\n")

        # Positive pairs
        with open(os.path.join(LFW_DIR, "matchpairsDevTest.csv")) as f:
            next(f)  # bỏ header
            for line in f:
                parts = line.strip().split(",")
                name, img1, img2 = parts[0], parts[1], parts[2]
                out.write(f"{name},{img1},{name},{img2}\n")

        # Negative pairs
        with open(os.path.join(LFW_DIR, "mismatchpairsDevTest.csv")) as f:
            next(f)  # bỏ header
            for line in f:
                parts = line.strip().split(",")
                name1, img1, name2, img2 = parts[0], parts[1], parts[2], parts[3]
                out.write(f"{name1},{img1},{name2},{img2}\n")

    print(f"✅ Done! Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    convert_pairs()