"""UC-KNW-05. Nháp và bản công bố có dữ liệu độc lập, ghi cùng nhật ký."""

import copy
import hashlib
import json
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone

from projectp.models import (
    BaiVietTriThuc,
    DinhKem,
    GanChuDePhienBan,
    NguonThamKhao,
    NhatKyNghiepVu,
    PhienBanTriThuc,
)
from projects.permissions import readable_projects
from projects.services_common import attach_files, payload_hash
from communities.views._chung import cong_dong_xem_duoc

SALT = "knowledge.editor.request.v1"
REVISION_SALT = "knowledge.editor.revision.v1"


def can_edit(user, article=None):
    if not user.is_authenticated or not user.is_active:
        return False
    if article is None:
        return user.has_perm("projectp.add_baiviettrithuc")
    if article.da_xoa_mem or article.trang_thai_quan_tri != "hien_thi":
        return False
    return user.has_perm("projectp.change_baiviettrithuc") or (
        article.nguoi_tao_id == user.pk and user.has_perm("projectp.add_baiviettrithuc")
    )


def check_scope(user, version):
    if version.du_an_id and not readable_projects(user).filter(pk=version.du_an_id).exists():
        raise PermissionDenied("Không còn quyền sử dụng phạm vi dự án này.")
    if version.cong_dong_id and not cong_dong_xem_duoc(user).filter(pk=version.cong_dong_id).exists():
        raise PermissionDenied("Không còn quyền sử dụng phạm vi cộng đồng này.")


def revision(article, version):
    data = {
        "article": list(BaiVietTriThuc.objects.filter(pk=article.pk).values()),
        "version": list(PhienBanTriThuc.objects.filter(pk=version.pk).values()),
        "references": list(version.nguon_tham_khao.order_by("pk").values()),
        "topics": list(version.gan_chu_de.order_by("pk").values()),
        "attachments": list(DinhKem.objects.filter(phien_ban_tri_thuc=version).order_by("pk").values()),
    }
    fingerprint = hashlib.sha256(json.dumps(data, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()
    return signing.dumps(
        {"article": article.pk, "version": version.pk, "hash": fingerprint}, salt=REVISION_SALT
    )


def check_revision(article, version, token):
    try:
        expected = signing.loads(token, salt=REVISION_SALT, max_age=8 * 60 * 60)
        current = signing.loads(revision(article, version), salt=REVISION_SALT)
    except signing.BadSignature:
        raise ValidationError("Biểu mẫu đã hết hiệu lực. Tải lại để đối chiếu.")
    if expected != current:
        raise ValidationError(
            "Bài hoặc phiên bản đã thay đổi. Tải lại để đối chiếu, dữ liệu chưa được ghi đè."
        )


def editor_token(user, article_id=None, version_id=None):
    return signing.dumps(
        {"user": user.pk, "article": article_id, "version": version_id, "key": str(uuid.uuid4())}, salt=SALT
    )


def request_key(user, token, article_id, version_id):
    try:
        data = signing.loads(token, salt=SALT, max_age=24 * 60 * 60)
        key = uuid.UUID(data["key"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise ValidationError("Yêu cầu đã hết hiệu lực. Mở lại biểu mẫu.")
    if (data["user"], data["article"], data["version"]) != (user.pk, article_id, version_id):
        raise ValidationError("Yêu cầu không thuộc đúng người dùng hoặc phiên bản.")
    return key


def audit(user, article, version, action, key, fingerprint):
    NhatKyNghiepVu.objects.create(
        nguoi_dung=user,
        hanh_dong=action,
        loai_tai_nguyen="BAI_VIET_TRI_THUC",
        ma_tai_nguyen=str(article.pk),
        ma_yeu_cau=key,
        du_lieu_sau={
            "version_id": version.pk,
            "so_phien_ban": version.so_phien_ban,
            "request_hash": fingerprint,
        },
    )


def check_references(user, version):
    from social.permissions import accessible_posts

    references = version.nguon_tham_khao.select_related("bai_viet_nguon", "tep_nguon")
    if not references.exists():
        raise ValidationError("Cần nguồn tham khảo hợp lệ.")
    for reference in references:
        reference.full_clean()
        if reference.bai_viet_nguon_id:
            post = reference.bai_viet_nguon
            if post.du_an_id or post.che_do_xu_ly:
                raise ValidationError("Kinh nghiệm dự án cần chuẩn hóa qua UC-KNW-04.")
            if not accessible_posts(user).filter(pk=post.pk).exists():
                raise PermissionDenied("Nguồn tham khảo không còn quyền đọc.")
            if post.cong_dong_id and post.cong_dong.pham_vi_truy_cap == "thanh_vien":
                if version.pham_vi_chia_se != "cong_dong" or version.cong_dong_id != post.cong_dong_id:
                    raise ValidationError("Phạm vi bài viết rộng hơn phạm vi nguồn cộng đồng.")
        if reference.tep_nguon_id:
            file = reference.tep_nguon
            if file.da_xoa_mem or file.trang_thai != "san_sang":
                raise ValidationError("Tệp tham khảo không còn khả dụng.")
            from .files import can_read_reference_file
            if not can_read_reference_file(user, reference):
                raise PermissionDenied("Không còn quyền đọc nguồn của tệp tham khảo.")
            links = DinhKem.objects.filter(tep_tin=file)
            if links.filter(Q(ket_qua_thu__isnull=False) | Q(phuong_an__isnull=False)
                    | Q(bai_viet__che_do_xu_ly=True)).exists():
                raise ValidationError("Tệp chứng cứ xử lý dự án cần đi qua quy trình chuẩn hóa KNW-04.")
            for link in links.filter(bai_viet__isnull=False).select_related("bai_viet__cong_dong"):
                post = link.bai_viet
                if post.du_an_id and (version.pham_vi_chia_se != "du_an" or version.du_an_id != post.du_an_id):
                    raise ValidationError("Phạm vi bài viết rộng hơn nguồn tệp dự án.")
                if not post.du_an_id and post.cong_dong_id and post.cong_dong.pham_vi_truy_cap == "thanh_vien":
                    if version.pham_vi_chia_se != "cong_dong" or version.cong_dong_id != post.cong_dong_id:
                        raise ValidationError("Phạm vi bài viết rộng hơn nguồn tệp cộng đồng.")
            # Tệp mới do người biên tập cung cấp hoặc tệp đã thuộc chính phiên bản.
            if (
                file.nguoi_tai_len_id != user.pk
                and not DinhKem.objects.filter(tep_tin=file, phien_ban_tri_thuc=version).exists()
            ):
                raise PermissionDenied("Chưa có quyền sử dụng tệp tham khảo này.")


def save_draft(user, data, article_id=None, version_id=None):
    key = request_key(user, data["request_token"], article_id, version_id)
    payload = {k: v for k, v in data.items() if k not in {"revision_token", "action"}}
    payload["chu_de"] = list(data["chu_de"])
    fingerprint = payload_hash(payload)
    files = []
    try:
        with transaction.atomic():
            get_user_model().objects.filter(pk=user.pk).update(is_active=F("is_active"))
            if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists():
                raise PermissionDenied("Tài khoản không còn hoạt động.")
            user = get_user_model().objects.get(pk=user.pk)
            previous = NhatKyNghiepVu.objects.filter(
                nguoi_dung=user, ma_yeu_cau=key, hanh_dong="UC-KNW-05:save"
            ).first()
            if previous:
                if previous.du_lieu_sau.get("request_hash") != fingerprint:
                    raise ValidationError("Yêu cầu đã được lưu với nội dung khác. Mở lại biểu mẫu.")
                version = PhienBanTriThuc.objects.select_related("bai_viet_tri_thuc").get(
                    pk=previous.du_lieu_sau["version_id"]
                )
                if not can_edit(user, version.bai_viet_tri_thuc):
                    raise PermissionDenied("Quyền biên tập đã thay đổi.")
                check_scope(user, version)
                return version
            if article_id is None:
                if not can_edit(user):
                    raise PermissionDenied("Chưa có quyền tạo bài viết tri thức.")
                article = BaiVietTriThuc.objects.create(nguoi_tao=user, khoa_khoi_tao=key)
                version = PhienBanTriThuc(bai_viet_tri_thuc=article, so_phien_ban=1, nguoi_bien_tap=user)
            else:
                BaiVietTriThuc.objects.filter(pk=article_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
                article = BaiVietTriThuc.objects.get(pk=article_id)
                version = PhienBanTriThuc.objects.get(pk=version_id, bai_viet_tri_thuc=article)
                if not can_edit(user, article):
                    raise PermissionDenied("Quyền biên tập đã thay đổi.")
                if version.trang_thai != "ban_nhap":
                    raise ValidationError("Chỉ chỉnh sửa bản nháp. Bản công bố được giữ trong lịch sử.")
                check_scope(user, version)
                check_revision(article, version, data["revision_token"])
            for field in (
                "tieu_de",
                "tom_tat",
                "noi_dung",
                "loai_nguon",
                "pham_vi_ap_dung",
                "pham_vi_chia_se",
                "du_an",
                "cong_dong",
            ):
                setattr(version, field, data.get(field))
            check_scope(user, version)
            version.nguoi_bien_tap = user
            version.full_clean()
            version.save()
            for name in ("remove_reference_ids", "remove_attachment_ids"):
                values = data.get(name, [])
                queryset = (
                    version.nguon_tham_khao.all()
                    if name == "remove_reference_ids"
                    else DinhKem.objects.filter(phien_ban_tri_thuc=version)
                )
                if queryset.filter(pk__in=values).count() != len(set(values)):
                    raise ValidationError("Chỉ gỡ dữ liệu thuộc đúng bản nháp này.")
                queryset.filter(pk__in=values).delete()
            # Trường tham khảo chính của form chỉ cập nhật nguồn đang được chọn.
            reference_id = data.get("reference_id")
            primary_removed = reference_id in data.get("remove_reference_ids", [])
            reference = (
                version.nguon_tham_khao.filter(pk=reference_id).first()
                if reference_id
                else version.nguon_tham_khao.order_by("thu_tu", "pk").first()
            )
            if reference_id and reference is None and not primary_removed:
                raise ValidationError("Nguồn tham khảo không thuộc bản nháp.")
            if data.get("loai_tham_chieu") and not primary_removed:
                if reference is None:
                    reference = NguonThamKhao(phien_ban=version, thu_tu=1)
                reference.loai_tham_chieu = data["loai_tham_chieu"]
                reference.tieu_de_nguon = data.get("tieu_de_nguon", "")
                reference.tac_gia = data.get("tac_gia", "")
                reference.url = data.get("url_nguon", "") if reference.loai_tham_chieu == "url" else ""
                reference.trich_dan = data.get("trich_dan", "")
                reference.bai_viet_nguon = (
                    data.get("bai_viet_nguon") if reference.loai_tham_chieu == "bai_viet" else None
                )
                reference.tep_nguon = data.get("tep_nguon") if reference.loai_tham_chieu == "tep" else None
                reference.full_clean()
                reference.save()
            selected = {topic.pk for topic in data["chu_de"]}
            version.gan_chu_de.exclude(chu_de_id__in=selected).delete()
            for pk in selected:
                GanChuDePhienBan.objects.get_or_create(phien_ban=version, chu_de_id=pk)
            attach_files(user, data.get("minh_chung", []), {"phien_ban_tri_thuc": version}, files)
            check_references(user, version)
            audit(user, article, version, "UC-KNW-05:save", key, fingerprint)
            return version
    except Exception:
        for storage, name in files:
            try:
                storage.delete(name)
            except OSError:
                import logging

                logging.getLogger(__name__).exception("Chưa dọn được tệp sau khi hoàn tác nháp")
        raise


@transaction.atomic
def clone_draft(user, article_id, token, revision_token):
    key = request_key(user, token, article_id, None)
    BaiVietTriThuc.objects.filter(pk=article_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    user = get_user_model().objects.get(pk=user.pk)
    article = BaiVietTriThuc.objects.select_related("phien_ban_dang_cong_bo").get(pk=article_id)
    if not can_edit(user, article) or article.phien_ban_dang_cong_bo is None:
        raise PermissionDenied("Không còn quyền tạo nháp của bài viết này.")
    current = article.phien_ban_dang_cong_bo
    check_scope(user, current)
    draft = article.phien_ban.filter(trang_thai="ban_nhap").order_by("-so_phien_ban").first()
    if draft:
        return draft
    check_revision(article, current, revision_token)
    draft = copy.copy(current)
    draft.pk = None
    draft._state.adding = True
    draft.so_phien_ban = (article.phien_ban.aggregate(value=Max("so_phien_ban"))["value"] or 0) + 1
    draft.trang_thai = "ban_nhap"
    draft.nguoi_bien_tap = user
    draft.nguoi_xuat_ban = None
    draft.xuat_ban_luc = None
    draft.kiem_tra_cong_bo_luc = None
    draft.full_clean()
    draft.save(force_insert=True)
    for reference in current.nguon_tham_khao.all():
        reference.pk = None
        reference.phien_ban = draft
        reference.du_lieu_bien_tap = copy.deepcopy(reference.du_lieu_bien_tap)
        reference.full_clean()
        reference.save(force_insert=True)
    for topic in current.gan_chu_de.all():
        GanChuDePhienBan.objects.create(phien_ban=draft, chu_de=topic.chu_de)
    for attachment in DinhKem.objects.filter(phien_ban_tri_thuc=current):
        attachment.pk = None
        attachment.phien_ban_tri_thuc = draft
        attachment.nguoi_dinh_kem = user
        attachment.full_clean()
        attachment.save(force_insert=True)
    audit(user, article, draft, "UC-KNW-05:clone", key, "")
    return draft


@transaction.atomic
def publish_version(
    user, version, token, article_id, original_version_id, expected_current_id, revision_token
):
    key = request_key(user, token, article_id, original_version_id)
    BaiVietTriThuc.objects.filter(pk=version.bai_viet_tri_thuc_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    user = get_user_model().objects.get(pk=user.pk)
    article = BaiVietTriThuc.objects.get(pk=version.bai_viet_tri_thuc_id)
    version = PhienBanTriThuc.objects.get(pk=version.pk, bai_viet_tri_thuc=article)
    if not can_edit(user, article) or not user.has_perm("projectp.cong_bo_tri_thuc"):
        raise PermissionDenied("Bạn chưa có quyền công bố bài viết tri thức.")
    check_scope(user, version)
    previous = NhatKyNghiepVu.objects.filter(
        nguoi_dung=user, ma_yeu_cau=key, hanh_dong="UC-KNW-05:publish"
    ).first()
    if previous and previous.du_lieu_sau.get("version_id") == version.pk:
        return version
    check_revision(article, version, revision_token)
    if article.phien_ban_dang_cong_bo_id != expected_current_id or version.trang_thai != "ban_nhap":
        raise ValidationError("Bản hiện hành đã thay đổi. Tải lại để đối chiếu trước khi công bố.")
    check_references(user, version)
    if not version.gan_chu_de.exists():
        raise ValidationError("Chọn ít nhất một chủ đề trước khi công bố.")
    duplicate = (
        PhienBanTriThuc.objects.filter(
            trang_thai="da_cong_bo", tieu_de__iexact=version.tieu_de.strip(), noi_dung=version.noi_dung
        )
        .exclude(bai_viet_tri_thuc=article)
        .exists()
    )
    if duplicate:
        raise ValidationError("Nội dung trùng với bài viết đã công bố.")
    old = article.phien_ban_dang_cong_bo
    if old:
        old.trang_thai = "lich_su"
        old.save(update_fields=["trang_thai", "ngay_cap_nhat"])
    version.trang_thai = "da_cong_bo"
    version.nguoi_xuat_ban = user
    version.xuat_ban_luc = version.kiem_tra_cong_bo_luc = timezone.now()
    version.full_clean()
    version.save()
    article.phien_ban_dang_cong_bo = version
    article.full_clean()
    article.save()
    audit(user, article, version, "UC-KNW-05:publish", key, "")
    return version
