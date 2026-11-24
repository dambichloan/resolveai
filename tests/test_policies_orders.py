"""Mock order access and legacy policy repository remain usable."""
import pytest

from app.db import Database
from app.mock_orders import MockOrderStore
from app.policies import PolicyRepo
from app.service import ApiError


def test_order_lookup_requires_verification(tmp_path):
    orders = MockOrderStore(tmp_path / "orders.db")
    assert orders.lookup("SVN1001") is None
    assert orders.lookup("SVN1001", "0000") is None
    order = orders.lookup("svn1001", "1122")
    assert order["status"] == "Đang vận chuyển"
    assert "phone_last4" not in order and "email" not in order
    assert orders.lookup("SVN1001", email="minhanh@example.demo") == order


def test_policy_repository_create_update_delete(tmp_path):
    db = Database(tmp_path / "app.db")
    db.init()
    kb = PolicyRepo(db)
    kb.seed_defaults()
    item = kb.create("Chính sách thanh toán", "Savani nhận thanh toán bằng tiền mặt và ví MoMo.")
    assert "ví MoMo" in kb.text()
    assert kb.search("thanh toán bằng momo")["id"] == item["id"]
    kb.update(item["id"], item["title"], "Chỉ nhận chuyển khoản.")
    assert "Chỉ nhận chuyển khoản" in kb.text()
    kb.delete(item["id"])
    assert all(d["id"] != item["id"] for d in kb.list())


def test_policy_validation(tmp_path):
    db = Database(tmp_path / "app.db")
    db.init()
    kb = PolicyRepo(db)
    with pytest.raises(ApiError):
        kb.create("", "x")
    with pytest.raises(ApiError):
        kb.update(9999, "a", "b")
