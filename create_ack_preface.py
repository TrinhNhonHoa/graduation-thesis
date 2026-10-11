# create_ack_preface.py - Tạo file .docx cho Lời cảm ơn và Lời nói đầu
# Chạy: python create_ack_preface.py

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUTPUT_PATH = r"H:\IT-project\Loi_Cam_On_Loi_Noi_Dau.docx"

def add_fmt(doc, text, bold=False, italic=False, size=13, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
            sb=0, sa=5, fi=1.27, ls=1.3, fn="Times New Roman", color=RGBColor(0,0,0), caps=False):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_before = Pt(sb)
    p.paragraph_format.space_after = Pt(sa)
    p.paragraph_format.line_spacing = ls
    p.paragraph_format.first_line_indent = Cm(fi) if fi > 0 else Cm(0)
    run = p.add_run(text)
    run.font.name = fn; run.font.size = Pt(size); run.font.bold = bold; run.font.italic = italic
    run.font.color.rgb = color; run.font.all_caps = caps
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    for k in ["ascii","hAnsi","cs","eastAsia"]: rFonts.set(qn(f"w:{k}"), fn)
    rPr.append(rFonts)
    return p

def add_head(doc, text, size=14, sb=18, sa=4):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(sb)
    p.paragraph_format.space_after = Pt(sa)
    p.paragraph_format.line_spacing = 1.3
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    run.font.name = "Times New Roman"; run.font.size = Pt(size); run.font.bold = True
    run.font.all_caps = True; run.font.color.rgb = RGBColor(0,0,0)
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    for k in ["ascii","hAnsi","cs","eastAsia"]: rFonts.set(qn(f"w:{k}"), "Times New Roman")
    rPr.append(rFonts)
    return p

def setup(doc):
    sec = doc.sections[0]
    sec.page_width = Cm(21.0); sec.page_height = Cm(29.7)
    sec.top_margin = Cm(3.0); sec.bottom_margin = Cm(3.0)
    sec.left_margin = Cm(3.5); sec.right_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"; st.font.size = Pt(13); st.font.color.rgb = RGBColor(0,0,0)
    st.paragraph_format.line_spacing = 1.3; st.paragraph_format.space_after = Pt(4)
    st.paragraph_format.space_before = Pt(0); st.paragraph_format.first_line_indent = Cm(1.27)
    st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

doc = Document(); setup(doc)

# ========== LỜI CẢM ƠN ==========
add_head(doc, "LỜI CẢM ƠN")
add_fmt(doc, "Kính thưa Hội đồng đánh giá Luận văn tốt nghiệp,", sb=10, sa=10, fi=0)
add_fmt(doc, 'Luận văn "Mô hình nhận diện khuôn mặt và ứng dụng Web chấm công nội bộ" là kết quả quá trình nghiên cứu và thực hiện của em dưới sự hướng dẫn tận tâm của thầy TS. Lâm Nhựt Khang - Giảng viên khoa Công nghệ Thông tin, Đại học Cần Thơ. Trong suốt quá trình thực hiện đề tài, em đã nhận được sự hỗ trợ, chia sẻ quý báu từ nhiều phía. Em xin gửi lời tri ân chân thành đến:', sb=0, sa=8)

add_fmt(doc, "Kính thưa Thầy TS. Lâm Nhựt Khang - Cán bộ hướng dẫn luận văn: ", bold=True, sb=6, sa=0)
add_fmt(doc, "Cảm ơn thầy đã dành thời gian quý báu chỉ đạo, định hướng chủ đề, review code, và góp ý chỉnh sửa từng chương, từng mục giúp em hoàn thiện luận văn. Sự am hiểu sâu sắc của thầy về Deep Learning và Computer Vision đã là đòn bẩy then chốt giúp em tiếp cận và áp dụng thành công kiến trúc ArcFace IR-SE50 vào bài toán thực tế.", sb=0, sa=8)

add_fmt(doc, "Kính thưa các Thầy, Cô khoa Công nghệ Thông tin - Đại học Cần Thơ: ", bold=True, sb=6, sa=0)
add_fmt(doc, "Cảm ơn các thầy cô đã truyền授 kiến thức nền tảng vững chắc trong 4 năm học tập, tạo tiền đề cho em có đủ trình độ để thực hiện được đề tài này.", sb=0, sa=8)

add_fmt(doc, "Gửi các bạn đồng môn, bạn bè: ", bold=True, sb=6, sa=0)
add_fmt(doc, "Cảm ơn các bạn đã cùng thảo luận, chia sẻ dữ liệu CASIA-WebFace, hỗ trợ test hệ thống trên nhiều môi trường phần cứng khác nhau (CPU, GPU NVIDIA), và luôn động viên em khi mô hình hội tụ chậm hay gặp lỗi CUDA out-of-memory.", sb=0, sa=8)

add_fmt(doc, "Gửi gia đình: ", bold=True, sb=6, sa=0)
add_fmt(doc, "Cảm ơn bố mẹ, người thân luôn ở bên cạnh, quan tâm, chăm sóc và tạo điều kiện tinh thần, vật chất tốt nhất để em tập trung hoàn thành luận văn đúng hạn.", sb=0, sa=8)

add_fmt(doc, "Luận văn không tránh khỏi những thiếu sót do hạn chế về thời gian, kinh nghiệm và điều kiện phần cứng. Em xin nhận sự góp ý thẳng thắn của Hội đồng để luận văn ngày càng hoàn thiện hơn.", sb=6, sa=18)

add_fmt(doc, "Trịnh Nhơn Hòa", italic=True, align=WD_ALIGN_PARAGRAPH.RIGHT, sb=0, sa=2, fi=0)
add_fmt(doc, "MSSV: B2205868", italic=True, align=WD_ALIGN_PARAGRAPH.RIGHT, sb=0, sa=2, fi=0)
add_fmt(doc, "Ngày … tháng … năm 2026", italic=True, align=WD_ALIGN_PARAGRAPH.RIGHT, sb=0, sa=0, fi=0)

doc.add_page_break()

# ========== LỜI NÓI ĐẦU ==========
add_head(doc, "LỜI NÓI ĐẦU")
add_fmt(doc, "1. Bối cảnh và động lực nghiên cứu", bold=True, size=13, sb=14, sa=6, fi=0)
add_fmt(doc, "Trong kỷ nguyên Công nghiệp 4.0, tự động hóa quy trình quản trị nhân sự đang trở thành yêu cầu tất yếu của mọi tổ chức. Trong đó, chấm công nhân viên - hoạt động diễn ra hàng ngày, lặp lại nhiều lần - vẫn còn nhiều điểm thủ công, tốn nhân lực, dễ phát sinh sai sót và gian lận (chấm công hộ, mạo danh). Các giải pháp thẻ từ, vân tay truyền thống tồn tại nhược điểm: thẻ dễ mất/quên, vân tay bị mờ do môi trường làm việc, và quan trọng hơn - không thể chống giả mạo (spoofing) bằng ảnh in hoặc màn hình điện thoại.")
add_fmt(doc, "Nhận diện khuôn mặt (Face Recognition) dựa trên Deep Learning đã đạt độ chính xác ngang ngửa con người trên các benchmark quốc tế (LFW, MegaFace). Tuy nhiên, triển khai vào hệ thống thực tế (production) đặt ra thách thức mới: Open-set recognition (nhận diện người mới không cần re-train), Real-time inference (< 200ms/frame trên edge device), và Anti-spoofing (phân biệt người thật vs ảnh/video giả).")
add_fmt(doc, "Đề tài này ra đời từ thực trạng đó: xây dựng một hệ thống chấm công hoàn chỉnh, sẵn sàng triển khai, kết hợp ArcFace IR-SE50 (SOTA face embedding), MTCNN (detection/alignment), và module Anti-Spoofing 4 tầng tự thiết kế - tất cả gói gọn trong kiến trúc Flask + SQLite nhẹ, không phụ thuộc server phức tạp.")

add_fmt(doc, "2. Mục tiêu nghiên cứu", bold=True, size=13, sb=14, sa=6, fi=0)
add_fmt(doc, "Luận văn tập trung giải quyết 3 mục tiêu cốt lõi:")

for i, obj in enumerate([
    "Nghiên cứu và áp dụng ArcFace IR-SE50 cho bài toán Open-set Face Recognition: Fine-tuning trên tập con CASIA-WebFace để thích nghi với điều kiện ánh sáng, góc chụp thực tế tại Việt Nam.",
    "Thiết kế module Anti-Spoofing đa đặc trưng (Sharpness + FFT Moiré + Skin Color + Micro-motion) hoạt động real-time trên CPU/GPU, chống được 2 kiểu tấn công phổ biến: Print Attack và Replay/Screen Attack.",
    "Xây dựng hệ thống Web end-to-end: Kiosk Live Cam (điểm danh tự động >60% similarity), Admin Dashboard (CRUD nhân viên, lọc chấm công ngày/tuần/tháng, xuất CSV/in ấn), cơ sở dữ liệu SQLite tích hợp."
], 1):
    add_fmt(doc, f"{i}. {obj}", fi=0, sb=2, sa=2)

add_fmt(doc, "3. Phạm vi nghiên cứu", bold=True, size=13, sb=14, sa=6, fi=0)
for item in [
    "Tập dữ liệu huấn luyện: Subset CASIA-WebFace (200-400 IDs, 10-30 ảnh/ID).",
    "Tập đánh giá: LFW (6.000 cặp ảnh, 10-fold cross-validation).",
    "Phần cứng: CPU Intel/AMD hoặc GPU NVIDIA CUDA (RTX 2060+ khuyến nghị).",
    "Môi trường: Windows/Linux, Python 3.10+, PyTorch 2.0+, Flask."
]:
    add_fmt(doc, f"• {item}", fi=0, sb=2, sa=2)

add_fmt(doc, "4. Cấu trúc luận văn", bold=True, size=13, sb=14, sa=6, fi=0)
add_fmt(doc, "Luận văn gồm 5 chương:")
for title, desc in [
    ("Chương 1 - Tổng quan", "Bối cảnh, vấn đề, mục tiêu, phạm vi, phương pháp, đóng góp, cấu trúc."),
    ("Chương 2 - Cơ sở lý thuyết", "Pipeline 4 giai đoạn Face Recognition, MTCNN, ArcFace Loss, IR-SE50, Anti-Spoofing theory, Metrics (Accuracy/FAR/FRR/EER/AUC)."),
    ("Chương 3 - Phương pháp thực hiện", "Kiến trúc hệ thống, Thu thập dữ liệu (02a_decode_mxnet_rec, 02b_sample_casia), Fine-tuning (03_finetune), Module Liveness (liveness.py), Thiết kế DB, Web App (app.py, templates, static)."),
    ("Chương 4 - Thí nghiệm & Kết quả", "So sánh Baseline FaceNet vs Fine-tuned ArcFace trên LFW (Accuracy, EER, AUC, Latency), Ablation study các tầng Anti-Spoofing, Stress test Kiosk thực tế."),
    ("Chương 5 - Kết luận & Hướng phát triển", "Tóm tắt đóng góp, hạn chế (chưa chống Deepfake video, latency trên CPU cao), mở rộng: MobileNet/Edge deployment, FAISS index cho 10k+ nhân viên, tích hợp HRM/ERP.")
]:
    add_fmt(doc, f"• {title}: {desc}", fi=0, sb=2, sa=2)

add_fmt(doc, "5. Đóng góp chính của luận văn", bold=True, size=13, sb=14, sa=6, fi=0)
for i, contrib in enumerate([
    "Hệ thống hoàn chỉnh, chạy được ngay (production-ready): Code mở nguồn, không phụ thuộc cloud API, chi phí triển khai = 0 VNĐ license.",
    "Module Anti-Spoofing 4 tầng tự thiết kế không dùng model nặng (Silent-Face-Anti-Spoofing ~50MB) mà chỉ dùng OpenCV/NumPy (~200KB), phù hợp edge device yếu.",
    "Pipeline Fine-tuning ArcFace tự động hóa từ MXNet .rec → PyTorch .pth → best_model.pth, tái sử dụng cho các đề tài sau.",
    "Giao diện Kiosk hiện thực: HUD scanner, real-time liveness feedback, cooldown logic, âm thanh xác nhận - trải nghiệm UX tốt cho người dùng cuối."
], 1):
    add_fmt(doc, f"{i}. {contrib}", fi=0, sb=2, sa=2)

add_fmt(doc, "Mong luận văn là tài liệu tham khảo hữu ích cho các bạn sinh viên, nhà nghiên cứu quan tâm đến Face Recognition ứng dụng thực tế.", sb=12, sa=18)
add_fmt(doc, "Trịnh Nhơn Hòa", italic=True, align=WD_ALIGN_PARAGRAPH.RIGHT, sb=0, sa=2, fi=0)
add_fmt(doc, "MSSV: B2205868", italic=True, align=WD_ALIGN_PARAGRAPH.RIGHT, sb=0, sa=2, fi=0)
add_fmt(doc, "Ngày … tháng … năm 2026", italic=True, align=WD_ALIGN_PARAGRAPH.RIGHT, sb=0, sa=0, fi=0)

doc.save(OUTPUT_PATH)
print(f"Đã tạo file: {OUTPUT_PATH}")