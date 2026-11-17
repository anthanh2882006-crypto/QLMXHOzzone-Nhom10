"""Lưu trữ sau khi hoàn tất xử lý kỹ thuật và đánh giá tri thức của dự án."""

from django.conf import settings
from django.db.models import Q
from django.utils.module_loading import import_string
from projectp.models import BaiViet, LanThuPhuongAn


def pending_knowledge_sources(project):
    """Nguồn đã giải quyết còn thiếu kết quả đánh giá hợp lệ, kể cả dữ liệu cũ thiếu hàng chờ."""
    completed = Q(
        muc_cho_tri_thuc__nguoi_danh_gia__isnull=False,
        muc_cho_tri_thuc__danh_gia_luc__isnull=False,
    ) & ~Q(muc_cho_tri_thuc__ly_do_danh_gia="") & ~Q(
        muc_cho_tri_thuc__ket_luan_danh_gia=""
    ) & (
        Q(muc_cho_tri_thuc__trang_thai="khong_tao_bai_hoc")
        | Q(muc_cho_tri_thuc__trang_thai="da_tao_bai_hoc", muc_cho_tri_thuc__bai_hoc__isnull=False)
    )
    return BaiViet.objects.filter(
        du_an=project,
        che_do_xu_ly=True,
        trang_thai_xu_ly=BaiViet.TechnicalStatus.RESOLVED,
    ).exclude(completed)


def archive_reasons(project):
    policy = getattr(settings, "OZZONE_ARCHIVE_POLICY", None)
    if not policy:
        return ["Nhóm cần chốt điều kiện lưu trữ của tổ chức theo UC-PRJ-03 trước khi xác nhận."]
    return list(import_string(policy)(project))


def technical_work_complete(project):
    """Kiểm tra đồng thời xử lý kỹ thuật và kết quả đánh giá tri thức."""
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
    if pending_knowledge_sources(project).exists():
        reasons.append("Dự án còn nguồn chưa hoàn tất đánh giá tri thức. Người phụ trách cần hoàn tất UC-KNW-04 trước khi lưu trữ.")
    return reasons
