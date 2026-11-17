"""UC-PRJ-03. Cập nhật dự án, tư cách, vai trò, thiết bị/tài sản và phân công.

Mỗi nhánh có giao dịch riêng, bảo toàn lịch sử và không gán vai trò OWNER theo MANAGER.
"""

import hashlib
import json
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from projectp.models import (
    BaiViet,
    ChoDanhGiaTriThuc,
    CommunityRole,
    CongDong,
    DuAn,
    LanThuPhuongAn,
    MaThietBi,
    MemberStatus,
    NhatKyNghiepVu,
    PhanCongTriThuc,
    ProjectRole,
    TaiSanThietBi,
    ThanhVienCongDong,
    ThanhVienDuAn,
)
from .policies import archive_reasons as configured_archive_reasons, pending_knowledge_sources

SALT = "projects.manage.v1"
PENDING = ("cho_danh_gia", "cho_danh_gia_lai")


def managed_project(user, pk):
    project = get_object_or_404(DuAn.objects.select_related("cong_dong"), pk=pk)
    active = (
        user.is_authenticated
        and get_user_model().objects.filter(pk=user.pk, is_active=True).exists()
    )
    manager = ThanhVienDuAn.objects.filter(
        du_an=project,
        nguoi_dung_id=user.pk,
        trang_thai=MemberStatus.ACTIVE,
        ket_thuc_luc__isnull=True,
        vai_tro=ProjectRole.MANAGER,
    ).exists()
    if not active or not manager:
        raise PermissionDenied("Bạn không có quyền quản lý dự án này.")
    if project.da_luu_tru:
        raise PermissionDenied("Dự án đã lưu trữ, chỉ được đọc theo quyền hiện hành.")
    if project.cong_dong.da_xoa_mem:
        raise ValidationError("Cộng đồng liên kết không còn hợp lệ. Cần xử lý dữ liệu trước.")
    return project


def state(project):
    """Dùng đối chiếu thay đổi và nhật ký, không chứa mật khẩu tài khoản."""
    queries = {
        "du_an": DuAn.objects.filter(pk=project.pk),
        "cong_dong": CongDong.objects.filter(pk=project.cong_dong_id),
        "thanh_vien": ThanhVienDuAn.objects.filter(du_an=project),
        "tu_cach_cong_dong": ThanhVienCongDong.objects.filter(cong_dong_id=project.cong_dong_id),
        "thiet_bi": MaThietBi.objects.filter(du_an=project),
        "tai_san": TaiSanThietBi.objects.filter(ma_the_thiet_bi__du_an=project),
        "phan_cong": PhanCongTriThuc.objects.filter(du_an=project),
        "lan_thu": LanThuPhuongAn.objects.filter(phuong_an__bai_viet__du_an=project),
        "hang_cho": ChoDanhGiaTriThuc.objects.filter(bai_viet_nguon__du_an=project),
    }
    data = {key: list(query.order_by("pk").values()) for key, query in queries.items()}
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder, sort_keys=True))


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def revision(project):
    return signing.dumps(
        {
            "pk": project.pk,
            "updated": project.ngay_cap_nhat.isoformat(),
            "hash": digest(state(project)),
        },
        salt=SALT,
    )


def save_checked(obj):
    obj.full_clean()
    obj.save()


def active_members(project):
    return ThanhVienDuAn.objects.filter(
        du_an=project,
        trang_thai=MemberStatus.ACTIVE,
        ket_thuc_luc__isnull=True,
        nguoi_dung__is_active=True,
    )


def outstanding(project):
    return {
        "issues": BaiViet.objects.filter(
            du_an=project, che_do_xu_ly=True, trang_thai_xu_ly=BaiViet.TechnicalStatus.OPEN
        ).count(),
        "trials": LanThuPhuongAn.objects.filter(
            phuong_an__bai_viet__du_an=project, trang_thai__in=("cho_ket_qua", "dang_thuc_hien")
        ).count(),
        "reviews": pending_knowledge_sources(project).count(),
    }


def archive_reasons(project):
    return configured_archive_reasons(project)


@transaction.atomic
def execute(user, pk, token, action, data, target=None):
    try:
        version = signing.loads(token, salt=SALT, max_age=8 * 60 * 60)
    except signing.BadSignature:
        raise ValidationError("Biểu mẫu không còn hợp lệ. Tải lại trang trước khi lưu.")
    if version["pk"] != pk:
        raise ValidationError("Biểu mẫu không thuộc dự án này.")
    # Lấy khóa ghi trước khi kiểm tra, dùng được cả SQLite và PostgreSQL.
    locked = DuAn.objects.filter(pk=pk, ngay_cap_nhat=parse_datetime(version["updated"])).update(
        ngay_cap_nhat=parse_datetime(version["updated"])
    )
    if not locked:
        raise ValidationError(
            "Dữ liệu đã thay đổi. Giữ nội dung đang nhập và tải lại để đối chiếu."
        )
    project = managed_project(user, pk)
    project.full_clean()
    if not ThanhVienCongDong.objects.filter(
        cong_dong_id=project.cong_dong_id,
        vai_tro=CommunityRole.OWNER,
        trang_thai=MemberStatus.ACTIVE,
        ket_thuc_luc__isnull=True,
        nguoi_dung__is_active=True,
    ).exists():
        raise ValidationError(
            "Cộng đồng dự án cần có OWNER hoạt động. Xử lý qua phân hệ Cộng đồng trước."
        )
    before = state(project)
    if digest(before) != version["hash"]:
        raise ValidationError("Dữ liệu liên quan đã thay đổi. Tải lại để đối chiếu trước khi lưu.")
    now = timezone.now()

    if action == "info":
        project.ten_du_an = data["ten_du_an"]
        project.mo_ta = data["mo_ta"]
        save_checked(project)

    elif action == "member_add":
        person = get_object_or_404(
            get_user_model(),
            pk=data["nguoi_dung"].pk,
            is_active=True,
            ho_so_nhan_vien__isnull=False,
        )
        member, created = ThanhVienDuAn.objects.get_or_create(du_an=project, nguoi_dung=person)
        if not created and member.trang_thai != MemberStatus.ENDED:
            raise ValidationError(
                "Người này đã có tư cách; không tự khôi phục tư cách bị tạm dừng."
            )
        community, com_created = ThanhVienCongDong.objects.get_or_create(
            cong_dong_id=project.cong_dong_id, nguoi_dung=person
        )
        if not com_created and community.trang_thai == MemberStatus.SUSPENDED:
            raise ValidationError(
                "Tư cách cộng đồng đang bị tạm dừng. Cần xử lý theo quyền tương ứng."
            )
        member.vai_tro, member.trang_thai = data["vai_tro"], MemberStatus.ACTIVE
        member.ngay_tham_gia, member.ket_thuc_luc = now, None
        save_checked(member)
        if com_created or community.trang_thai == MemberStatus.ENDED:
            community.vai_tro = CommunityRole.MEMBER
            community.trang_thai, community.ket_thuc_luc = MemberStatus.ACTIVE, None
            community.ngay_tham_gia = now
            save_checked(community)

    elif action in ("member_role", "member_end"):
        member = get_object_or_404(
            ThanhVienDuAn,
            pk=target,
            du_an=project,
            trang_thai=MemberStatus.ACTIVE,
            ket_thuc_luc__isnull=True,
        )
        if action == "member_role" and not member.nguoi_dung.is_active:
            raise ValidationError("Không gán vai trò cho tài khoản đã vô hiệu hóa.")
        removing_manager = action == "member_end" or data["vai_tro"] != ProjectRole.MANAGER
        if member.vai_tro == ProjectRole.MANAGER and removing_manager:
            if (
                not active_members(project)
                .filter(vai_tro=ProjectRole.MANAGER)
                .exclude(pk=member.pk)
                .exists()
            ):
                raise ValidationError("Cần bổ nhiệm quản lý đủ điều kiện khác trước khi thực hiện.")
        if action == "member_role":
            member.vai_tro = data["vai_tro"]
        else:
            community = get_object_or_404(
                ThanhVienCongDong,
                cong_dong_id=project.cong_dong_id,
                nguoi_dung_id=member.nguoi_dung_id,
            )
            if community.vai_tro == CommunityRole.OWNER:
                raise ValidationError(
                    "Cần bàn giao Chủ sở hữu qua UC-COM-07 trước. Vai trò dự án không thay OWNER."
                )
            if PhanCongTriThuc.objects.filter(
                du_an=project, nguoi_phu_trach_id=member.nguoi_dung_id, ket_thuc_luc__isnull=True
            ).exists():
                raise ValidationError("Cần bàn giao hoặc kết thúc phân công tri thức trước.")
            trials = LanThuPhuongAn.objects.filter(
                phuong_an__bai_viet__du_an=project, trang_thai__in=("cho_ket_qua", "dang_thuc_hien")
            )
            if (
                trials.filter(nguoi_thuc_hien_id=member.nguoi_dung_id).exists()
                or trials.filter(
                    nguoi_thuc_hien__isnull=True, nguoi_khoi_tao_id=member.nguoi_dung_id
                ).exists()
            ):
                raise ValidationError(
                    "Thành viên còn lần thử chưa hoàn tất; cần xử lý trách nhiệm trước."
                )
            member.trang_thai, member.ket_thuc_luc = MemberStatus.ENDED, now
            community.trang_thai, community.ket_thuc_luc = MemberStatus.ENDED, now
            save_checked(community)
        save_checked(member)

    elif action == "equipment":
        device = (
            get_object_or_404(MaThietBi, pk=target, du_an=project)
            if target
            else MaThietBi(du_an=project)
        )
        current = (
            list(TaiSanThietBi.objects.filter(ma_the_thiet_bi=device, trang_thai="dang_su_dung"))
            if device.pk
            else []
        )
        if len(current) > 1:
            raise ValidationError(
                "Có nhiều tài sản hiện hành. Cần xử lý toàn vẹn dữ liệu, không tự chọn một tài sản."
            )
        device.ma_thiet_bi, device.ten_thiet_bi = data["ma_thiet_bi"], data["ten_thiet_bi"]
        device.mo_ta, device.dang_su_dung = data["mo_ta"], data["dang_su_dung"]
        replacing = bool(data["tai_san_moi"] or data["ngung_tai_san"])
        if not device.dang_su_dung and (
            data["tai_san_moi"] or (current and not data["ngung_tai_san"])
        ):
            raise ValidationError(
                "Thiết bị ngừng sử dụng cần kết thúc tài sản hiện hành và không gắn tài sản mới."
            )
        save_checked(device)
        if replacing:
            date = data["ngay_thay"]
            if not date or date > timezone.localdate():
                raise ValidationError("Ngày thay tài sản cần có và không được ở tương lai.")
            if date < project.ngay_bat_dau:
                raise ValidationError("Ngày gắn tài sản không được trước ngày bắt đầu dự án.")
            if TaiSanThietBi.objects.filter(
                ma_the_thiet_bi=device, ngay_ket_thuc_su_dung__gt=date
            ).exists():
                raise ValidationError("Ngày thay chồng lên lịch sử tài sản đã có.")
            if current:
                old = current[0]
                if date < old.ngay_bat_dau_su_dung:
                    raise ValidationError("Ngày kết thúc không được trước ngày bắt đầu tài sản cũ.")
                # Không kết thúc lùi ngày làm sai ngữ cảnh của cập nhật đã có.
                if BaiViet.objects.filter(tai_san=old, ngay_tao__date__gt=date).exists():
                    raise ValidationError(
                        "Ngày thay làm sai ngữ cảnh cập nhật cũ. Cần đối chiếu lại."
                    )
                old.trang_thai, old.ngay_ket_thuc_su_dung = "ngung_su_dung", date
                save_checked(old)
            elif data["ngung_tai_san"]:
                raise ValidationError("Thiết bị chưa có tài sản hiện hành để kết thúc.")
            if data["tai_san_moi"]:
                asset = TaiSanThietBi(
                    ma_the_thiet_bi=device,
                    ma_tai_san_noi_bo=data["tai_san_moi"],
                    so_serial=data["so_serial"],
                    ngay_bat_dau_su_dung=date,
                )
                save_checked(asset)

    elif action in ("knowledge", "knowledge_end"):
        if action == "knowledge_end":
            raise ValidationError(
                "Cần bàn giao cho người phụ trách tri thức mới qua chức năng phân công."
            )
        person = get_object_or_404(get_user_model(), pk=data["nguoi_phu_trach"].pk, is_active=True)
        if not active_members(project).filter(nguoi_dung=person).exists():
            raise ValidationError("Người nhận phải là thành viên hợp lệ của đúng dự án.")
        old = PhanCongTriThuc.objects.filter(du_an=project, ket_thuc_luc__isnull=True).first()
        chosen = data.get("thay_phan_cong")
        if chosen and (old is None or chosen.pk != old.pk):
            raise ValidationError("Phân công hiện hành đã thay đổi. Tải lại để đối chiếu.")
        if old and old.nguoi_phu_trach_id == person.pk:
            return
        if old:
            if not data.get("ban_giao"):
                raise ValidationError("Cần xác nhận thay người phụ trách tri thức hiện hành.")
            old.ket_thuc_luc, old.nguoi_ket_thuc = now, user
            save_checked(old)
        new = PhanCongTriThuc(
            du_an=project,
            nguoi_phu_trach=person,
            nguoi_phan_cong=user,
            ngay_phan_cong=now,
            ghi_chu=data["ghi_chu"],
        )
        save_checked(new)
        # Chuyển trách nhiệm hiện hành, giữ người đánh giá và lịch sử các lượt đã lưu.
        ChoDanhGiaTriThuc.objects.filter(
            bai_viet_nguon__du_an=project,
            trang_thai__in=(*PENDING, "khong_tao_bai_hoc"),
        ).update(phan_cong=new, ngay_cap_nhat=now)

    elif action == "archive":
        reasons = archive_reasons(project)
        if reasons:
            raise ValidationError(reasons)
        project.trang_thai = DuAn.Status.ARCHIVED
        project.luu_tru_luc, project.nguoi_luu_tru = now, user
        save_checked(project)
    else:
        raise ValidationError("Thao tác không hợp lệ.")

    DuAn.objects.filter(pk=pk).update(ngay_cap_nhat=now)
    NhatKyNghiepVu.objects.create(
        nguoi_dung=user,
        hanh_dong=f"UC-PRJ-03:{action}",
        loai_tai_nguyen="DU_AN",
        ma_tai_nguyen=str(pk),
        du_lieu_truoc=before,
        du_lieu_sau=state(project),
        ly_do=data.get("ghi_chu", ""),
    )
