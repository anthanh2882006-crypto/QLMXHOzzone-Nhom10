"""Điều kiện thao tác Dự án được nhóm chốt ngày 11/11/2026.

Một dự án có tối đa một phân công tri thức đang hiệu lực.
Một vấn đề có tối đa một lần thử đang chờ kết quả.
Lưu trữ yêu cầu hoàn tất xử lý kỹ thuật, vẫn giữ nguồn chờ đánh giá tri thức.
"""

from django.conf import settings
from django.utils.module_loading import import_string
from projectp.models import BaiViet, LanThuPhuongAn


def curator_limit():
    return getattr(settings, "OZZONE_KNOWLEDGE_MAX_ACTIVE", None)


def trial_limit():
    return getattr(settings, "OZZONE_MAX_PENDING_TRIALS", None)


def archive_reasons(project):
    policy = getattr(settings, "OZZONE_ARCHIVE_POLICY", None)
    if not policy:
        return ["Nhóm cần chốt điều kiện lưu trữ của tổ chức theo UC-PRJ-03 trước khi xác nhận."]
    return list(import_string(policy)(project))


def technical_work_complete(project):
    """Trả các việc kỹ thuật cần hoàn tất trước khi quản lý xác nhận lưu trữ."""
    reasons = []
    if BaiViet.objects.filter(
        du_an=project,
        che_do_xu_ly=True,
        trang_thai_xu_ly=BaiViet.TechnicalStatus.OPEN,
    ).exists():
        reasons.append("Dự án còn vấn đề chưa giải quyết.")
    if LanThuPhuongAn.objects.filter(
        phuong_an__bai_viet__du_an=project,
        trang_thai__in=("cho_ket_qua", "dang_thuc_hien"),
    ).exists():
        reasons.append("Dự án còn lần thử đang chờ kết quả.")
    return reasons
