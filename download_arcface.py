import requests
import os

os.makedirs("data/models", exist_ok=True)

url = "https://github.com/deepinsight/insightface/releases/download/v0.7.0/arcface_r50_v1.pth"
response = requests.get(url, stream=True)

if response.status_code == 200:
    with open("data/models/arcface_r50_v1.pth", "wb") as f:
        for chunk in response.iter_content(1024*1024):
            f.write(chunk)
    print("✅ Downloaded!")
else:
    print("❌ Failed:", response.status_code)