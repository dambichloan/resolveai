"""Backup/retention: dữ liệu bền vững và không lỗi khi kho Chroma chưa tạo."""
from app.operations import backup_once, retain_application_data


def test_backup_and_retention_scaffold(make, tmp_path):
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "sample.md").write_text("nội dung", encoding="utf-8")
    svc = make(policies_dir=policies)
    retain_application_data(svc.db, svc.s)
    destination = backup_once(svc.s)
    assert (destination / "app.db").exists()
    assert (destination / "policies" / "sample.md").read_text(encoding="utf-8") == "nội dung"
