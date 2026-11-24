# ResolveAI

Chatbot AI Agent chăm sóc khách hàng cho website thời trang Savani. Hệ thống gồm giao diện chat, trang quản trị và backend FastAPI, chạy trong một container Docker.

## Thành phần

| Thành phần | Mô tả | Địa chỉ mặc định |
|---|---|---|
| Web chat | Giao diện khách hàng trò chuyện với chatbot | `http://localhost:8000/chat/` |
| Trang quản trị | Giao diện cho nhân viên | `http://localhost:8000/admin/` |
| Chatbot nhúng | Nút chat cho trang bán hàng | `http://localhost:8000/` |

## Kiến trúc

`GeminiAgent` dùng Gemini 3.5 Flash-Lite và LangGraph để hiểu yêu cầu, gọi tối đa ba công cụ trong một lượt, rồi trả câu trả lời có kiểm soát.

- `search_kb`: tìm tài liệu chính sách qua Chroma RAG.
- `lookup_order`: tra Mock Order DB sau khi đã xác thực mã đơn và bốn số cuối liên hệ.
- `create_ticket`: Gemini chỉ thu thập và đề nghị Ticket; khách vẫn phải xác nhận và backend mới ghi DB.
- `handoff_to_agent`: chuyển nhân viên khi thiếu căn cứ, cần xử lý ngoài luồng hoặc khách yêu cầu.

Backend vẫn kiểm tra schema công cụ, chống prompt injection/dữ liệu nhạy cảm, kiểm tra nguồn và mức chắc chắn trước khi trả lời. Gemini có thể thử lại lỗi mạng có giới hạn; nếu không lấy được câu trả lời an toàn, cuộc trò chuyện được chuyển nhân viên. Không còn Agent theo từ khóa hoặc cờ chạy mô phỏng.

## Cấu trúc thư mục

```
.
├── app/
│   ├── main.py          # FastAPI và khởi tạo GeminiAgent
│   ├── gemini_agent.py  # workflow LangGraph, tool loop và guard
│   ├── service.py       # nghiệp vụ Ticket, phiên chat, quyền nhân viên
│   ├── tools.py         # allowlist công cụ cho Gemini
│   └── rag.py           # Chroma RAG
├── data/policies/       # sáu tài liệu chính sách nguồn
├── evals/               # các ca đánh giá cố định
├── scripts/             # khởi tạo dữ liệu và chạy eval
├── tests/               # kiểm thử pytest
└── web/                 # giao diện chat, widget, quản trị và cửa hàng demo
```

## Cấu hình và chạy

Sao chép `.env.example` thành `.env`, đặt `GEMINI_API_KEY` trong môi trường chạy, rồi thay `SECRET_KEY` trước khi triển khai.

```env
GEMINI_API_KEY=<khóa Gemini>
LLM_MODEL=gemini-3.5-flash-lite
LLM_FALLBACK_MODEL=
EMBED_MODEL=gemini-embedding-2
```

Chạy với Docker:

```bash
docker compose up --build
```

Hoặc chạy trực tiếp:

```bash
pip install -r requirements.txt
uvicorn app.main:app --workers 1
```

Nếu chưa đặt `GEMINI_API_KEY`, ứng dụng dừng khi khởi động với thông báo cấu hình rõ ràng. Không commit khóa API vào GitHub.

Đặt `SEED_DEMO=1` để nạp phiên chat, Ticket và sáu đơn giả `SVN1001`–`SVN1006` cho demo. Tắt biến này khi chạy thật.

## Kiểm thử và eval

```bash
pip install -r requirements-dev.txt
pytest
```

Các test dùng phản hồi Gemini mô phỏng nên không gửi yêu cầu ra Internet. Để chạy 21 ca đánh giá với Gemini thật sau khi đã cấu hình khóa:

```bash
python -m scripts.run_evals
```

Kết quả được ghi tại `DATA_DIR/evals/latest.json`; eval không tự chạy khi khởi động.

## Dữ liệu và giới hạn hiện tại

- Chroma chạy nhúng, lưu ở `DATA_DIR/chroma`; chỉ mục tự tạo lại khi tài liệu chính sách hoặc model embedding thay đổi.
- Dữ liệu đơn hàng hiện là Mock Order DB, chưa có tích hợp với đơn hàng vận hành thật.
- Trang `/admin/` và `/api/admin/*` đang mở; khi triển khai thật cần đặt sau lớp xác thực phù hợp.
- Chỉ dùng một worker, nên rate limit và khóa phiên nằm trong bộ nhớ.
- Bảng size là thông tin phổ thông; Savani cần xác nhận số đo chính thức trước khi dùng cho tư vấn vận hành.
- Langfuse là tùy chọn; đặt `LANGFUSE_PUBLIC_KEY` và `LANGFUSE_SECRET_KEY` để bật trace. Thiếu hoặc lỗi Langfuse không làm gián đoạn chat.

## Nhúng chatbot

Thêm dòng này trước `</body>` trên website khác:

```html
<script src="https://<máy-chủ-resolveai>/widget/widget.js" defer></script>
```

Widget dùng iframe `/chat/` của chính ResolveAI.
