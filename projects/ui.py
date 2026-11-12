"""Đồng bộ trạng thái hiển thị của vấn đề giữa tổng quan, bảng tin và chi tiết."""

from django.db.models import Exists, OuterRef
from projectp.models import KetQuaThu, LanThuPhuongAn


def with_issue_state(posts):
    """Chỉ bổ sung thông tin trình bày cho tập bài đã được kiểm tra quyền đọc."""
    trials = LanThuPhuongAn.objects.filter(phuong_an__bai_viet_id=OuterRef("pk"))
    results = KetQuaThu.objects.filter(
        lan_thu__phuong_an__bai_viet_id=OuterRef("pk"),
        lan_thu__trang_thai="da_co_ket_qua",
    )
    return posts.annotate(
        ui_pending=Exists(
            trials.filter(
                trang_thai__in=["cho_ket_qua", "dang_thuc_hien"], ket_qua__isnull=True
            )
        ),
        ui_success=Exists(results.filter(thanh_cong=True)),
        ui_failed=Exists(results.filter(thanh_cong=False)),
    )
