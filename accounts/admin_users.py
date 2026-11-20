"""UC-ACC-05: thông tin tài khoản khác quyền cấp đặc quyền và mật khẩu tạm."""

from copy import deepcopy
import hashlib
import json
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group
from django.contrib.auth.forms import AdminPasswordChangeForm, UserChangeForm
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import F
from django.shortcuts import redirect
from projectp.models import HoSoNhanVien, NhatKyNghiepVu
from notifications.permissions import TRACK_GROUP_PREFIX


def account_snapshot(user):
    current = get_user_model().objects.get(pk=user.pk)
    return {
        "username": current.username,
        "first_name": current.first_name,
        "last_name": current.last_name,
        "email": current.email,
        "is_active": current.is_active,
        "is_staff": current.is_staff,
        "is_superuser": current.is_superuser,
        "groups": list(current.groups.order_by("pk").values_list("pk", flat=True)),
        "permissions": list(current.user_permissions.order_by("pk").values_list("pk", flat=True)),
    }


def account_revision(user):
    fingerprint = hashlib.sha256(json.dumps(account_snapshot(user), sort_keys=True).encode()).hexdigest()
    return signing.dumps({"pk": user.pk, "hash": fingerprint}, salt="accounts.admin.revision")


class AccountChangeForm(UserChangeForm):
    revision_token = forms.CharField(widget=forms.HiddenInput)
    ly_do_quyen = forms.CharField(
        required=False, label="Lý do thay đổi nhóm/quyền", widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "revision_token" in self.fields:
            self.fields["revision_token"].initial = account_revision(self.instance)

    def clean(self):
        data = super().clean()
        if not self.instance.pk:
            return data
        with transaction.atomic():
            get_user_model().objects.filter(pk=self.instance.pk).update(is_active=F("is_active"))
            try:
                expected = signing.loads(
                    data.get("revision_token", ""), salt="accounts.admin.revision", max_age=8 * 60 * 60
                )
            except signing.BadSignature:
                raise ValidationError("Biểu mẫu hết hiệu lực. Tải lại để đối chiếu.")
            if expected != signing.loads(account_revision(self.instance), salt="accounts.admin.revision"):
                raise ValidationError("Tài khoản hoặc quyền vừa thay đổi. Tải lại trước khi lưu.")
            self.before = account_snapshot(self.instance)
        if {"is_staff", "is_superuser", "groups", "user_permissions"}.intersection(
            self.changed_data
        ) and not data.get("ly_do_quyen"):
            self.add_error("ly_do_quyen", "Nhập lý do thay đổi quyền.")
        return data


class TemporaryPasswordForm(AdminPasswordChangeForm):
    def save(self, commit=True):
        if not commit:
            return super().save(commit=False)
        with transaction.atomic():
            user = super().save(commit=True)
            if user.has_usable_password():
                HoSoNhanVien.objects.filter(nguoi_dung=user).update(bat_buoc_doi_mat_khau=True)
            return user


class OzzoneUserAdmin(UserAdmin):
    """change_user chỉ sửa tài khoản thường; đặc quyền do superuser quản lý."""

    change_password_form = TemporaryPasswordForm
    form = AccountChangeForm
    privilege_fields = {"is_staff", "is_superuser", "groups", "user_permissions"}

    def can_manage_grants(self, user):
        return user.is_superuser or user.has_perm("auth.change_permission")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(is_superuser=False, is_staff=False)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            request.user.is_superuser or obj is None or not (obj.is_staff or obj.is_superuser)
        )

    def has_delete_permission(self, request, obj=None):
        # Vô hiệu hóa giữ liên kết và lịch sử; không xóa tài khoản vật lý tại đây.
        return False

    def get_fieldsets(self, request, obj=None):
        fieldsets = deepcopy(super().get_fieldsets(request, obj))
        if request.user.is_superuser:
            return list(fieldsets) + (
                [("Đối chiếu thay đổi", {"fields": ("revision_token", "ly_do_quyen")})] if obj else []
            )
        result = []
        restricted = (
            {"is_staff", "is_superuser"} if self.can_manage_grants(request.user) else self.privilege_fields
        )
        for title, options in fieldsets:
            fields = tuple(name for name in options["fields"] if name not in restricted)
            if fields:
                result.append((title, {**options, "fields": fields}))
        if obj:
            result.append(("Đối chiếu thay đổi", {"fields": ("revision_token", "ly_do_quyen")}))
        return result

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        NhatKyNghiepVu.objects.create(
            nguoi_dung=request.user,
            hanh_dong="UC-ACC-05:update" if change else "UC-ACC-05:create",
            loai_tai_nguyen="NGUOI_DUNG",
            ma_tai_nguyen=str(form.instance.pk),
            du_lieu_truoc=getattr(form, "before", None),
            du_lieu_sau=account_snapshot(form.instance),
            ly_do=form.cleaned_data.get("ly_do_quyen", ""),
        )

    def save_model(self, request, obj, form, change):
        from projectp.admin_permissions import current_admin
        request.user = current_admin(request, "auth.change_user" if change else "auth.add_user")
        if not request.user.is_superuser and (obj.is_staff or obj.is_superuser):
            raise PermissionDenied("Chỉ quản trị viên phù hợp mới được quản lý tài khoản đặc quyền.")
        if not request.user.is_superuser and "groups" in form.changed_data:
            previous = set(obj.groups.filter(name__startswith=TRACK_GROUP_PREFIX).values_list("pk", flat=True)) if obj.pk else set()
            chosen = {group.pk for group in form.cleaned_data["groups"] if group.name.startswith(TRACK_GROUP_PREFIX)}
            if previous != chosen:
                raise PermissionDenied("Chỉ quản trị viên cấp cao được phân phạm vi theo dõi tiếp nhận.")
        if self.privilege_fields.intersection(form.changed_data) and not self.can_manage_grants(request.user):
            raise PermissionDenied("Chưa có quyền quản lý nhóm/quyền của tài khoản.")
        return super().save_model(request, obj, form, change)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        restricted = (
            {"is_staff", "is_superuser"} if self.can_manage_grants(request.user) else self.privilege_fields
        )
        if (
            request.method == "POST"
            and not request.user.is_superuser
            and restricted.intersection(request.POST)
        ):
            raise PermissionDenied("Quyền sửa tài khoản không bao gồm cấp nhóm, quyền hoặc cờ Admin.")
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except DatabaseError:
            messages.error(request, "Chưa lưu được tài khoản. Dữ liệu cũ được giữ, vui lòng thử lại.")
            return redirect(request.path)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            from django.contrib.auth.models import Permission

            allowed = request.user.get_all_permissions()
            if db_field.name == "user_permissions":
                ids = [
                    p.pk
                    for p in Permission.objects.select_related("content_type")
                    if f"{p.content_type.app_label}.{p.codename}" in allowed
                ]
                kwargs["queryset"] = Permission.objects.filter(pk__in=ids)
            elif db_field.name == "groups":
                ids = [
                    g.pk
                    for g in Group.objects.prefetch_related("permissions__content_type")
                    if all(f"{p.content_type.app_label}.{p.codename}" in allowed for p in g.permissions.all())
                ]
                kwargs["queryset"] = Group.objects.filter(pk__in=ids)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def user_change_password(self, request, id, form_url=""):
        try:
            with transaction.atomic():
                response = super().user_change_password(request, id, form_url)
                if request.method == "POST" and response.status_code == 302:
                    NhatKyNghiepVu.objects.create(
                        nguoi_dung=request.user,
                        hanh_dong="UC-ACC-05:temporary_password",
                        loai_tai_nguyen="NGUOI_DUNG",
                        ma_tai_nguyen=str(id),
                        du_lieu_sau={"bat_buoc_doi_mat_khau": True},
                    )
                return response
        except DatabaseError:
            messages.error(request, "Chưa đặt lại được mật khẩu. Mật khẩu cũ được giữ.")
            return redirect(request.path)


User = get_user_model()
if admin.site.is_registered(User):
    admin.site.unregister(User)
admin.site.register(User, OzzoneUserAdmin)


class OzzoneGroupAdmin(GroupAdmin):
    def has_add_permission(self, request):
        return (
            request.user.is_superuser or request.user.has_perm("auth.change_permission")
        ) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if obj and obj.name.startswith(TRACK_GROUP_PREFIX) and not request.user.is_superuser:
            return False
        return (
            request.user.is_superuser or request.user.has_perm("auth.change_permission")
        ) and super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if obj.name.startswith(TRACK_GROUP_PREFIX) and not request.user.is_superuser:
            raise PermissionDenied("Chỉ quản trị viên cấp cao được cấu hình nhóm phạm vi theo dõi tiếp nhận.")
        super().save_model(request, obj, form, change)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "name" and field and request.user.is_superuser:
            field.help_text = (
                "Phạm vi theo dõi thông báo: OZZONE:SOC-09:toan_cong_ty hoặc "
                "OZZONE:SOC-09:phong_ban:<ID>. Có thể thay phong_ban bằng cong_dong, du_an hoặc nguoi_dung. "
                "Gắn quyền Được theo dõi tiếp nhận thông báo và thêm người được phân vào nhóm."
            )
        return field

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        allowed = request.user.get_all_permissions()
        ids = [
            g.pk
            for g in queryset.prefetch_related("permissions__content_type")
            if all(f"{p.content_type.app_label}.{p.codename}" in allowed for p in g.permissions.all())
        ]
        return queryset.filter(pk__in=ids)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "permissions" and not request.user.is_superuser:
            from django.contrib.auth.models import Permission

            allowed = request.user.get_all_permissions()
            ids = [
                p.pk
                for p in Permission.objects.select_related("content_type")
                if f"{p.content_type.app_label}.{p.codename}" in allowed
            ]
            kwargs["queryset"] = Permission.objects.filter(pk__in=ids)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


if admin.site.is_registered(Group):
    admin.site.unregister(Group)
admin.site.register(Group, OzzoneGroupAdmin)
