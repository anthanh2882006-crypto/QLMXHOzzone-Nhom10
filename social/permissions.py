"""Quyền truy cập hiện hành cho bảng tin OZZONE.

Không dùng việc đã lưu bài hoặc từng nhận thông báo làm căn cứ tự cấp quyền đọc.
"""

from django.db.models import F, Q
from django.core.exceptions import ObjectDoesNotExist
from projects.permissions import readable_projects

from projectp.models import (
    BaiViet,
    CongDong,
    DuAn,
    MemberStatus,
    ThanhVienCongDong,
)


def _is_active_user(user):
    return bool(user and user.is_authenticated and user.is_active)


def accessible_posts(user, include_hidden=False):
    """Queryset bài không phải thông báo chính thức mà user được đọc lúc này.

    - Bài cấp công ty: không gắn cộng đồng/dự án.
    - Bài cộng đồng: cộng đồng nội bộ hoặc user đang là thành viên hoạt động.
    - Bài dự án: user phải là thành viên dự án hoạt động.
    """
    if not _is_active_user(user):
        return BaiViet.objects.none()

    community_ids = ThanhVienCongDong.objects.filter(
        nguoi_dung=user,
        trang_thai=MemberStatus.ACTIVE,
        ket_thuc_luc__isnull=True,
        cong_dong__loai_cong_dong=CongDong.Type.GENERAL,
        cong_dong__da_xoa_mem=False,
    ).values_list("cong_dong_id", flat=True)

    project_ids = readable_projects(user).values_list("pk", flat=True)

    company_scope = Q(cong_dong__isnull=True, du_an__isnull=True)
    community_scope = Q(
        du_an__isnull=True,
        cong_dong__loai_cong_dong=CongDong.Type.GENERAL,
        cong_dong__da_xoa_mem=False,
        cong_dong__pham_vi_truy_cap="noi_bo",
    ) | Q(du_an__isnull=True, cong_dong_id__in=community_ids)
    project_scope = (
        Q(du_an_id__in=project_ids) & (Q(cong_dong__isnull=True) | Q(cong_dong_id=F("du_an__cong_dong_id")))
    ) | Q(du_an__isnull=True, cong_dong__loai_cong_dong=CongDong.Type.PROJECT, cong_dong__du_an_lien_ket__in=project_ids)

    qs = BaiViet.objects.filter(company_scope | community_scope | project_scope)
    qs = qs.filter(
        da_xoa_mem=False,
        loai_bai_viet__in=[BaiViet.Kind.STANDARD, BaiViet.Kind.FIELD_UPDATE],
    )
    if not include_hidden:
        qs = qs.filter(trang_thai="hien")
    return qs.select_related("nguoi_dang", "cong_dong", "du_an", "cong_dong__du_an_lien_ket")


def can_create_company_post(user):
    """Nhân viên hoạt động có hồ sơ hoặc người có quyền Django được đăng bài cá nhân."""
    if not _is_active_user(user):
        return False
    if user.is_superuser or user.has_perm("projectp.add_baiviet"):
        return True
    from projectp.models import HoSoNhanVien

    return HoSoNhanVien.objects.filter(nguoi_dung=user).exists()


def protected_source_reason(post):
    """Trả lý do nếu bài/tệp là nguồn đã tham gia luồng kỹ thuật hoặc tri thức."""
    if post.loai_bai_viet == BaiViet.Kind.ANNOUNCEMENT:
        return "Bài thông báo chính thức được quản lý theo quy trình riêng và không thể sửa tại đây."

    if post.phuong_an.exists():
        return "Bài viết đã được dùng làm nguồn cho phương án xử lý kỹ thuật."
    from projectp.models import NguonThamKhao

    if NguonThamKhao.objects.filter(bai_viet_nguon=post).exists():
        return "Bài viết đang được tham chiếu làm nguồn tri thức."

    # Các quan hệ OneToOne có related_name trong projectp.models.
    for relation, message in (
        ("ket_luan_xu_ly", "Bài viết đã tham gia kết luận xử lý kỹ thuật."),
        ("muc_cho_tri_thuc", "Bài viết đang/đã tham gia quy trình đánh giá tri thức."),
        ("bai_hoc_kinh_nghiem", "Bài viết đã được chuẩn hóa thành bài học kinh nghiệm."),
    ):
        try:
            getattr(post, relation)
        except ObjectDoesNotExist:
            continue
        else:
            return message

    # Một tệp từ bài viết nếu được liên kết lại làm minh chứng ở kết quả/bài học/
    # phiên bản tri thức/phương án thì cũng không được gỡ khỏi nguồn ban đầu.
    from projectp.models import DinhKem

    file_ids = DinhKem.objects.filter(bai_viet=post).values_list("tep_tin_id", flat=True)
    if (
        DinhKem.objects.filter(tep_tin_id__in=file_ids)
        .exclude(bai_viet=post)
        .filter(
            Q(ket_qua_thu__isnull=False)
            | Q(bai_hoc__isnull=False)
            | Q(phien_ban_tri_thuc__isnull=False)
            | Q(phuong_an__isnull=False)
        )
        .exists()
    ):
        return "Tệp của bài viết đã được sử dụng làm minh chứng cho nội dung nghiệp vụ khác."

    if post.du_an_id and post.du_an.trang_thai == DuAn.Status.ARCHIVED:
        return "Dự án đã lưu trữ; không cho phép sửa nội dung vận hành."

    return ""


def moderation_block_reason(post, action):
    if action == "hide" and post.che_do_xu_ly and post.trang_thai_xu_ly == BaiViet.TechnicalStatus.OPEN:
        return "Vấn đề kỹ thuật đang mở. Cần hoàn tất xử lý trước khi xem xét ẩn nội dung."
    return protected_source_reason(post)


def can_manage_own_post(user, post):
    if not _is_active_user(user):
        return False, "Bạn cần đăng nhập bằng tài khoản đang hoạt động."
    if post.nguoi_dang_id != user.pk:
        return False, "Bạn chỉ được quản lý bài viết do chính mình tạo."
    if post.da_xoa_mem:
        return False, "Bài viết đã được xóa mềm."
    if post.loai_bai_viet not in {BaiViet.Kind.STANDARD, BaiViet.Kind.FIELD_UPDATE}:
        return False, "Loại nội dung này được quản lý qua quy trình riêng."
    if post.du_an_id:
        if not readable_projects(user).filter(pk=post.du_an_id).exists():
            return False, "Bạn không còn tư cách thành viên trong dự án này."
    elif post.cong_dong_id:
        from communities.views._chung import duoc_dang, tu_cach

        if not duoc_dang(post.cong_dong, tu_cach(user, post.cong_dong)):
            return False, "Bạn không còn quyền đăng hoặc sửa bài trong cộng đồng này."
    elif not can_create_company_post(user):
        return False, "Bạn không còn quyền đăng bài tại bảng tin công ty."
    if post.che_do_xu_ly and post.trang_thai_xu_ly == BaiViet.TechnicalStatus.RESOLVED:
        return False, "Bài viết đã tham gia kết luận xử lý kỹ thuật."
    reason = protected_source_reason(post)
    if reason:
        return False, reason
    if post.che_do_xu_ly:
        return False, "Vấn đề kỹ thuật được xử lý trong đúng không gian dự án."
    return True, ""
