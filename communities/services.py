"""Kiểm tra bàn giao OWNER dùng chung cho COM-07 và COM-08."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from projectp.models import CommunityRole, CongDong, DuAn, MemberStatus, ThanhVienDuAn


def lock_community(pk):
    DuAn.objects.filter(cong_dong_id=pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    CongDong.objects.filter(pk=pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    return CongDong.objects.get(pk=pk)


@transaction.atomic
def handover_roles(community, previous_id, recipient_id):
    community = lock_community(community.pk)
    project = DuAn.objects.filter(cong_dong=community).first()
    if community.da_xoa_mem or (project and project.da_luu_tru):
        raise ValidationError("Cộng đồng không còn hoạt động hoặc dự án đã lưu trữ.")
    memberships = community.thanh_vien.filter(trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True)
    previous = memberships.filter(pk=previous_id, vai_tro=CommunityRole.OWNER).first()
    recipient = memberships.filter(pk=recipient_id, nguoi_dung__is_active=True).first()
    if previous is None or recipient is None:
        raise ValidationError("OWNER cũ hoặc người nhận không còn tư cách hợp lệ.")
    if community.loai_cong_dong == CongDong.Type.PROJECT:
        if (
            project is None
            or not ThanhVienDuAn.objects.filter(
                du_an=project,
                nguoi_dung=recipient.nguoi_dung,
                trang_thai=MemberStatus.ACTIVE,
                ket_thuc_luc__isnull=True,
                nguoi_dung__is_active=True,
            ).exists()
        ):
            raise ValidationError("Người nhận cần tư cách dự án liên kết đang hoạt động.")
    if previous.pk == recipient.pk or recipient.vai_tro == CommunityRole.OWNER:
        raise ValidationError("Người nhận đã là OWNER; không thực hiện bàn giao trùng.")
    before = {"chu_so_huu_cu": previous.nguoi_dung_id, "vai_tro_nguoi_nhan": recipient.vai_tro}
    recipient.vai_tro = CommunityRole.OWNER
    recipient.full_clean()
    recipient.save()
    previous.vai_tro = CommunityRole.MEMBER
    previous.full_clean()
    previous.save()
    return before, {"chu_so_huu_cu": previous.nguoi_dung_id, "chu_so_huu_moi": recipient.nguoi_dung_id}
