"""UC-ACC-05: thông tin tài khoản khác quyền cấp đặc quyền và mật khẩu tạm."""

from copy import deepcopy
import hashlib
import json
import logging
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
from notifications.permissions import NOTICE_SCOPE_PREFIXES
from projects.permissions import PROJECT_ADMIN_GROUP_PREFIX


from projectp.admin_scopes import OBJECT_SCOPE_PREFIXES
from .services import check_deactivation


SCOPED_GROUP_PREFIXES = (*NOTICE_SCOPE_PREFIXES, PROJECT_ADMIN_GROUP_PREFIX, *OBJECT_SCOPE_PREFIXES)


logger = logging.getLogger(__name__)


def audit_denied_grant(request, resource, object_id):
    if request.method != "POST":
        return
    identifier = str(object_id or "")
    if not (identifier.isascii() and identifier.isdecimal() and len(identifier) <= 19):
        identifier = ""
    try:
        NhatKyNghiepVu.objects.create(
            nguoi_dung=request.user,
            hanh_dong="UC-ACC-05:grant_denied",
            loai_tai_nguyen=resource,
            ma_tai_nguyen=identifier,
            ly_do="Yêu cầu quản trị quyền vượt quyền hoặc phạm vi được cấp.",
            du_lieu_sau={"ket_qua": "tu_choi"},
        )
    except DatabaseError:
        logger.exception("Chưa ghi được nhật ký yêu cầu bị từ chối của UC-ACC-05.")


def has_invalid_grant_choices(request, response, fields):
    if request.method != "POST" or not fields.intersection(request.POST):
        return False
    admin_form = (getattr(response, "context_data", None) or {}).get("adminform")
    if admin_form is None:
        return False
    errors = admin_form.form.errors.as_data()
    invalid_choices = {"invalid_choice", "invalid_pk_value", "invalid_list"}
    return any(
        error.code in invalid_choices
        for name in fields
        for error in errors.get(name, [])
    )


def account_snapshot(user):
    current = get_user_model().objects.get(pk=user.pk)
    profile = HoSoNhanVien.objects.filter(nguoi_dung=current).values(
        "ma_nhan_vien", "phong_ban_id", "vi_tri_id",
    ).first()
    return {
        "employee_profile": profile,
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
            if self.before["is_active"] and "is_active" in data and not data["is_active"]:
                try:
                    check_deactivation(self.instance.pk)
                except ValidationError as exc:
                    self.add_error("is_active", exc)
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


class EmployeeProfileInline(admin.StackedInline):
    model = HoSoNhanVien
    fk_name = "nguoi_dung"
    fields = ("ma_nhan_vien", "phong_ban", "vi_tri")
    extra = 0
    max_num = 1
    can_delete = False

    def get_extra(self, request, obj=None, **kwargs):
        return int(obj is None or not HoSoNhanVien.objects.filter(nguoi_dung=obj).exists())


class OzzoneUserAdmin(UserAdmin):
    """change_user chỉ sửa tài khoản thường; đặc quyền do superuser quản lý."""

    readonly_fields = ("employee_profile",)
    inlines = (EmployeeProfileInline,)
    add_fieldsets = (*UserAdmin.add_fieldsets, (
        "Thông tin tài khoản", {"fields": ("first_name", "last_name", "email", "is_active")},
    ))
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

    @admin.display(description="Hồ sơ nhân viên và thông tin tổ chức")
    def employee_profile(self, obj):
        profile = HoSoNhanVien.objects.filter(nguoi_dung=obj).select_related("phong_ban", "vi_tri").first()
        if not profile:
            return "Chưa liên kết hồ sơ nhân viên."
        from django.urls import reverse
        from django.utils.html import format_html

        return format_html(
            '{} · {} · {} · <a href="{}">Mở hồ sơ nhân viên</a>',
            profile.ma_nhan_vien, profile.phong_ban, profile.vi_tri,
            reverse("admin:projectp_hosonhanvien_change", args=[profile.pk]),
        )

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(deepcopy(super().get_fieldsets(request, obj)))
        if obj and (
            request.user.has_perm("projectp.view_hosonhanvien")
            or request.user.has_perm("projectp.change_hosonhanvien")
        ):
            fieldsets.append(("Thông tin tổ chức", {"fields": ("employee_profile",)}))
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
        from projectp.admin_permissions import current_admin

        for formset in formsets:
            if formset.model is not HoSoNhanVien:
                continue
            for inline in formset.forms:
                if inline.has_changed() and inline.cleaned_data:
                    permission = "change_hosonhanvien" if inline.instance.pk else "add_hosonhanvien"
                    current_admin(request, f"projectp.{permission}")
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
            previous = set((group.pk for group in obj.groups.all() if group.name.startswith(SCOPED_GROUP_PREFIXES))) if obj.pk else set()
            chosen = {group.pk for group in form.cleaned_data["groups"] if group.name.startswith(SCOPED_GROUP_PREFIXES)}
            if previous != chosen:
                raise PermissionDenied("Chỉ quản trị viên cấp cao được phân phạm vi nghiệp vụ.")
        if self.privilege_fields.intersection(form.changed_data) and not self.can_manage_grants(request.user):
            raise PermissionDenied("Chưa có quyền quản lý nhóm/quyền của tài khoản.")
        return super().save_model(request, obj, form, change)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        restricted = (
            {"is_staff", "is_superuser"} if self.can_manage_grants(request.user) else self.privilege_fields
        )
        try:
            if (
                request.method == "POST"
                and not request.user.is_superuser
                and restricted.intersection(request.POST)
            ):
                raise PermissionDenied("Quyền sửa tài khoản không bao gồm cấp nhóm, quyền hoặc cờ Admin.")
            response = super().changeform_view(request, object_id, form_url, extra_context)
        except PermissionDenied:
            # Django đã hoàn tác giao dịch biểu mẫu trước khi ghi sự kiện bị từ chối.
            audit_denied_grant(request, "NGUOI_DUNG", object_id)
            raise
        except DatabaseError:
            messages.error(request, "Chưa lưu được tài khoản. Dữ liệu cũ được giữ, vui lòng thử lại.")
            return redirect(request.path)
        if has_invalid_grant_choices(request, response, {"groups", "user_permissions"}):
            audit_denied_grant(request, "NGUOI_DUNG", object_id)
        return response

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

    def log_change(self, request, obj, message):
        result = super().log_change(request, obj, message)
        if request.resolver_match and request.resolver_match.url_name == "auth_user_password_change":
            requires_change = HoSoNhanVien.objects.filter(
                nguoi_dung=obj, bat_buoc_doi_mat_khau=True,
            ).exists()
            NhatKyNghiepVu.objects.create(
                nguoi_dung=request.user,
                hanh_dong=(
                    "UC-ACC-05:temporary_password"
                    if obj.has_usable_password()
                    else "UC-ACC-05:disable_password"
                ),
                loai_tai_nguyen="NGUOI_DUNG",
                ma_tai_nguyen=str(obj.pk),
                du_lieu_sau={"bat_buoc_doi_mat_khau": requires_change},
            )
        return result

    def user_change_password(self, request, id, form_url=""):
        try:
            with transaction.atomic():
                return super().user_change_password(request, id, form_url)
        except DatabaseError:
            messages.error(request, "Chưa đặt lại được mật khẩu. Mật khẩu cũ được giữ.")
            return redirect(request.path)


User = get_user_model()
if admin.site.is_registered(User):
    admin.site.unregister(User)
admin.site.register(User, OzzoneUserAdmin)


def group_snapshot(group):
    return {"name": group.name, "permissions": list(group.permissions.order_by("pk").values_list("pk", flat=True))}


def group_revision(group):
    return signing.dumps({"pk": group.pk, **group_snapshot(group)}, salt="accounts.admin.group")


class GroupChangeForm(forms.ModelForm):
    revision_token = forms.CharField(required=False, widget=forms.HiddenInput)
    ly_do_quyen = forms.CharField(
        required=False, max_length=1000, label="Lý do thay đổi nhóm/quyền",
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    class Meta:
        model = Group
        fields = ("name", "permissions")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "revision_token" in self.fields:
            self.fields["revision_token"].initial = group_revision(self.instance)

    def clean(self):
        data = super().clean()
        if (not self.instance.pk or {"name", "permissions"}.intersection(self.changed_data)) and not data.get("ly_do_quyen"):
            self.add_error("ly_do_quyen", "Nhập lý do thay đổi nhóm/quyền.")
        return data


class OzzoneGroupAdmin(GroupAdmin):
    form = GroupChangeForm
    fields = ("name", "permissions", "revision_token", "ly_do_quyen")
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            response = super().changeform_view(request, object_id, form_url, extra_context)
        except PermissionDenied:
            audit_denied_grant(request, "NHOM_QUYEN", object_id)
            raise
        except (ValidationError, DatabaseError) as exc:
            messages.error(request, " ".join(exc.messages) if isinstance(exc, ValidationError)
                           else "Chưa lưu nhóm quyền. Tải lại để đối chiếu.")
            return redirect(request.path)
        if has_invalid_grant_choices(request, response, {"permissions"}):
            audit_denied_grant(request, "NHOM_QUYEN", object_id)
        return response

    def has_add_permission(self, request):
        return (
            request.user.is_superuser or request.user.has_perm("auth.change_permission")
        ) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if obj and obj.name.startswith(SCOPED_GROUP_PREFIXES) and not request.user.is_superuser:
            return False
        return (
            request.user.is_superuser or request.user.has_perm("auth.change_permission")
        ) and super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        from projectp.admin_permissions import current_admin

        request.user = current_admin(request, "auth.change_group" if change else "auth.add_group")
        old = None
        if change:
            # Force a write lock on SQLite as well as databases supporting SELECT FOR UPDATE.
            Group.objects.filter(pk=obj.pk).update(name=F("name"))
            old = Group.objects.get(pk=obj.pk)
            try:
                submitted = signing.loads(
                    form.cleaned_data.get("revision_token", ""), salt="accounts.admin.group", max_age=8 * 60 * 60
                )
            except signing.BadSignature:
                raise ValidationError("Biểu mẫu nhóm quyền hết hiệu lực. Tải lại để đối chiếu.") from None
            if submitted != {"pk": old.pk, **group_snapshot(old)}:
                raise ValidationError("Nhóm hoặc quyền vừa thay đổi. Tải lại trước khi lưu.")
        may_save = self.has_change_permission(request, old) if old else self.has_add_permission(request)
        if not may_save or (obj.name.startswith(SCOPED_GROUP_PREFIXES) and not request.user.is_superuser):
            raise PermissionDenied("Bạn không có quyền cập nhật nhóm này.")
        permission_set = form.cleaned_data["permissions"]
        if not request.user.is_superuser:
            allowed = request.user.get_all_permissions()
            if any(f"{p.content_type.app_label}.{p.codename}" not in allowed for p in permission_set):
                raise PermissionDenied("Bạn không thể cấp quyền ngoài phạm vi được giao.")
        form.before = group_snapshot(old) if old else None
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        after = group_snapshot(form.instance)
        if form.before != after:
            NhatKyNghiepVu.objects.create(
                nguoi_dung=request.user, hanh_dong="UC-ACC-05:group_permissions",
                loai_tai_nguyen="NHOM_QUYEN", ma_tai_nguyen=str(form.instance.pk),
                du_lieu_truoc=form.before, du_lieu_sau=after,
                ly_do=form.cleaned_data["ly_do_quyen"],
            )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "name" and field and request.user.is_superuser:
            field.help_text = (
                "Phạm vi theo dõi thông báo: OZZONE:SOC-09:toan_cong_ty hoặc "
                "OZZONE:SOC-09:phong_ban:<ID>. Có thể thay phong_ban bằng cong_dong, du_an hoặc nguoi_dung. "
                "Dùng tiền tố OZZONE:SOC-06: cho quyền phát hành, OZZONE:SOC-09: cho quyền theo dõi. "
                "Gắn quyền chức năng tương ứng và thêm người được phân vào nhóm. "
                "Phạm vi quản trị dự án: OZZONE:PRJ-11:du_an:<ID>. "
                "Kiểm duyệt: OZZONE:SOC-10:du_an:<ID>, cong_dong:<ID> hoặc toan_cong_ty. "
                "Cộng đồng: OZZONE:COM-08:cong_dong:<ID> hoặc toan_cong_ty. "
                "Tri thức: OZZONE:KNW-06:bai_hoc:<ID>, bai_viet:<ID>, du_an:<ID>, cong_dong:<ID> hoặc toan_cong_ty."
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
