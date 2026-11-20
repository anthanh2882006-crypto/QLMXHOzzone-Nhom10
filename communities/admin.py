"""UC-COM-08: cộng đồng + OWNER + nhật ký cùng giao dịch; giữ vòng đời dự án."""

import hashlib
import json
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, transaction
from django.shortcuts import redirect
from django.utils import timezone
from projectp.models import CongDong, CommunityRole, DuAn, NhatKyNghiepVu, ThanhVienCongDong, YeuCauThamGia
from projectp.admin import WorkflowReadOnlyAdmin
from projects.permissions import administrable_projects, readable_projects
from projectp.admin_scopes import COMMUNITY_ADMIN_PREFIX, assigned_scopes, scope_ids
from .services import handover_roles, lock_community


def community_state(community):
    return {
        "community": list(CongDong.objects.filter(pk=community.pk).values()),
        "members": list(community.thanh_vien.order_by("pk").values()),
        "project": list(DuAn.objects.filter(cong_dong=community).values()),
    }


def community_digest(community):
    return hashlib.sha256(
        json.dumps(community_state(community), cls=DjangoJSONEncoder, sort_keys=True).encode()
    ).hexdigest()


def community_revision(community):
    return signing.dumps(
        {"pk": community.pk, "hash": community_digest(community)}, salt="communities.admin.v1"
    )


class CommunityAdminForm(forms.ModelForm):
    revision_token = forms.CharField(widget=forms.HiddenInput, required=False)
    owner_ban_dau = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(), required=False, label="OWNER ban đầu"
    )
    ban_giao_tu = forms.ModelChoiceField(
        queryset=ThanhVienCongDong.objects.none(), required=False, label="OWNER bàn giao"
    )
    ban_giao_cho = forms.ModelChoiceField(
        queryset=ThanhVienCongDong.objects.none(), required=False, label="Thành viên nhận OWNER"
    )

    class Meta:
        model = CongDong
        fields = ("ten_cong_dong", "chu_de", "mo_ta", "quy_tac_tham_gia", "pham_vi_truy_cap", "da_xoa_mem")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "owner_ban_dau" in self.fields:
            self.fields["owner_ban_dau"].queryset = get_user_model().objects.filter(is_active=True)
            self.fields["owner_ban_dau"].required = not self.instance.pk
        if self.instance.pk:
            if "revision_token" in self.fields:
                self.fields["revision_token"].initial = community_revision(self.instance)
            members = self.instance.thanh_vien.filter(trang_thai="hoat_dong", ket_thuc_luc__isnull=True)
            if "ban_giao_tu" in self.fields:
                self.fields["ban_giao_tu"].queryset = members.filter(vai_tro=CommunityRole.OWNER)
            recipients = members.filter(nguoi_dung__is_active=True).exclude(vai_tro=CommunityRole.OWNER)
            project = DuAn.objects.filter(cong_dong=self.instance).first()
            if project:
                recipients = recipients.filter(
                    nguoi_dung_id__in=project.thanh_vien.filter(
                        trang_thai="hoat_dong", ket_thuc_luc__isnull=True, nguoi_dung__is_active=True
                    ).values("nguoi_dung_id")
                )
            if "ban_giao_cho" in self.fields:
                self.fields["ban_giao_cho"].queryset = recipients
            if not self.actor.has_perm("projectp.change_thanhviencongdong"):
                for name in ("ban_giao_tu", "ban_giao_cho"):
                    if name in self.fields:
                        self.fields[name].disabled = True

    def clean(self):
        data = super().clean()
        if not self.instance.pk:
            if self.data.get("loai_cong_dong", CongDong.Type.GENERAL) != CongDong.Type.GENERAL:
                raise ValidationError("Cộng đồng dự án được tạo qua UC-PRJ-01.")
            self.instance.loai_cong_dong = CongDong.Type.GENERAL
            self.instance.nguoi_tao = self.actor
        else:
            with transaction.atomic():
                current = lock_community(self.instance.pk)
                try:
                    version = signing.loads(
                        data.get("revision_token", ""), salt="communities.admin.v1", max_age=8 * 60 * 60
                    )
                except signing.BadSignature:
                    raise ValidationError("Biểu mẫu hết hiệu lực; tải lại để đối chiếu.")
                if version.get("pk") != current.pk or version.get("hash") != community_digest(current):
                    raise ValidationError("Cộng đồng/thành viên đã thay đổi; tải lại trước khi lưu.")
                project = DuAn.objects.filter(cong_dong=current).first()
                if project and project.da_luu_tru:
                    raise ValidationError("Dự án đã lưu trữ; chỉ được xem.")
                self.current = current
        old, new = data.get("ban_giao_tu"), data.get("ban_giao_cho")
        if bool(old) != bool(new):
            raise ValidationError("Bàn giao cần chọn cả OWNER cũ và người nhận.")
        if old and not self.actor.has_perm("projectp.change_thanhviencongdong"):
            raise ValidationError("Chưa được cấp quyền bàn giao OWNER trong Admin.")
        deleted = data.get("da_xoa_mem", self.instance.da_xoa_mem)
        self.instance.ngay_xoa = (self.instance.ngay_xoa or timezone.now()) if deleted else None
        self.instance.nguoi_xoa = self.actor if deleted else None
        return data


@admin.register(CongDong)
class CongDongAdmin(admin.ModelAdmin):
    form = CommunityAdminForm
    list_display = (
        "ten_cong_dong",
        "loai_cong_dong",
        "quy_tac_tham_gia",
        "pham_vi_truy_cap",
        "da_xoa_mem",
        "ngay_tao",
    )
    list_filter = ("loai_cong_dong", "quy_tac_tham_gia", "pham_vi_truy_cap", "da_xoa_mem")
    search_fields = ("ten_cong_dong", "chu_de", "mo_ta")
    date_hierarchy = "ngay_tao"

    def get_form(self, request, obj=None, **kwargs):
        base = super().get_form(request, obj, **kwargs)

        class BoundForm(base):
            actor = request.user

        return BoundForm

    def get_queryset(self, request):
        from django.db.models import Q

        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        scopes = assigned_scopes(request.user, COMMUNITY_ADMIN_PREFIX)
        general = Q(loai_cong_dong=CongDong.Type.GENERAL)
        if "toan_cong_ty" not in scopes:
            general &= Q(pk__in=scope_ids(scopes, "cong_dong"))
        project_access = readable_projects(request.user) | administrable_projects(request.user)
        return queryset.filter(
            general | Q(
                loai_cong_dong=CongDong.Type.PROJECT,
                pk__in=scope_ids(scopes, "cong_dong"),
                du_an_lien_ket__in=project_access,
            )
        )

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def get_fields(self, request, obj=None):
        fields = ["ten_cong_dong", "chu_de", "mo_ta", "quy_tac_tham_gia", "pham_vi_truy_cap"]
        if obj is None:
            return fields + ["owner_ban_dau"]
        fields += ["loai_cong_dong", "nguoi_tao", "da_xoa_mem", "ngay_xoa", "nguoi_xoa"]
        if self.has_change_permission(request, obj):
            fields += ["revision_token", "ban_giao_tu", "ban_giao_cho"]
        return fields

    def get_readonly_fields(self, request, obj=None):
        fields = ["loai_cong_dong", "nguoi_tao", "ngay_xoa", "nguoi_xoa"]
        if obj and obj.loai_cong_dong == CongDong.Type.PROJECT:
            fields += ["quy_tac_tham_gia", "pham_vi_truy_cap", "da_xoa_mem"]
        return fields

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj) or not self.has_view_permission(request, obj):
            return False
        project = DuAn.objects.filter(cong_dong=obj).first() if obj else None
        return not project or (
            not project.da_luu_tru
            and (request.user.is_superuser or (readable_projects(request.user) | administrable_projects(request.user)).filter(pk=project.pk).exists())
        )

    def save_model(self, request, obj, form, change):
        from projectp.admin_permissions import current_admin
        request.user = current_admin(request, "projectp.change_congdong" if change else "projectp.add_congdong")
        if change and not self.has_change_permission(request, form.current):
            raise PermissionDenied("Không có quyền cập nhật cộng đồng này.")
        if not change:
            owner = (
                get_user_model()
                .objects.filter(pk=form.cleaned_data["owner_ban_dau"].pk, is_active=True)
                .first()
            )
            if owner is None:
                raise ValidationError("OWNER ban đầu không còn hoạt động.")
            obj.loai_cong_dong, obj.nguoi_tao = CongDong.Type.GENERAL, request.user
            obj.da_xoa_mem, obj.ngay_xoa, obj.nguoi_xoa = False, None, None
            obj.full_clean()
            obj.save()
            ThanhVienCongDong.objects.create(cong_dong=obj, nguoi_dung=owner, vai_tro=CommunityRole.OWNER)
            before = None
        else:
            current = form.current
            before = community_state(current)
            current.ten_cong_dong, current.mo_ta = (
                form.cleaned_data["ten_cong_dong"],
                form.cleaned_data["mo_ta"],
            )
            if current.loai_cong_dong == CongDong.Type.GENERAL:
                current.quy_tac_tham_gia = form.cleaned_data["quy_tac_tham_gia"]
                current.pham_vi_truy_cap = form.cleaned_data["pham_vi_truy_cap"]
                current.da_xoa_mem = form.cleaned_data.get("da_xoa_mem", current.da_xoa_mem)
                current.ngay_xoa = (current.ngay_xoa or timezone.now()) if current.da_xoa_mem else None
                current.nguoi_xoa = request.user if current.da_xoa_mem else None
            current.chu_de = form.cleaned_data["chu_de"]
            current.full_clean()
            current.save()
            old, new = form.cleaned_data.get("ban_giao_tu"), form.cleaned_data.get("ban_giao_cho")
            if old and new:
                if not request.user.has_perm("projectp.change_thanhviencongdong"):
                    raise PermissionDenied("Chưa có quyền bàn giao OWNER trong Admin.")
                handover_roles(current, old.pk, new.pk)
            obj = current
        if (
            not obj.da_xoa_mem
            and not obj.thanh_vien.filter(
                vai_tro=CommunityRole.OWNER,
                trang_thai="hoat_dong",
                ket_thuc_luc__isnull=True,
                nguoi_dung__is_active=True,
            ).exists()
        ):
            raise ValidationError("Cộng đồng hoạt động cần ít nhất một OWNER đang hoạt động.")
        # JSONField cần dữ liệu JSON thuần; không lưu datetime thô.
        after = community_state(obj)
        clean = lambda value: json.loads(json.dumps(value, cls=DjangoJSONEncoder))
        NhatKyNghiepVu.objects.create(
            nguoi_dung=request.user,
            hanh_dong="UC-COM-08:create" if not change else "UC-COM-08:update",
            loai_tai_nguyen="CONG_DONG",
            ma_tai_nguyen=str(obj.pk),
            du_lieu_truoc=clean(before),
            du_lieu_sau=clean(after),
        )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except (DatabaseError, ValidationError):
            messages.error(
                request, "Chưa lưu được cộng đồng. Dữ liệu và OWNER cũ được giữ; tải lại để đối chiếu."
            )
            return redirect(request.path)


@admin.register(ThanhVienCongDong)
class ThanhVienCongDongAdmin(WorkflowReadOnlyAdmin):
    list_display = ("nguoi_dung", "cong_dong", "vai_tro", "trang_thai", "ngay_tham_gia", "ket_thuc_luc")
    list_filter = ("vai_tro", "trang_thai", "cong_dong")
    search_fields = ("nguoi_dung__username", "cong_dong__ten_cong_dong")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.filter(
            cong_dong_id__in=admin.site._registry[CongDong].get_queryset(request).values("pk")
        )


@admin.register(YeuCauThamGia)
class YeuCauThamGiaAdmin(WorkflowReadOnlyAdmin):
    list_display = ("nguoi_dung", "cong_dong", "trang_thai", "ngay_tao", "nguoi_xu_ly", "ngay_xu_ly")
    list_filter = ("trang_thai", "cong_dong")
    search_fields = ("nguoi_dung__username", "cong_dong__ten_cong_dong", "loi_nhan")
    date_hierarchy = "ngay_tao"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.filter(
            cong_dong_id__in=admin.site._registry[CongDong].get_queryset(request).values("pk")
        )
