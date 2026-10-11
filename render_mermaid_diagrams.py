#!/usr/bin/env python
"""
Script render các sơ đồ Mermaid thành PNG/SVG chất lượng cao.
Yêu cầu: pip install playwright && playwright install chromium
"""
import asyncio
import os
from pathlib import Path

# Thư mục đầu ra
OUTPUT_DIR = Path(r"H:\IT-project\IMG")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Các sơ đồ Mermaid (dictionary: filename -> mermaid_code)
DIAGRAMS = {
    "01_system_architecture": """
flowchart TB
    subgraph Client["🖥️ Client Side"]
        Kiosk["Kiosk Live Cam\n(HTML5 + JS + WebRTC)"]
        Admin["Admin Dashboard\n(HTML5 + JS)"]
    end
    
    subgraph Server["⚙️ Server Side (Flask)"]
        API["RESTful API\n/app.py"]
        MTCNN["MTCNN\nDetection + Alignment"]
        Liveness["LivenessDetector\nAnti-Spoofing 4 tầng"]
        ArcFace["ArcFace IR-SE50\nEmbedding 512-d"]
        Matcher["Cosine Matching\nRAM Cache"]
        DB["SQLite\nattendance.db"]
    end
    
    Kiosk -->|"Video frames\n(900ms/frame)"| API
    Admin -->|"CRUD requests"| API
    API --> MTCNN
    MTCNN --> Liveness
    Liveness -->|"Live face"| ArcFace
    ArcFace --> Matcher
    Matcher -->|"Best match > 60%"| DB
    DB -->|"Log attendance"| API
    API -->|"JSON response"| Kiosk
    API -->|"JSON response"| Admin
""",
    "02_recognition_pipeline": """
flowchart TD
    A["📷 Webcam Frame\n640x480 @30fps"] --> B["MTCNN Detection\nP-Net → R-Net → O-Net"]
    B -->|"No face"| B
    B -->|"Face + 5 Landmarks"| C["Liveness Detection\n4-layer Anti-Spoofing"]
    C -->|"Score < 0.60"| D["⚠️ Spoof Alert\nBlock attendance"]
    C -->|"Score ≥ 0.60"| E["Face Alignment\nAffine Transform 112x112"]
    E --> F["ArcFace IR-SE50\nForward Pass"]
    F --> G["Embedding 512-d\nL2 Normalized"]
    G --> H["Cosine Similarity\nvs RAM Cache"]
    H -->|"Max Sim < 0.60"| I["❌ Unknown Person\nLog mismatch"]
    H -->|"Max Sim ≥ 0.60"| J["✅ Matched: Name + Code"]
    J --> K["Cooldown Check\n25 seconds"]
    K -->|"In cooldown"| L["⏳ Skip logging"]
    K -->|"Ready"| M["💾 Log to SQLite\nUpdate Live Feed"]
    M --> N["🔊 Success Sound\n📱 Kiosk Popup"]
""",
    "03_mtcnn_architecture": """
flowchart TD
    Input["Input Image\nMulti-scale Pyramid"]
    
    subgraph PNet["P-Net (Proposal Network)"]
        P1["Fully Conv Net\n12x12 receptive field"]
        P2["Output: Candidate boxes\n+ BBox regression\n+ NMS"]
    end
    
    subgraph RNet["R-Net (Refine Network)"]
        R1["CNN + FC Layers\n24x24 input"]
        R2["Output: Refined boxes\n+ Confidence score\n+ NMS"]
    end
    
    subgraph ONet["O-Net (Output Network)"]
        O1["Deep CNN\n48x48 input"]
        O2["Output: Final boxes\n+ 5 Landmarks\n(x2 eyes, nose, mouth x2)"]
    end
    
    Input --> PNet
    PNet -->|"Candidates"| RNet
    RNet -->|"Refined"| ONet
    ONet --> Final["Final: BBox + 5 Landmarks\n→ Face Alignment"]
    
    style PNet fill:#e3f2fd
    style RNet fill:#fff3e0
    style ONet fill:#e8f5e9
""",
    "04_arcface_loss_geometry": """
flowchart LR
    subgraph Hypersphere["🔵 Unit Hypersphere (S^511)"]
        Wi["W_j (Class Centers)\n||W_j|| = 1"]
        xi["x_i (Face Embedding)\n||x_i|| = 1"]
        theta["θ = arccos(W_j^T · x_i)"]
        margin["+ m (Additive Margin)"]
        theta_m["θ + m"]
        logits["s · cos(θ + m)"]
    end
    
    xi -->|"cos(θ)"| theta
    theta -->|"+ m"| theta_m
    theta_m -->|"× s"| logits
    logits --> Softmax["Softmax + CrossEntropy"]
    
    classDef geo fill:#f3e5f5,stroke:#7b1fa2
    class Hypersphere,Wi,xi,theta,margin,theta_m,logits geo
""",
    "05_liveness_detection": """
flowchart TD
    Face["Face Crop\nfrom BBox"] --> T1["Tầng 1: Sharpness\nLaplacian Variance"]
    Face --> T2["Tầng 2: FFT Moiré\n2D Frequency Analysis"]
    Face --> T3["Tầng 3: Skin Color\nYCrCb + HSV Distribution"]
    Face --> T4["Tầng 4: Micro-Motion\nLandmark Dynamics 5s"]
    
    T1 -->|"S_sharp ∈ [0,1]"| Ensemble["Weighted Ensemble"]
    T2 -->|"S_fft ∈ [0,1]"| Ensemble
    T3 -->|"S_color ∈ [0,1]"| Ensemble
    T4 -->|"S_motion ∈ [0,1]"| Ensemble
    
    Ensemble -->|"Score = 0.25·S_sharp +\n0.25·S_fft + 0.30·S_color +\n0.20·S_motion"| Decision{"Score ≥ 0.60?"}
    Decision -->|"Yes"| Live["✅ LIVE PERSON\nProceed to ArcFace"]
    Decision -->|"No"| Spoof["🚫 SPOOF DETECTED\nBlock + Alert"]
    
    classDef layer fill:#e8f5e9,stroke:#2e7d32
    class T1,T2,T3,T4 layer
""",
    "06_finetuning_flow": """
flowchart TD
    Pretrained["Pretrained IR-SE50\n(MS1M / VGGFace2)"]
    CASIA["CASIA-WebFace\nSubset: 200-400 IDs\n10-30 img/ID"]
    
    Pretrained --> Freeze["Freeze Backbone\n(80% params)"]
    CASIA --> DataLoader["DataLoader\nAug: Flip + Normalize"]
    
    Freeze --> Model["IR-SE50 Backbone\n+ ArcFace Head\n(num_classes = subset IDs)"]
    DataLoader --> Model
    
    Model --> Train["Training Loop\nSGD, lr=0.001\nMomentum=0.9"]
    Train --> Val["Validation\nAccuracy per epoch"]
    Val -->|"Best val_acc"| Checkpoint["best_model.pth"]
    Val -->|"Every epoch"| Ckpt["epoch_N.pth"]
    
    Checkpoint --> Export["Export to\nmodels/best_model.pth"]
    Export --> App["app.py loads\nACTIVE_MODEL_PATH"]
""",
    "07_database_erd": """
erDiagram
    ADMINS ||--o{ ATTENDANCE_LOGS : "manages"
    EMPLOYEES ||--o{ ATTENDANCE_LOGS : "generates"
    
    ADMINS {
        INTEGER id PK
        TEXT username UK
        TEXT password_hash
        TEXT full_name
        TIMESTAMP created_at
    }
    
    EMPLOYEES {
        INTEGER id PK
        TEXT emp_code UK
        TEXT name
        TEXT department
        TEXT position
        TEXT avatar_file
        TEXT embedding_file
        TIMESTAMP created_at
    }
    
    ATTENDANCE_LOGS {
        INTEGER id PK
        INTEGER emp_id FK
        TEXT emp_code
        TEXT emp_name
        TEXT timestamp
        TEXT date
        TEXT time
        TEXT check_type
        REAL similarity
        TEXT status
        TEXT note
    }
""",
    "08_evaluation_comparison": """
flowchart LR
    subgraph FaceNet["FaceNet Baseline (VGGFace2)"]
        FN_Acc["Accuracy: 99.2%"]
        FN_FAR["FAR: 0.8%"]
        FN_FRR["FRR: 1.2%"]
        FN_EER["EER: 1.0%"]
        FN_AUC["AUC: 0.998"]
        FN_Lat["Latency: 12.5 ms"]
    end
    
    subgraph ArcFace["ArcFace IR-SE50 Fine-tuned"]
        AF_Acc["Accuracy: 99.8%"]
        AF_FAR["FAR: 0.2%"]
        AF_FRR["FRR: 0.4%"]
        AF_EER["EER: 0.3%"]
        AF_AUC["AUC: 0.999"]
        AF_Lat["Latency: 15.2 ms"]
    end
    
    style FaceNet fill:#e3f2fd
    style ArcFace fill:#e8f5e9
""",
    "09_enrollment_sequence": """
sequenceDiagram
    participant Admin
    participant Frontend
    participant Backend
    participant MTCNN
    participant ArcFace
    participant DB
    participant Cache
    
    Admin->>Frontend: Mở modal "Thêm nhân viên"
    Admin->>Frontend: Nhập mã NV, tên, PB, CV
    Admin->>Frontend: Tải ảnh / Chụp webcam
    Frontend->>Backend: POST /api/admin/employees\n(form-data: info + image)
    Backend->>MTCNN: Detect + Align face
    MTCNN-->>Backend: Aligned face 112x112
    Backend->>ArcFace: Forward pass
    ArcFace-->>Backend: Embedding 512-d
    Backend->>DB: INSERT employees\n(avatar.jpg + embedding.npy)
    DB-->>Backend: emp_id
    Backend->>Cache: reload_face_cache()
    Cache-->>Backend: Updated cache
    Backend-->>Frontend: JSON {success, emp_id}
    Frontend-->>Admin: Toast "Thêm thành công"
    Frontend->>Frontend: Cập nhật bảng nhân viên
""",
    "10_kiosk_state_diagram": """
stateDiagram-v2
    [*] --> INIT: App start
    INIT --> LOADING_MODELS: Load ArcFace + MTCNN
    LOADING_MODELS --> IDLE: Models ready
    
    IDLE --> DETECTING: New frame from cam
    DETECTING --> NO_FACE: No face found
    DETECTING --> LIVENESS_CHECK: Face + landmarks
    
    NO_FACE --> IDLE: Wait next frame
    
    LIVENESS_CHECK --> SPOOF_DETECTED: Score < 0.60
    LIVENESS_CHECK --> EXTRACTING: Score ≥ 0.60
    
    SPOOF_DETECTED --> IDLE: Show alert, wait
    
    EXTRACTING --> MATCHING: Embedding ready
    MATCHING --> LOW_SIM: Max sim < 0.60
    MATCHING --> HIGH_SIM: Max sim ≥ 0.60
    
    LOW_SIM --> IDLE: Show mismatch
    HIGH_SIM --> COOLDOWN_CHECK: Check 25s cooldown
    COOLDOWN_CHECK --> LOGGED: Ready
    COOLDOWN_CHECK --> SKIP_LOG: In cooldown
    
    LOGGED --> IDLE: Update DB + Cache + UI
    SKIP_LOG --> IDLE: Update UI only
""",
    "11_deployment_diagram": """
flowchart TB
    subgraph LAN["🏢 Mạng nội bộ Doanh nghiệp"]
        subgraph Server["🖥️ Server (Windows/Linux)"]
            Flask["Flask App :5000\napp.py"]
            Models["Models/\nbest_model.pth\nmodel_ir_se50.pth"]
            DBFile["data/attendance.db"]
            FaceDB["data/face_db/\n*.npy embeddings"]
            Avatars["data/avatars/\n*.jpg"]
        end
        
        subgraph Kiosk["📱 Trạm Kiosk (Cửa vào)"]
            Browser1["Chrome/Edge Kiosk Mode\nhttp://server:5000"]
            Cam1["Webcam USB\n1080p/30fps"]
        end
        
        subgraph AdminPC["💻 Máy Quản trị"]
            Browser2["Browser\nhttp://server:5000/admin"]
        end
    end
    
    Browser1 -->|HTTP/WS| Flask
    Browser2 -->|HTTP| Flask
    Cam1 -->|Video frames| Browser1
    Flask --> Models
    Flask --> DBFile
    Flask --> FaceDB
    Flask --> Avatars
    
    Internet((🌐 Internet)) -.->|Optional: VPN/Remote| AdminPC
""",
    "12_roc_det_curves": """
flowchart LR
    subgraph ROC["ROC Curve (LFW 6000 pairs)"]
        direction TB
        TPR["True Positive Rate\n(1 - FRR)"]
        FPR["False Positive Rate\n(FAR)"]
        AUC["AUC ≈ 0.999"]
        EER["EER ≈ 0.3%"]
    end
    
    subgraph DET["DET Curve (Log scale)"]
        direction TB
        FRR_d["FRR %"]
        FAR_d["FAR %"]
        Cross["Cross point = EER"]
    end
    
    subgraph Threshold["Threshold Analysis"]
        direction TB
        Th06["> 0.60 (Yêu cầu đề tài)"]
        ThEER["EER Threshold"]
        ThOpt["Optimal Operating Point"]
    end
    
    style ROC fill:#e3f2fd
    style DET fill:#fff3e0
    style Threshold fill:#e8f5e9
"""
}

# HTML template để render mermaid
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            themeVariables: {{
                primaryColor: '#1a1a2e',
                primaryTextColor: '#fff',
                primaryBorderColor: '#0f3460',
                lineColor: '#333',
                background: '#ffffff',
                fontFamily: 'Arial, sans-serif',
                fontSize: '14px'
            }},
            flowchart: {{
                useMaxWidth: true,
                htmlLabels: true,
                curve: 'basis'
            }},
            sequence: {{
                actorMargin: 50,
                boxMargin: 10,
                noteMargin: 10
            }},
            er: {{
                diagramPadding: 20
            }},
            state: {{
                padding: 15
            }}
        }});
    </script>
    <style>
        body {{ margin: 0; padding: 20px; background: white; }}
        .mermaid {{ text-align: center; }}
        svg {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <div class="mermaid">
{mermaid_code}
    </div>
</body>
</html>
"""


async def render_diagram(page, mermaid_code, output_path, format="png", scale=2):
    """Render một sơ đồ Mermaid thành file ảnh."""
    html_content = HTML_TEMPLATE.format(mermaid_code=mermaid_code.strip())
    
    # Tạo file HTML tạm
    temp_html = output_path.with_suffix('.html')
    temp_html.write_text(html_content, encoding='utf-8')
    
    # Mở trong browser
    await page.goto(temp_html.as_uri(), wait_until='networkidle')
    
    # Đợi mermaid render xong
    await page.wait_for_function("() => document.querySelector('.mermaid svg') !== null")
    await page.wait_for_timeout(1000)  # Đợi thêm 1s cho animation
    
    # Lấy element SVG
    svg_element = await page.query_selector('.mermaid svg')
    if not svg_element:
        raise Exception("Không tìm thấy SVG sau khi render")
    
    if format == "svg":
        # Lấy SVG content
        svg_content = await svg_element.evaluate("el => el.outerHTML")
        output_path.write_text(svg_content, encoding='utf-8')
    else:
        # Chụp screenshot PNG
        await svg_element.screenshot(path=str(output_path), type=format)
    
    # Xóa file HTML tạm
    temp_html.unlink(missing_ok=True)
    print(f"  Da luu: {output_path.name}")


async def main():
    from playwright.async_api import async_playwright
    
    print(f"Thu muc dau ra: {OUTPUT_DIR}")
    print(f"Tong so so do: {len(DIAGRAMS)}")
    print("-" * 50)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        for name, mermaid_code in DIAGRAMS.items():
            try:
                # Render PNG (chất lượng cao)
                png_path = OUTPUT_DIR / f"{name}.png"
                await render_diagram(page, mermaid_code, png_path, format="png", scale=2)
                
                # Render SVG (vector, phóng to không mờ)
                svg_path = OUTPUT_DIR / f"{name}.svg"
                await render_diagram(page, mermaid_code, svg_path, format="svg")
                
            except Exception as e:
                print(f"  Loi {name}: {e}")
        
        await browser.close()
    
    print("-" * 50)
    print("Hoan tat render tat ca so do!")
    print(f"Kiem tra thu muc: {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())