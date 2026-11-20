"""UC-KNW-06 qua Django Admin. Chỉ đổi trạng thái, bảo toàn nội dung/phiên bản."""

import hashlib
import json
from django import forms
from django.contrib import admin, messages
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.shortcuts import redirect
from knowledge.services import article_communities
from projects.permissions import readable_projects
from projectp.models import (
    BaiHocKinhNghiem,
    BaiVietTriThuc,
    ChuDeTriThuc,
    GanChuDePhienBan,
    NguonThamKhao,
    NhatKyNghiepVu,
    PhienBanTriThuc,
)
from projectp.admin import WorkflowReadOnlyAdmin
from .admin_scopes import KNOWLEDGE_ADMIN_PREFIX, assigned_scopes, scope_ids


def readable_admin_versions(user, visible_articles):
    versions = PhienBanTriThuc.objects.all()
    if user.is_superuser:
        return versions

    allowed = Q(pk__in=visible_articles.values("phien_ban_dang_cong_bo_id"))
    scopes = assigned_scopes(user, KNOWLEDGE_ADMIN_PREFIX)
    allowed |= Q(du_an_id__in=scope_ids(scopes, "du_an"))
    allowed |= Q(cong_dong_id__in=scope_ids(scopes, "cong_dong"))
    if "toan_cong_ty" in scopes:
        allowed |= Q(pham_vi_chia_se="noi_bo")

    editor_articles = BaiVietTriThuc.objects.filter(da_xoa_mem=False, trang_thai_quan_tri="hien_thi")
    if not user.has_perm("projectp.change_baiviettrithuc"):
        if user.has_perm("projectp.add_baiviettrithuc"):
            editor_articles = editor_articles.filter(nguoi_tao=user)
        else:
            editor_articles = editor_articles.none()
    allowed |= (
        Q(trang_thai="ban_nhap", bai_viet_tri_thuc_id__in=editor_articles.values("pk"))
        & (Q(du_an__isnull=True) | Q(du_an__in=readable_projects(user).values("pk")))
        & (Q(cong_dong__isnull=True) | Q(cong_dong__in=article_communities(user).values("pk")))
    )
    return versions.filter(allowed)


def status_revision(instance):
    data = instance.__class__.objects.filter(pk=instance.pk).values().get()
    fingerprint = hashlib.sha256(json.dumps(data, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()
    return signing.dumps(
        {"pk": instance.pk, "model": instance._meta.label_lower, "hash": fingerprint},
        salt="knowledge.admin.status",
    )


class KnowledgeStatusForm(forms.ModelForm):
    revision_token = forms.CharField(widget=forms.HiddenInput)
    ly_do = forms.CharField(required=False, label="Lý do", widget=forms.Textarea(attrs={"rows": 2}))
    xac_nhan = forms.BooleanField(label="Xác nhận chuyển trạng thái tri thức")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["revision_token"].initial = status_revision(self.instance)

    def clean(self):
        data = super().clean()
        if not self.instance.pk:
            raise ValidationError("Tạo nội dung qua quy trình chuẩn hóa/biên tập.")
        with transaction.atomic():
            model = type(self.instance)
            model.objects.filter(pk=self.instance.pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))
            self.current = model.objects.get(pk=self.instance.pk)
            try:
                expected = signing.loads(
                    data.get("revision_token", ""), salt="knowledge.admin.status", max_age=8 * 60 * 60
                )
            except signing.BadSignature:
                raise ValidationError("Biểu mẫu hết hiệu lực; tải lại để đối chiếu.")
            if expected != signing.loads(status_revision(self.current), salt="knowledge.admin.status"):
                raise ValidationError("Nội dung vừa thay đổi; tải lại trước khi chuyển trạng thái.")
            target = data.get("trang_thai_quan_tri")
            if target and (target != self.current.trang_thai_quan_tri or self.current.da_xoa_mem):
                if not data.get("ly_do"):
                    self.add_error("ly_do", "Nhập lý do trước khi chuyển trạng thái.")
            if target == "hien_thi":
                if isinstance(self.current, BaiHocKinhNghiem):
                    source = self.current.bai_viet_nguon
                    if (
                        source.da_xoa_mem
                        or source.trang_thai != "hien"
                        or not self.current.ket_luan.ket_qua.thanh_cong
                    ):
                        raise ValidationError("Nguồn/kết quả không còn hợp lệ để khôi phục.")
                    self.current.full_clean()
                else:
                    version = self.current.phien_ban_dang_cong_bo
                    if version is None:
                        raise ValidationError("Chưa có phiên bản công bố hợp lệ để khôi phục.")
                    if version.bai_viet_tri_thuc_id != self.current.pk or version.trang_thai != "da_cong_bo":
                        raise ValidationError("Phiên bản công bố hiện hành không hợp lệ.")
                    version.full_clean()
        return data


class KnowledgeStatusAdmin(admin.ModelAdmin):
    form = KnowledgeStatusForm
    list_display = ("__str__", "trang_thai_quan_tri", "da_xoa_mem", "ngay_cap_nhat")
    list_filter = ("trang_thai_quan_tri", "da_xoa_mem")

    def get_search_fields(self, request):
        if self.model is BaiHocKinhNghiem:
            return ("=ma_bai_hoc", "tieu_de")
        return ("=ma_bai_viet_tri_thuc", "phien_ban_dang_cong_bo__tieu_de")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_fields(self, request, obj=None):
        fields = [f.name for f in self.model._meta.fields]
        if self.has_change_permission(request, obj):
            fields += ["revision_token", "ly_do", "xac_nhan"]
        return fields

    def get_readonly_fields(self, request, obj=None):
        return tuple(f.name for f in self.model._meta.fields if f.name != "trang_thai_quan_tri")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        scopes = assigned_scopes(request.user, KNOWLEDGE_ADMIN_PREFIX)
        projects = scope_ids(scopes, "du_an")
        if self.model is BaiHocKinhNghiem:
            scope = Q(pk__in=scope_ids(scopes, "bai_hoc")) | Q(bai_viet_nguon__du_an_id__in=projects)
            if "toan_cong_ty" in scopes:
                scope |= Q(pham_vi_chia_se="noi_bo")
        else:
            scope = (
                Q(pk__in=scope_ids(scopes, "bai_viet"))
                | Q(phien_ban_dang_cong_bo__du_an_id__in=projects)
                | Q(phien_ban_dang_cong_bo__cong_dong_id__in=scope_ids(scopes, "cong_dong"))
            )
            if "toan_cong_ty" in scopes:
                scope |= Q(phien_ban_dang_cong_bo__pham_vi_chia_se="noi_bo")
        return queryset.filter(scope)

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def save_model(self, request, obj, form, change):
        from projectp.admin_permissions import current_admin
        request.user = current_admin(request, f"{self.model._meta.app_label}.change_{self.model._meta.model_name}")
        if (not change or not self.has_change_permission(request, form.current)
                or not self.get_queryset(request).filter(pk=form.current.pk).exists()):
            raise PermissionDenied("Không có quyền chuyển trạng thái tri thức.")
        current = form.current
        before = {"trang_thai_quan_tri": current.trang_thai_quan_tri, "da_xoa_mem": current.da_xoa_mem}
        current.trang_thai_quan_tri = form.cleaned_data["trang_thai_quan_tri"]
        if current.trang_thai_quan_tri == "hien_thi":
            current.da_xoa_mem, current.ngay_xoa, current.nguoi_xoa = False, None, None
        current.full_clean()
        current.save()
        NhatKyNghiepVu.objects.create(
            nguoi_dung=request.user,
            hanh_dong="UC-KNW-06:status",
            loai_tai_nguyen=current._meta.db_table,
            ma_tai_nguyen=str(current.pk),
            du_lieu_truoc=before,
            du_lieu_sau={
                "trang_thai_quan_tri": current.trang_thai_quan_tri,
                "da_xoa_mem": current.da_xoa_mem,
            },
            ly_do=form.cleaned_data.get("ly_do", ""),
        )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except (DatabaseError, ValidationError):
            messages.error(request, "Chưa đổi được trạng thái. Dữ liệu cũ được giữ; tải lại để thử lại.")
            return redirect(request.path)


admin.site.register(BaiHocKinhNghiem, KnowledgeStatusAdmin)
admin.site.register(BaiVietTriThuc, KnowledgeStatusAdmin)
admin.site.register([PhienBanTriThuc, NguonThamKhao, GanChuDePhienBan], WorkflowReadOnlyAdmin)
admin.site.register(ChuDeTriThuc)
