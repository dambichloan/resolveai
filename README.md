# ResolveAI

Chatbot AI Agent chăm sóc khách hàng (CSKH) cho website thời trang **Savani**.

Hệ thống gồm giao diện chat cho khách hàng, trang quản trị cho nhân viên và Backend FastAPI, đóng gói trong một container bằng `docker-compose`.

> **Trạng thái:** khung mẫu (Mục 25 của báo cáo). Agent hiện tại là Agent mẫu theo từ khóa, cần thay bằng Agent LangGraph thật. Xem phần [Giới hạn đã biết](#giới-hạn-đã-biết).

## Mục lục

- [Thành phần](#thành-phần)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Cấu hình](#cấu-hình)
- [Kiểm thử](#kiểm-thử)
- [Thay Agent mẫu bằng Agent LangGraph](#thay-agent-mẫu-bằng-agent-langgraph)
- [Quy ước](#quy-ước)
- [Giới hạn đã biết](#giới-hạn-đã-biết)

## Thành phần

| Thành phần | Mô tả | Địa chỉ mặc định |
|---|---|---|
| Web chat | Giao diện khách hàng trò chuyện với chatbot | https://resolveai-4ly7.onrender.com/ |
| Trang quản trị | Giao diện cho nhân viên | https://resolveai-4ly7.onrender.com/admin/ |

## Cấu trúc thư mục

```
.
├── app/
│   ├── main.py          # lớp HTTP mỏng (FastAPI), hàm build_agent()
│   ├── service.py       # toàn bộ nghiệp vụ, không phụ thuộc framework
│   ├── agent_port.py    # hợp đồng (interface) với Agent
│   └── stub_agent.py    # Agent MẪU theo từ khóa (dùng khi FAKE_LLM=1)
├── web/
│   ├── chat/            # giao diện chat khách hàng (HTML/JS thuần)
│   └── admin/           # giao diện quản trị nhân viên (HTML/JS thuần)
├── scripts/             # script hỗ trợ (khởi tạo dữ liệu, admin...)
├── tests/               # kiểm thử pytest
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

Phần `web/` không cần bước build.

## Cấu hình

Sao chép `.env.example` thành `.env` rồi chỉnh các giá trị. Các biến chính:

| Biến | Ý nghĩa |
|---|---|
| `SECRET_KEY` | Khóa bí mật của ứng dụng, **bắt buộc đổi** ||
| `FAKE_LLM` | `1` để dùng Agent mẫu theo từ khóa, không gọi LLM thật |
| `HOTLINE` | Số hotline hiển thị cho khách: `0888.566.599` |

Xem `.env.example` để biết đầy đủ các biến.

## Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest
```

## Thay Agent mẫu bằng Agent LangGraph

Agent mẫu nằm ở `app/stub_agent.py`. Để dùng Agent thật (Mục 20):

1. Hiện thực `AgentPort.run_turn(AgentInput) -> AgentOutput` theo hợp đồng trong `app/agent_port.py`.
2. Trả về Agent mới trong hàm `build_agent()` ở `app/main.py`.

Agent chỉ đề nghị tạo Ticket/Handoff. Backend (`app/service.py`) tự kiểm tra điều kiện rồi mới ghi DB.

## Quy ước

- **Mã Ticket** theo BR5: `TK-YYYYMMDDXXXX` (không có dấu gạch giữa ngày và số thứ tự).
- **Hotline:** `0888.566.599`, cấu hình qua biến `HOTLINE`.

## Giới hạn đã biết

Những điểm cần team quyết định hoặc hiện thực tiếp:

- **API quản lý KB** (`/api/admin/kb/*`): hiện trả về `501 Not Implemented`.
- **Chỉ 1 worker:** giới hạn tần suất (rate limit) và khóa phiên nằm trong bộ nhớ.
- **EX-COM-04:** tạo Ticket ngoài giờ khi Handoff, chưa làm.
- **Khóa phiên bản thư viện:** chạy `pip freeze` để cố định phiên bản trước khi nộp.
- **Gemini miễn phí:** nếu dùng gói miễn phí thì chỉ nạp dữ liệu mẫu.
