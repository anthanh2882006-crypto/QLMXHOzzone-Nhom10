"""Phân hệ Tài khoản — mỗi file ứng với một use case trong báo cáo.

UC-ACC-01 Đăng nhập          : uc_acc_01_dang_nhap.py   (OzzoneLoginView, after_login, first_password)
UC-ACC-02 Đăng xuất          : uc_acc_02_dang_xuat.py   (logout_view, account_settings)
UC-ACC-03 Hồ sơ cá nhân      : uc_acc_03_ho_so.py       (profile, profile_edit)
UC-ACC-04 Tra cứu nhân viên  : uc_acc_04_tra_cuu.py     (directory, employee_detail)
UC-ACC-05 Quản trị tài khoản : Django Admin (accounts/admin.py)
Hàm dùng chung               : _chung.py                (can_doi_mat_khau, ho_ten, thong_tin_ho_so)

Xuất các view dùng trong urls.py và phân hệ Cộng đồng.
"""

from ._chung import can_doi_mat_khau, da_doi_mat_khau, ho_ten, thong_tin_ho_so
from .uc_acc_01_dang_nhap import OzzoneLoginView, after_login, first_password
from .uc_acc_02_dang_xuat import account_settings, logout_view
from .uc_acc_03_ho_so import profile, profile_edit
from .uc_acc_04_tra_cuu import directory, employee_detail

__all__ = [
    "can_doi_mat_khau", "da_doi_mat_khau", "ho_ten", "thong_tin_ho_so",
    "OzzoneLoginView", "after_login", "first_password",
    "account_settings", "logout_view",
    "profile", "profile_edit",
    "directory", "employee_detail",
]
