"""Giao diện Admin chung, phân nhóm theo năm UC quản trị của OZZONE."""

from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.admin import AdminSite
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.translation import override


# Nhóm điều hướng dùng lại app label và quyền hiện có của từng model.
ADMIN_GROUPS = (
    {
        "slug": "tai-khoan",
        "title": "Tài khoản",
        "description": "Quản trị tài khoản, nhóm quyền và danh mục nhân viên.",
        "primary": settings.AUTH_USER_MODEL.lower(),
        "count_label": "Tài khoản trong phạm vi",
        "models": (
            (settings.AUTH_USER_MODEL.lower(), "Tài khoản"),
            ("auth.group", "Nhóm quyền Django"),
            ("projectp.hosonhanvien", "Hồ sơ nhân viên"),
            ("projectp.phongban", "Phòng ban"),
            ("projectp.vitricongviec", "Vị trí công việc"),
            ("projectp.kynang", "Kỹ năng"),
            ("projectp.kynangnhanvien", "Kỹ năng nhân viên"),
        ),
    },
    {
        "slug": "kiem-duyet",
        "title": "Kiểm duyệt nội dung",
        "description": "Xem nội dung, thực hiện kiểm duyệt và tra cứu dữ liệu liên quan theo quyền.",
        "primary": "projectp.baiviet",
        "count_label": "Bài đăng trong phạm vi",
        "models": (
            ("projectp.baiviet", "Bài đăng"),
            ("projectp.binhluan", "Bình luận"),
            ("projectp.camxuc", "Cảm xúc"),
            ("projectp.baivietdaluu", "Bài đăng đã lưu"),
            ("projectp.thongbaochinhthuc", "Thông báo chính thức"),
            ("projectp.tieuchithongbao", "Tiêu chí phân phối thông báo"),
            ("projectp.nguoinhanthongbao", "Người nhận thông báo"),
            ("projectp.thongbaohethong", "Thông báo hệ thống"),
            ("projectp.teptin", "Tệp tin"),
            ("projectp.dinhkem", "Liên kết tệp đính kèm"),
        ),
    },
    {
        "slug": "cong-dong",
        "title": "Cộng đồng",
        "description": "Quản trị cộng đồng và trách nhiệm chủ sở hữu trong phạm vi được cấp.",
        "primary": "projectp.congdong",
        "count_label": "Cộng đồng trong phạm vi",
        "models": (
            ("projectp.congdong", "Cộng đồng"),
            ("projectp.thanhviencongdong", "Thành viên cộng đồng"),
            ("projectp.yeucauthamgia", "Yêu cầu tham gia"),
        ),
    },
    {
        "slug": "du-an",
        "title": "Dự án",
        "description": "Cập nhật thông tin, lưu trữ và đọc lịch sử dự án theo quyền.",
        "primary": "projectp.duan",
        "count_label": "Dự án trong phạm vi",
        "models": (
            ("projectp.duan", "Dự án"),
            ("projectp.thanhvienduan", "Thành viên dự án"),
            ("projectp.mathietbi", "Mã thiết bị"),
            ("projectp.taisanthietbi", "Tài sản thiết bị"),
            ("projectp.phancongtrithuc", "Phân công tri thức"),
            ("projectp.phuonganxuly", "Phương án xử lý"),
            ("projectp.lanthuphuongan", "Lần thử phương án"),
            ("projectp.ketquathu", "Kết quả thực hiện"),
            ("projectp.ketluanxuly", "Kết luận xử lý"),
        ),
    },
    {
        "slug": "tri-thuc",
        "title": "Tri thức",
        "description": "Quản trị trạng thái bài học, bài viết và xem phiên bản, nguồn theo quyền.",
        "primary": "projectp.baiviettrithuc",
        "count_label": "Bài viết tri thức trong phạm vi",
        "models": (
            ("projectp.baiviettrithuc", "Bài viết tri thức"),
            ("projectp.baihockinhnghiem", "Bài học kinh nghiệm"),
            ("projectp.phienbantrithuc", "Phiên bản tri thức"),
            ("projectp.nguonthamkhao", "Nguồn tham khảo"),
            ("projectp.chudetrithuc", "Chủ đề tri thức"),
            ("projectp.ganchudephienban", "Chủ đề của phiên bản"),
            ("projectp.chodanhgiatrithuc", "Hàng chờ đánh giá tri thức"),
        ),
    },
)


class OzzoneAdminSite(AdminSite):
    site_header = "OZZONE — Quản trị hệ thống"
    site_title = "OZZONE Admin"
    index_title = "Tổng quan quản trị"
    index_template = "admin/console/index.html"
    app_index_template = "admin/console/app_index.html"

    def admin_view(self, view, cacheable=False):
        protected_view = super().admin_view(view, cacheable)

        @wraps(protected_view)
        def vietnamese_admin(request, *args, **kwargs):
            with override("vi"):
                response = protected_view(request, *args, **kwargs)
                # TemplateResponse được render trong ngữ cảnh tiếng Việt của Admin.
                if hasattr(response, "render"):
                    response.render()
                return response

        return vietnamese_admin

    def login(self, request, extra_context=None):
        with override("vi"):
            response = super().login(request, extra_context)
            if hasattr(response, "render"):
                response.render()
            return response

    def logout(self, request, extra_context=None):
        target = request.GET.get("next") or reverse(f"{self.name}:index")
        return redirect(reverse("accounts:logout") + "?" + urlencode({"next": target}))

    def get_urls(self):
        return [
            path("phan-he/<slug:slug>/", self.admin_view(self.group_view), name="console_group"),
        ] + super().get_urls()

    def each_context(self, request):
        context = super().each_context(request)
        available = {
            item["model"]._meta.label_lower: item
            for app in context["available_apps"]
            for item in app["models"]
        }
        match = request.resolver_match
        current_model = ""
        current_group = ""
        if match:
            current_group = match.kwargs.get("slug", "")
            model_admin = getattr(match.func, "model_admin", None)
            if model_admin:
                current_model = model_admin.model._meta.label_lower
        groups = []
        for definition in ADMIN_GROUPS:
            entries = [
                {**available[label], "name": name}
                for label, name in definition["models"]
                if label in available
            ]
            if not entries:
                continue
            labels = {label for label, _ in definition["models"]}
            groups.append({
                **definition,
                "models": entries,
                "url": reverse("admin:console_group", kwargs={"slug": definition["slug"]}, current_app=self.name),
                "active": current_group == definition["slug"] or current_model in labels,
            })
        active_group = next((group for group in groups if group["active"]), None)
        active_model = None
        if active_group:
            active_model = next(
                (item for item in active_group["models"] if item["model"]._meta.label_lower == current_model),
                None,
            )
        if current_model == "projectp.nhatkynghiepvu":
            active_model = {**available.get(current_model, {}), "name": "Nhật ký quản trị"}
        context.update({
            "console_groups": groups,
            "console_current_group": active_group,
            "console_model": active_model,
            "console_audit": available.get("projectp.nhatkynghiepvu"),
            "console_audit_active": current_model == "projectp.nhatkynghiepvu",
            "console_home_active": bool(match and match.url_name == "index"),
        })
        return context

    def index(self, request, extra_context=None):
        context = self.each_context(request)
        registry = {model._meta.label_lower: model_admin for model, model_admin in self._registry.items()}
        for group in context["console_groups"]:
            group["count"] = None
            primary_admin = registry.get(group["primary"])
            visible_labels = {item["model"]._meta.label_lower for item in group["models"]}
            if primary_admin and group["primary"] in visible_labels:
                try:
                    group["count"] = primary_admin.get_queryset(request).count()
                except DatabaseError:
                    context["console_count_error"] = True
        context.update(extra_context or {})
        context.update({"title": "Tổng quan quản trị", "subtitle": None})
        request.current_app = self.name
        return TemplateResponse(request, self.index_template, context)

    def group_view(self, request, slug):
        context = self.each_context(request)
        group = next((item for item in context["console_groups"] if item["slug"] == slug), None)
        if group is None:
            raise PermissionDenied("Bạn chưa có quyền truy cập nhóm quản trị này.")
        context.update({"title": group["title"], "subtitle": None, "console_group": group})
        request.current_app = self.name
        return TemplateResponse(request, "admin/console/group.html", context)
