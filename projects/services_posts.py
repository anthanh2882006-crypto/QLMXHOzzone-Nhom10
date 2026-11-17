"""UC-PRJ-01, UC-05, UC-06. Khởi tạo đầy đủ và giữ ngữ cảnh tài sản lúc ghi."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from projectp.models import (
    BaiViet,
    CommunityRole,
    CongDong,
    DuAn,
    MaThietBi,
    MemberStatus,
    TaiSanThietBi,
    ThanhVienCongDong,
    ThanhVienDuAn,
)
from .permissions import explicit_permission
from .services_common import attach_files, command, save_model


def current_asset(device):
    assets = list(TaiSanThietBi.objects.filter(ma_the_thiet_bi=device, trang_thai="dang_su_dung"))
    if len(assets) > 1:
        raise ValidationError(
            "Mã thiết bị có nhiều tài sản hoạt động. Cần xử lý toàn vẹn dữ liệu trước."
        )
    return assets[0] if assets else None


def device_context(device):
    asset = current_asset(device)
    return f"{device.pk}|{device.ngay_cap_nhat.isoformat()}|{asset.pk if asset else ''}|{asset.ngay_cap_nhat.isoformat() if asset else ''}"


def create_project(user, data):
    with command(user, "UC-PRJ-01", data["request_token"], data) as task:
        if not explicit_permission(user, "add_duan"):
            raise PermissionDenied("Tài khoản chưa được gán quyền tạo dự án của tổ chức.")
        if not task["replay"]:
            community = save_model(
                CongDong(
                    ten_cong_dong=data["ten_du_an"],
                    mo_ta=data["mo_ta"],
                    loai_cong_dong=CongDong.Type.PROJECT,
                    quy_tac_tham_gia=CongDong.JoinRule.PROJECT_MANAGED,
                    pham_vi_truy_cap=data["pham_vi_truy_cap"],
                    nguoi_tao=user,
                )
            )
            project = save_model(
                DuAn(
                    ma_du_an_nghiep_vu=data["ma_du_an_nghiep_vu"],
                    ten_du_an=data["ten_du_an"],
                    mo_ta=data["mo_ta"],
                    ngay_bat_dau=data["ngay_bat_dau"],
                    cong_dong=community,
                    nguoi_tao=user,
                )
            )
            save_model(
                ThanhVienDuAn(
                    du_an=project,
                    nguoi_dung=user,
                    vai_tro="quan_ly",
                    trang_thai=MemberStatus.ACTIVE,
                )
            )
            save_model(
                ThanhVienCongDong(
                    cong_dong=community,
                    nguoi_dung=user,
                    vai_tro=CommunityRole.OWNER,
                    trang_thai=MemberStatus.ACTIVE,
                )
            )
            task["result_id"] = project.pk
    return task["result_id"]


def create_post(user, project, data, device=None):
    action = "UC-PRJ-06" if device else "UC-PRJ-05"
    kind = BaiViet.Kind.FIELD_UPDATE if device else BaiViet.Kind.STANDARD
    if data.get("loai_bai_viet", kind) != kind:
        raise ValidationError("Loại nội dung không phù hợp với chức năng đang mở.")
    # Loại bài do lối vào xác định và được loại khỏi nội dung kiểm tra gửi lặp.
    request_data = {key: value for key, value in data.items() if key != "loai_bai_viet"}
    with command(
        user, action, data["request_token"], request_data, project.pk, device.pk if device else None
    ) as task:
        if not task["replay"]:
            asset = None
            if device:
                device = MaThietBi.objects.filter(
                    pk=device.pk, du_an=task["project"], dang_su_dung=True
                ).first()
                if device is None:
                    raise ValidationError(
                        "Thiết bị không còn hoạt động trong dự án. Nội dung nhập được giữ để đối chiếu."
                    )
                if device_context(device) != data["asset_context"]:
                    raise ValidationError(
                        "Ngữ cảnh thiết bị/tài sản đã thay đổi. Nội dung nhập được giữ, hãy đối chiếu ngữ cảnh mới và gửi lại."
                    )
                asset = current_asset(device)
            technical = data["che_do_xu_ly"]
            post = save_model(
                BaiViet(
                    du_an=task["project"],
                    cong_dong_id=task["project"].cong_dong_id,
                    nguoi_dang=user,
                    tieu_de=data["tieu_de"],
                    noi_dung=data["noi_dung"],
                    loai_bai_viet=kind,
                    che_do_xu_ly=technical,
                    ma_the_thiet_bi=device,
                    tai_san=asset,
                    trang_thai_xu_ly=(
                        BaiViet.TechnicalStatus.OPEN if technical else BaiViet.TechnicalStatus.NONE
                    ),
                    chua_giai_quyet_luc=timezone.now() if technical else None,
                )
            )
            attach_files(user, data["minh_chung"], {"bai_viet": post}, task["files"])
            task["result_id"] = post.pk
            task["audit"] = {
                "post_id": post.pk,
                "device_id": device.pk if device else None,
                "asset_id": asset.pk if asset else None,
            }
    return task["result_id"]
