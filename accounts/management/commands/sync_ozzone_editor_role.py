"""Đồng bộ quyền của Actor Biên tập viên tri thức trong nhóm Django hiện có."""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from projectp.models import NhatKyNghiepVu


class Command(BaseCommand):
    help = "Đồng bộ nhóm Biên tập viên tri thức OZZONE với quyền tạo, sửa và công bố tri thức."

    @transaction.atomic
    def handle(self, *args, **options):
        permissions = list(
            Permission.objects.filter(
                content_type__app_label="projectp",
                codename__in=["add_baiviettrithuc", "change_baiviettrithuc", "cong_bo_tri_thuc"],
            )
        )
        if len(permissions) != 3:
            raise CommandError("Run migrate before synchronizing the knowledge editor role.")
        group, _ = Group.objects.get_or_create(name="Biên tập viên tri thức OZZONE")
        existing = set(group.permissions.values_list("pk", flat=True))
        added = [permission for permission in permissions if permission.pk not in existing]
        if added:
            group.permissions.add(*added)
            NhatKyNghiepVu.objects.create(
                hanh_dong="configure_knowledge_editor_role",
                loai_tai_nguyen="DJANGO_GROUP",
                ma_tai_nguyen=str(group.pk),
                du_lieu_sau={"group": group.name, "added_permissions": [p.codename for p in added]},
            )
        self.stdout.write(self.style.SUCCESS(f"Knowledge editor role synced. Added {len(added)} permission(s)."))
