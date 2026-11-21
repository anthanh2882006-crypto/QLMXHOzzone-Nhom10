"""UC-PRJ-10. Chỉ trình bày các trường lịch sử thuộc nhóm thao tác đã chọn.

Snapshot nhật ký có dữ liệu nhiều nhóm. Màn chi tiết lọc nhóm và trường để tránh
hiển thị nội dung nguồn kỹ thuật chỉ từ quyền xem nhật ký quản lý.
"""

from django.contrib.auth import get_user_model

from accounts.views._chung import ho_ten
from projectp.models import MaThietBi

SCHEMAS = {
    "du_an": (
        "Thông tin dự án",
        "ma_du_an",
        "du_an_id",
        {
            "ma_du_an_nghiep_vu": "Mã dự án",
            "ten_du_an": "Tên dự án",
            "mo_ta": "Mô tả",
            "trang_thai": "Trạng thái",
            "luu_tru_luc": "Thời điểm lưu trữ",
            "nguoi_luu_tru_id": "Người lưu trữ",
        },
    ),
    "thanh_vien": (
        "Tư cách dự án",
        "ma_thanh_vien",
        "du_an_id",
        {
            "nguoi_dung_id": "Người dùng",
            "vai_tro": "Vai trò",
            "trang_thai": "Trạng thái tư cách",
            "ngay_tham_gia": "Bắt đầu tư cách",
            "ket_thuc_luc": "Kết thúc tư cách",
        },
    ),
    "thiet_bi": (
        "Thiết bị",
        "ma_the_thiet_bi",
        "du_an_id",
        {
            "ma_thiet_bi": "Mã thiết bị",
            "ten_thiet_bi": "Tên thiết bị",
            "mo_ta": "Mô tả",
            "dang_su_dung": "Đang sử dụng",
        },
    ),
    "tai_san": (
        "Tài sản",
        "ma_tai_san",
        "ma_the_thiet_bi_id",
        {
            "ma_the_thiet_bi_id": "Thiết bị",
            "ma_tai_san_noi_bo": "Mã tài sản",
            "so_serial": "Số serial",
            "trang_thai": "Trạng thái tài sản",
            "ngay_bat_dau_su_dung": "Ngày bắt đầu",
            "ngay_ket_thuc_su_dung": "Ngày kết thúc",
        },
    ),
    "phan_cong": (
        "Phân công tri thức",
        "ma_phan_cong",
        "du_an_id",
        {
            "nguoi_phu_trach_id": "Người phụ trách",
            "nguoi_phan_cong_id": "Người phân công",
            "ngay_phan_cong": "Bắt đầu phân công",
            "ket_thuc_luc": "Kết thúc phân công",
            "nguoi_ket_thuc_id": "Người kết thúc",
            "ghi_chu": "Căn cứ / lý do",
        },
    ),
}

ACTION_GROUPS = {
    "info": ("du_an",),
    "archive": ("du_an",),
    "member_add": ("thanh_vien",),
    "member_role": ("thanh_vien",),
    "member_end": ("thanh_vien",),
    "equipment": ("thiet_bi", "tai_san"),
    "knowledge": ("phan_cong",),
    "knowledge_end": ("phan_cong",),
}

STATUS_LABELS = {
    "quan_ly": "Quản lý dự án",
    "thanh_vien": "Thành viên",
    "hoat_dong": "Hoạt động",
    "da_roi": "Đã kết thúc tư cách",
    "tam_dung": "Tạm dừng",
    "dang_thuc_hien": "Đang thực hiện",
    "hoan_thanh": "Hoàn thành",
    "luu_tru": "Lưu trữ",
    "dang_su_dung": "Đang sử dụng",
    "ngung_su_dung": "Ngừng sử dụng",
}

PERSON_FIELDS = {
    "nguoi_luu_tru_id", "nguoi_dung_id", "nguoi_phu_trach_id",
    "nguoi_phan_cong_id", "nguoi_ket_thuc_id",
}
DEVICE_FIELD = "ma_the_thiet_bi_id"


def snapshot_changes(log, project):
    """Lấy chênh lệch an toàn theo phạm vi của chính dự án và hành động trong nhật ký."""
    before = log.du_lieu_truoc if isinstance(log.du_lieu_truoc, dict) else {}
    after = log.du_lieu_sau if isinstance(log.du_lieu_sau, dict) else {}
    action = log.hanh_dong.split(":")[-1]
    allowed_devices = set()
    for snapshot in (before, after):
        device_records = snapshot.get("thiet_bi", [])
        if not isinstance(device_records, list):
            continue
        for record in device_records:
            if isinstance(record, dict) and record.get("du_an_id") == project.pk:
                allowed_devices.add(record.get("ma_the_thiet_bi"))
    changes = []
    person_ids = set()
    device_ids = set()
    for group in ACTION_GROUPS.get(action, ()):
        title, pk_field, scope_field, fields = SCHEMAS[group]

        def records(snapshot):
            result = {}
            stored = snapshot.get(group, [])
            if not isinstance(stored, list):
                return result
            for record in stored:
                if not isinstance(record, dict):
                    continue
                in_scope = (
                    record.get(scope_field) in allowed_devices
                    if group == "tai_san"
                    else record.get(scope_field) == project.pk
                )
                if group == "du_an":
                    in_scope = record.get(pk_field) == project.pk
                if in_scope:
                    result[record.get(pk_field)] = record
            return result

        previous, current = records(before), records(after)
        for record_id in sorted(previous.keys() | current.keys(), key=str):
            old, new = previous.get(record_id, {}), current.get(record_id, {})
            for field, label in fields.items():
                if old.get(field) == new.get(field):
                    continue
                old_value, new_value = old.get(field), new.get(field)
                if field in PERSON_FIELDS:
                    person_ids.update(value for value in (old_value, new_value) if isinstance(value, int))
                if field == DEVICE_FIELD:
                    device_ids.update(value for value in (old_value, new_value) if isinstance(value, int))
                changes.append((title, field, label, old_value, new_value))

    people = {pk: ho_ten(user) for pk, user in get_user_model().objects.in_bulk(person_ids).items()}
    devices = {
        pk: name or code
        for pk, name, code in MaThietBi.objects.filter(du_an=project, pk__in=device_ids).values_list(
            "pk", "ten_thiet_bi", "ma_thiet_bi"
        )
    }
    references = dict.fromkeys(PERSON_FIELDS, people)
    references[DEVICE_FIELD] = devices
    return [
        {
            "group": title,
            "field": label,
            "before": display(old, references.get(field)),
            "after": display(new, references.get(field)),
        }
        for title, field, label, old, new in changes
    ]


def display(value, labels=None):
    if value is None or value == "":
        return "—"
    if labels is not None:
        return labels.get(value, "Không còn thông tin") if isinstance(value, int) else "Không còn thông tin"
    if isinstance(value, bool):
        return "Có" if value else "Không"
    return STATUS_LABELS.get(str(value), str(value))
