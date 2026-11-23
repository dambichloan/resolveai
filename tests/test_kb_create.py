"""Thêm tài liệu KB thủ công từ trang quản trị."""
import pytest

from app.service import ApiError


@pytest.fixture
def kbsvc(make, tmp_path):
    pdir = tmp_path / "policies"
    svc = make(policies_dir=pdir)
    return svc, pdir


def test_create_writes_file_and_is_listed(kbsvc):
    svc, pdir = kbsvc
    d = svc.kb_create("Chính sách thành viên", "## Ưu đãi\n- Giảm 5% cho khách thân thiết.", "policy", "2026-11-23")
    assert d["doc_code"] == "KB-01" and d["is_active"] and d["effective_date"] == "2026-11-23"
    assert (pdir / "chinh-sach-thanh-vien.md").exists()
    assert "Giảm 5%" in svc.kb_get("KB-01")["content"]
    d2 = svc.kb_create("Câu hỏi về quà tặng", "Quà tặng không áp dụng đổi trả.")
    assert d2["doc_code"] == "KB-02"
    assert [x["doc_code"] for x in svc.kb_list()] == ["KB-01", "KB-02"]


def test_validation(kbsvc):
    svc, _ = kbsvc
    for args in [("", "x"), ("t", "  "), ("t" * 201, "x"), ("t", "x" * 20001), ("t", "x", "evil"), ("t", "x", "policy", "23/11")]:
        with pytest.raises(ApiError) as e:
            svc.kb_create(*args)
        assert e.value.status == 422
    svc.kb_create("Trùng tên", "a")
    with pytest.raises(ApiError) as e:
        svc.kb_create("trùng tên", "b")
    assert e.value.status == 409


def test_title_newline_cannot_inject_front_matter(kbsvc):
    svc, _ = kbsvc
    d = svc.kb_create("Tên\nis_active: false", "nội dung")
    assert d["is_active"] is True and "\n" not in d["title"]


def test_agent_is_reloaded(make, tmp_path):
    class A:
        called = 0
        def reload_kb(self):
            A.called += 1
        def run_turn(self, inp):
            raise AssertionError
    svc = make(agent=A(), policies_dir=tmp_path / "p")
    svc.kb_create("Tài liệu mới", "nội dung")
    assert A.called == 1

