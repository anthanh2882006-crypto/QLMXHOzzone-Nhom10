import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from projectp.models import (
    BaiViet,
    DinhKem,
    NguoiNhanThongBao,
    NhatKyNghiepVu,
    ThongBaoChinhThuc,
    ThongBaoHeThong,
    TieuChiThongBao,
)
from social.services import _save_attachments

from .permissions import can_manage_draft, can_publish_notices, can_read_notice, resolve_scope_user_ids


CRITERION_FIELDS = {
    "phong_ban": "phong_ban",
    "cong_dong": "cong_dong",
    "du_an": "du_an",
    "nguoi_dung": "nguoi_dung",
}


def _audit(*, user, notice, action, before=None, after=None, request=None, request_key=None):
    NhatKyNghiepVu.objects.create(
        nguoi_dung=user,
        hanh_dong=action,
        loai_tai_nguyen="THONG_BAO_CHINH_THUC",
        ma_tai_nguyen=str(notice.pk),
        du_lieu_truoc=before,
        du_lieu_sau=after,
        ma_yeu_cau=request_key or uuid.uuid4(),
        dia_chi_ip=request.META.get("REMOTE_ADDR") if request else None,
        thoi_diem=timezone.now(),
    )


def _criteria_payload(cleaned):
    return {
        "doc": {
            "phong_ban": cleaned.get("doc_phong_ban", []),
            "cong_dong": cleaned.get("doc_cong_dong", []),
            "du_an": cleaned.get("doc_du_an", []),
            "nguoi_dung": cleaned.get("doc_nguoi_dung", []),
        },
        "phan_phoi": {
            "phong_ban": cleaned.get("phan_phoi_phong_ban", []),
            "cong_dong": cleaned.get("phan_phoi_cong_dong", []),
            "du_an": cleaned.get("phan_phoi_du_an", []),
            "nguoi_dung": cleaned.get("phan_phoi_nguoi_dung", []),
        },
    }


def _replace_criteria(notice, cleaned):
    TieuChiThongBao.objects.filter(thong_bao=notice).delete()
    payload = _criteria_payload(cleaned)
    if notice.che_do_doc == "toan_cong_ty":
        payload["doc"] = {key: [] for key in payload["doc"]}
    if notice.che_do_phan_phoi == "toan_cong_ty":
        payload["phan_phoi"] = {key: [] for key in payload["phan_phoi"]}
    rows = []
    for purpose, groups in payload.items():
        for kind, objects in groups.items():
            for target in objects:
                criterion = TieuChiThongBao(
                    thong_bao=notice,
                    muc_dich="doc" if purpose == "doc" else "phan_phoi",
                    loai_tieu_chi=kind,
                    **{kind: target},
                )
                criterion.full_clean()
                rows.append(criterion)
    if rows:
        TieuChiThongBao.objects.bulk_create(rows)


def _remove_draft_attachments(notice, attachment_ids):
    if not attachment_ids:
        return
    attachments = DinhKem.objects.filter(
        bai_viet=notice.bai_viet,
        pk__in=[item.pk for item in attachment_ids],
    ).select_related("tep_tin")
    for attachment in attachments:
        file_record = attachment.tep_tin
        attachment.delete()
        if not DinhKem.objects.filter(tep_tin=file_record).exists():
            file_record.da_xoa_mem = True
            file_record.trang_thai = "da_go"
            file_record.save(update_fields=["da_xoa_mem", "trang_thai", "ngay_cap_nhat"])


def _save_notice_attachments(notice, user, files, remove_ids, request=None):
    current_count = DinhKem.objects.filter(bai_viet=notice.bai_viet).count()
    removal_count = DinhKem.objects.filter(
        bai_viet=notice.bai_viet,
        pk__in=[item.pk for item in remove_ids],
    ).count()
    if current_count - removal_count + len(files) > 5:
        raise ValidationError("Mỗi thông báo được đính kèm tối đa 5 tệp.")
    _remove_draft_attachments(notice, remove_ids)
    if not files:
        return []
    return _save_attachments(notice.bai_viet, user, files, request=request)


def save_notice_draft(*, user, cleaned, files=(), notice=None, request=None):
    """Create/update an unpublished official-notice draft and its file/criteria links."""
    if not can_publish_notices(user):
        raise PermissionDenied("Tài khoản không có quyền phát hành thông báo chính thức.")
    if notice is not None and not can_manage_draft(user, notice):
        raise PermissionDenied("Bạn không được biên tập bản nháp này hoặc bản nháp đã được công bố.")
    reference = cleaned.get("thong_bao_tham_chieu")
    if reference is not None:
        from .permissions import can_read_notice
        if reference.trang_thai != "da_cong_bo" or not can_read_notice(user, reference):
            raise PermissionDenied("Bạn không có quyền tham chiếu thông báo này để đính chính.")

    created_storage_names = []
    try:
        with transaction.atomic():
            if notice is not None:
                notice = ThongBaoChinhThuc.objects.select_for_update().select_related("bai_viet").get(pk=notice.pk)
                if not can_manage_draft(user, notice):
                    raise PermissionDenied("Bản nháp đã thay đổi trạng thái hoặc bạn không còn quyền biên tập.")
                post = BaiViet.objects.select_for_update().get(pk=notice.bai_viet_id)
                before = {
                    "tieu_de": post.tieu_de,
                    "noi_dung": post.noi_dung,
                    "che_do_doc": notice.che_do_doc,
                    "che_do_phan_phoi": notice.che_do_phan_phoi,
                }
                post.tieu_de = cleaned.get("tieu_de", "").strip()
                post.noi_dung = cleaned["noi_dung"].strip()
                post.trang_thai = "an"  # Bản nháp không được lộ ở bảng tin.
                post.phien_ban_noi_dung += 1
                post.full_clean()
                post.save(update_fields=["tieu_de", "noi_dung", "trang_thai", "phien_ban_noi_dung", "ngay_cap_nhat"])
                notice.che_do_doc = cleaned["che_do_doc"]
                notice.che_do_phan_phoi = cleaned["che_do_phan_phoi"]
                notice.yeu_cau_xac_nhan = bool(cleaned.get("yeu_cau_xac_nhan"))
                notice.phien_ban_cau_hinh += 1
                reference = cleaned.get("thong_bao_tham_chieu")
                notice.thong_bao_tham_chieu = reference
                notice.full_clean()
                notice.save(update_fields=[
                    "che_do_doc", "che_do_phan_phoi", "yeu_cau_xac_nhan",
                    "phien_ban_cau_hinh", "thong_bao_tham_chieu", "ngay_cap_nhat",
                ])
                _replace_criteria(notice, cleaned)
                _validate_notice_audience(notice, require_recipients=False)
                created_storage_names = _save_notice_attachments(
                    notice, user, files, cleaned.get("remove_attachment_ids", []), request=request
                )
                _audit(
                    user=user, notice=notice, action="cap_nhat_ban_nhap_thong_bao_chinh_thuc",
                    before=before,
                    after={"tieu_de": post.tieu_de, "che_do_doc": notice.che_do_doc,
                           "che_do_phan_phoi": notice.che_do_phan_phoi,
                           "yeu_cau_xac_nhan": notice.yeu_cau_xac_nhan,
                           "phien_ban_cau_hinh": notice.phien_ban_cau_hinh},
                    request=request,
                )
            else:
                post = BaiViet(
                    nguoi_dang=user,
                    loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
                    tieu_de=cleaned.get("tieu_de", "").strip(),
                    noi_dung=cleaned["noi_dung"].strip(),
                    trang_thai="an",
                )
                post.full_clean()
                post.save()
                notice = ThongBaoChinhThuc(
                    bai_viet=post,
                    nguoi_phu_trach=user,
                    che_do_doc=cleaned["che_do_doc"],
                    che_do_phan_phoi=cleaned["che_do_phan_phoi"],
                    yeu_cau_xac_nhan=bool(cleaned.get("yeu_cau_xac_nhan")),
                    trang_thai="ban_nhap",
                    thong_bao_tham_chieu=cleaned.get("thong_bao_tham_chieu"),
                )
                notice.full_clean()
                notice.save()
                _replace_criteria(notice, cleaned)
                _validate_notice_audience(notice, require_recipients=False)
                created_storage_names = _save_notice_attachments(
                    notice, user, files, cleaned.get("remove_attachment_ids", []), request=request
                )
                _audit(
                    user=user, notice=notice, action="tao_ban_nhap_thong_bao_chinh_thuc",
                    after={"tieu_de": post.tieu_de, "che_do_doc": notice.che_do_doc,
                           "che_do_phan_phoi": notice.che_do_phan_phoi,
                           "yeu_cau_xac_nhan": notice.yeu_cau_xac_nhan},
                    request=request,
                )
        return notice
    except Exception:
        for stored_name in created_storage_names:
            try:
                default_storage.delete(stored_name)
            except Exception:
                pass
        raise


def _resolve_audiences(read_scope, distribution_scope, read_criteria, distribution_criteria):
    readable = resolve_scope_user_ids(scope=read_scope, criteria=read_criteria, purpose="doc")
    recipients = resolve_scope_user_ids(scope=distribution_scope, criteria=distribution_criteria, purpose="phan_phoi")
    outside = recipients - readable
    if outside:
        raise ValidationError(
            f"Tập người nhận có {len(outside)} tài khoản nằm ngoài phạm vi quyền xem. "
            "Hãy điều chỉnh phạm vi đọc hoặc người nhận."
        )
    return readable, recipients


def preview_recipient_count(cleaned):
    """Dự kiến số người nhận từ lựa chọn hiện tại; chỉ truy vấn, chưa phát hành."""
    payload = _criteria_payload(cleaned)
    criteria = {
        purpose: [TieuChiThongBao(loai_tieu_chi=kind, **{kind: target})
                  for kind, targets in groups.items() for target in targets]
        for purpose, groups in payload.items()
    }
    _, recipients = _resolve_audiences(
        cleaned["che_do_doc"], cleaned["che_do_phan_phoi"], criteria["doc"], criteria["phan_phoi"],
    )
    if not recipients:
        raise ValidationError("Tập người nhận không có tài khoản nhân viên đang hoạt động.")
    return len(recipients)


def _notice_audiences(notice):
    doc_criteria = list(notice.tieu_chi.filter(muc_dich="doc").select_related(
        "phong_ban", "cong_dong", "du_an", "nguoi_dung"
    ))
    distribution_criteria = list(notice.tieu_chi.filter(muc_dich="phan_phoi").select_related(
        "phong_ban", "cong_dong", "du_an", "nguoi_dung"
    ))
    return _resolve_audiences(
        notice.che_do_doc, notice.che_do_phan_phoi, doc_criteria, distribution_criteria,
    )


def _validate_notice_audience(notice, *, require_recipients):
    """Validate B3/B4: recipient audience must be a subset of current readers."""
    _readable, recipients = _notice_audiences(notice)
    if require_recipients and not recipients:
        raise ValidationError("Tập người nhận không có tài khoản nhân viên đang hoạt động.")
    return sorted(recipients)


def _notice_recipients(notice):
    return _validate_notice_audience(notice, require_recipients=True)


def publish_notice(*, notice_id, user, request_key, request=None):
    """Atomically publish config + audience + ACK rows + per-recipient notifications.

    request_key is the form's UUID idempotency key. A retry after a committed publish
    returns the already published notice instead of distributing it a second time.
    """
    if not can_publish_notices(user):
        raise PermissionDenied("Bạn không còn quyền phát hành thông báo.")

    existing = ThongBaoChinhThuc.objects.filter(khoa_yeu_cau_xuat_ban=request_key).select_related("bai_viet").first()
    if existing and existing.trang_thai == "da_cong_bo":
        return existing, False

    try:
        with transaction.atomic():
            notice = ThongBaoChinhThuc.objects.select_for_update().select_related("bai_viet").get(pk=notice_id)
            if notice.trang_thai == "da_cong_bo":
                if notice.khoa_yeu_cau_xuat_ban == request_key:
                    return notice, False
                raise ValidationError("Thông báo đã công bố và không được sửa đè. Hãy tạo thông báo đính chính mới.")
            if not can_manage_draft(user, notice):
                raise PermissionDenied("Bạn không được phát hành bản nháp này.")
            post = BaiViet.objects.select_for_update().get(pk=notice.bai_viet_id)
            if not post.tieu_de.strip():
                raise ValidationError({"tieu_de": "Cần nhập tiêu đề trước khi phát hành."})
            if not post.noi_dung.strip():
                raise ValidationError({"noi_dung": "Cần nhập nội dung trước khi phát hành."})
            recipients = _notice_recipients(notice)
            User = get_user_model()
            locked_users = list(
                User.objects.select_for_update().filter(pk__in=recipients, is_active=True)
            )
            if len(locked_users) != len(recipients):
                raise ValidationError(
                    "Danh sách người nhận đã thay đổi trong lúc phát hành. "
                    "Hãy tải lại bản nháp và kiểm tra phạm vi."
                )
            users = {item.pk: item for item in locked_users}
            now = timezone.now()

            # The following writes are one atomic unit: state, actual recipient set,
            # ACK requirement and recipient notification events.
            NguoiNhanThongBao.objects.filter(thong_bao=notice).delete()
            ThongBaoHeThong.objects.filter(
                bai_viet=post,
                loai_thong_bao="thong_bao_chinh_thuc",
            ).delete()

            notice.nguoi_xuat_ban = user
            notice.ngay_xuat_ban = now
            notice.kiem_tra_luc = now
            notice.khoa_yeu_cau_xuat_ban = request_key
            notice.trang_thai = "da_cong_bo"
            notice.full_clean()
            notice.save(update_fields=[
                "nguoi_xuat_ban", "ngay_xuat_ban", "kiem_tra_luc",
                "khoa_yeu_cau_xuat_ban", "trang_thai", "ngay_cap_nhat",
            ])

            post.trang_thai = "hien"
            post.save(update_fields=["trang_thai", "ngay_cap_nhat"])

            NguoiNhanThongBao.objects.bulk_create([
                NguoiNhanThongBao(
                    thong_bao=notice,
                    nguoi_dung_id=user_id,
                    ngay_phan_phoi=now,
                    bat_buoc_xac_nhan=notice.yeu_cau_xac_nhan,
                    trang_thai_tiep_nhan="chua_xac_nhan",
                    ngay_xac_nhan=None,
                )
                for user_id in recipients
            ])

            event_key = f"official_notice:{notice.pk}:published"
            detail_path = reverse("notifications:detail", args=[notice.pk])
            ThongBaoHeThong.objects.bulk_create([
                ThongBaoHeThong(
                    nguoi_nhan=users[user_id],
                    nguoi_tao_hanh_dong=user,
                    tieu_de=post.tieu_de,
                    noi_dung=(post.noi_dung[:500]),
                    loai_thong_bao="thong_bao_chinh_thuc",
                    khoa_su_kien=event_key,
                    bai_viet=post,
                    duong_dan=detail_path,
                )
                for user_id in recipients if user_id in users
            ])
            _audit(
                user=user,
                notice=notice,
                action="cong_bo_thong_bao_chinh_thuc",
                after={
                    "tieu_de": post.tieu_de,
                    "che_do_doc": notice.che_do_doc,
                    "che_do_phan_phoi": notice.che_do_phan_phoi,
                    "yeu_cau_xac_nhan": notice.yeu_cau_xac_nhan,
                    "so_nguoi_nhan": len(recipients),
                    "khoa_yeu_cau_xuat_ban": str(request_key),
                },
                request=request,
                request_key=request_key,
            )
        return notice, True
    except IntegrityError:
        # If another identical request committed first, return its result.
        existing = ThongBaoChinhThuc.objects.filter(khoa_yeu_cau_xuat_ban=request_key).select_related("bai_viet").first()
        if existing and existing.trang_thai == "da_cong_bo":
            return existing, False
        raise


def cancel_notice_draft(*, notice, user, request=None):
    if not can_manage_draft(user, notice):
        raise PermissionDenied("Bạn không được hủy bản nháp này hoặc bản nháp đã công bố.")
    with transaction.atomic():
        notice = ThongBaoChinhThuc.objects.select_for_update().select_related("bai_viet").get(pk=notice.pk)
        if not can_manage_draft(user, notice):
            raise PermissionDenied("Bạn không còn quyền hủy bản nháp này.")
        if notice.trang_thai != "ban_nhap":
            raise ValidationError("Chỉ bản nháp mới được hủy.")
        post = BaiViet.objects.select_for_update().get(pk=notice.bai_viet_id)
        post.da_xoa_mem = True
        post.ngay_xoa = timezone.now()
        post.nguoi_xoa = user
        post.save(update_fields=["da_xoa_mem", "ngay_xoa", "nguoi_xoa", "ngay_cap_nhat"])
        _audit(user=user, notice=notice, action="huy_ban_nhap_thong_bao_chinh_thuc",
               after={"da_xoa_mem": True}, request=request)


def acknowledge_notice(*, notice_id, user, request=None):
    """Record the recipient's one-way ACK without changing the immutable audience."""
    with transaction.atomic():
        notice = ThongBaoChinhThuc.objects.select_for_update().select_related("bai_viet").get(pk=notice_id)
        if not can_read_notice(user, notice):
            raise PermissionDenied("Bạn không còn quyền đọc thông báo này.")
        if not notice.yeu_cau_xac_nhan:
            raise PermissionDenied("Thông báo này không yêu cầu xác nhận tiếp nhận.")

        recipient = NguoiNhanThongBao.objects.select_for_update().filter(
            thong_bao=notice,
            nguoi_dung=user,
            bat_buoc_xac_nhan=True,
        ).first()
        if recipient is None:
            raise PermissionDenied("Bạn không thuộc tập người nhận cần xác nhận thông báo này.")

        if recipient.trang_thai_tiep_nhan == "da_xac_nhan" and recipient.ngay_xac_nhan:
            return recipient, False

        confirmed_at = timezone.now()
        changed = NguoiNhanThongBao.objects.filter(
            pk=recipient.pk,
            bat_buoc_xac_nhan=True,
            trang_thai_tiep_nhan="chua_xac_nhan",
            ngay_xac_nhan__isnull=True,
        ).update(
            trang_thai_tiep_nhan="da_xac_nhan",
            ngay_xac_nhan=confirmed_at,
        )

        recipient.refresh_from_db()
        if not changed:
            # Idempotent retry/concurrent tab: return the already committed ACK.
            if recipient.trang_thai_tiep_nhan == "da_xac_nhan" and recipient.ngay_xac_nhan:
                return recipient, False
            raise ValidationError("Chưa thể ghi nhận xác nhận. Vui lòng tải lại và thử lại.")

        _audit(
            user=user,
            notice=notice,
            action="xac_nhan_tiep_nhan_thong_bao",
            before={"trang_thai_tiep_nhan": "chua_xac_nhan", "ngay_xac_nhan": None},
            after={
                "trang_thai_tiep_nhan": "da_xac_nhan",
                "ngay_xac_nhan": recipient.ngay_xac_nhan.isoformat(),
            },
            request=request,
        )
        return recipient, True

