"""Phân hệ Cộng đồng — mỗi file ứng với một use case trong báo cáo.

UC-COM-01 Khám phá/Xem cộng đồng   : uc_com_01_kham_pha.py   (community_list, community_about)
UC-COM-02 Tham gia cộng đồng       : uc_com_02_tham_gia.py   (join, cancel_request, join_requests, decide)
UC-COM-03 Rời cộng đồng            : uc_com_03_roi.py        (leave)
UC-COM-04 Xem bảng tin cộng đồng   : uc_com_04_bang_tin.py   (community_detail, post_detail)
UC-COM-05 Xem thành viên cộng đồng : uc_com_05_thanh_vien.py (members)
UC-COM-06 Tạo bài đăng cộng đồng   : uc_com_06_dang_bai.py   (post_create, luu_tep_dinh_kem)
UC-COM-07 Quản trị nội dung        : uc_com_07_quan_tri.py   (moderation_home, moderation, moderate, transfer)
UC-COM-08 Quản trị dữ liệu         : Django Admin (communities/admin.py)
Hàm dùng chung                     : _chung.py               (tu_cach, duoc_doc, ghi_nhat_ky, sidebar, ...)

Xuất các view dùng trong urls.py của phân hệ Cộng đồng.
"""

from ._chung import (
    cong_dong_xem_duoc, du_an_lien_ket, duoc_dang, duoc_doc, ghi_nhat_ky, kich_hoat_thanh_vien,
    la_chu_so_huu, la_quan_tri_noi_dung, lay_cong_dong, sidebar, tu_cach,
)
from .uc_com_01_kham_pha import community_about, community_list
from .uc_com_02_tham_gia import cancel_request, decide, join, join_requests
from .uc_com_03_roi import leave
from .uc_com_04_bang_tin import community_detail, post_detail
from .uc_com_05_thanh_vien import members
from .uc_com_06_dang_bai import luu_tep_dinh_kem, post_create
from .uc_com_07_quan_tri import moderate, moderation, moderation_home, transfer

__all__ = [
    "cong_dong_xem_duoc", "du_an_lien_ket", "duoc_dang", "duoc_doc", "ghi_nhat_ky", "kich_hoat_thanh_vien",
    "la_chu_so_huu", "la_quan_tri_noi_dung", "lay_cong_dong", "sidebar", "tu_cach",
    "community_about", "community_list",
    "cancel_request", "decide", "join", "join_requests",
    "leave",
    "community_detail", "post_detail",
    "members",
    "luu_tep_dinh_kem", "post_create",
    "moderate", "moderation", "moderation_home", "transfer",
]
