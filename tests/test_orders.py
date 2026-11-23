from app.orders import (DEMO_ORDERS, answer_order_query, extract_order_code,
                        extract_phone, find_order, lookup_order_tool)


def test_demo_orders_loaded():
    assert len(DEMO_ORDERS) >= 10
    assert len({o["code"] for o in DEMO_ORDERS}) == len(DEMO_ORDERS)


def test_extract():
    assert extract_order_code("đơn svn 1001 của mình") == "SVN1001"
    assert extract_phone("sđt 0901 234 567") == "0901234567"
    assert extract_phone("+84901234567") == "0901234567"


def test_lookup_needs_matching_phone():
    assert find_order("SVN1001", "0901234567")["customer"] == "Nguyễn Văn An"
    assert find_order("SVN1001", "0999999999") is None
    assert lookup_order_tool("SVN9999", "0901234567")["found"] is False


def test_answer_flow():
    assert "mã đơn" in answer_order_query("Cho mình hỏi tra cứu đơn hàng")
    assert "số điện thoại" in answer_order_query("đơn SVN1001 của mình đâu rồi")
    out = answer_order_query("SVN1001 0901234567")
    assert "Đang giao" in out and "GHN4829301" in out
    assert "không tìm thấy" in answer_order_query("SVN1001 0999999999")
    assert answer_order_query("Chính sách đổi trả thế nào?") is None


def test_answer_uses_history():
    out = answer_order_query("0901234567", history=["đơn SVN1001 của mình đâu"])
    assert "Đang giao" in out
