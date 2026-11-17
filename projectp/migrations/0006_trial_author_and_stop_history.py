from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def align_existing_trials(apps, schema_editor):
    Trial = apps.get_model("projectp", "LanThuPhuongAn")
    Conclusion = apps.get_model("projectp", "KetLuanXuLy")
    Audit = apps.get_model("projectp", "NhatKyNghiepVu")
    database = schema_editor.connection.alias
    trials = Trial.objects.using(database)
    for trial in trials.filter(
        trang_thai__in=("cho_ket_qua", "dang_thuc_hien"), ket_qua__isnull=True,
    ).select_related("phuong_an__bai_viet"):
        trials.filter(pk=trial.pk).update(
            nguoi_thuc_hien_id=trial.phuong_an.bai_viet.nguoi_dang_id,
        )
    for audit in Audit.objects.using(database).filter(hanh_dong="UC-PRJ-09"):
        data = audit.du_lieu_sau or {}
        conclusion = Conclusion.objects.using(database).filter(pk=data.get("conclusion_id")).first()
        if conclusion is None:
            continue
        trials.filter(
            pk__in=data.get("stopped_trial_ids", []),
            phuong_an__bai_viet_id=conclusion.bai_viet_nguon_id,
            trang_thai="da_huy", ket_qua__isnull=True,
        ).update(
            trang_thai="dung_thu",
            nguoi_xac_nhan_dung_id=audit.nguoi_dung_id or conclusion.nguoi_de_nghi_id,
            ket_luan_dung_id=conclusion.pk,
        )


def restore_previous_stop_state(apps, schema_editor):
    Trial = apps.get_model("projectp", "LanThuPhuongAn")
    Trial.objects.using(schema_editor.connection.alias).filter(trang_thai="dung_thu").update(
        trang_thai="da_huy", nguoi_xac_nhan_dung=None, ket_luan_dung=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("projectp", "0005_project_curator_scope"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="lanthuphuongan", name="ck_trial_lifecycle"),
        migrations.AddField(
            model_name="lanthuphuongan", name="nguoi_xac_nhan_dung",
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL, null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT, related_name="+",
            ),
        ),
        migrations.AddField(
            model_name="lanthuphuongan", name="ket_luan_dung",
            field=models.ForeignKey(
                to="projectp.ketluanxuly", null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT, related_name="lan_thu_dung",
            ),
        ),
        migrations.AlterField(
            model_name="lanthuphuongan", name="trang_thai",
            field=models.CharField(
                max_length=30, default="cho_ket_qua",
                choices=[
                    ("cho_ket_qua", "Chờ kết quả thực tế"),
                    ("dang_thuc_hien", "Đang thực hiện"),
                    ("da_co_ket_qua", "Đã có kết quả"),
                    ("dung_thu", "Dừng việc thử"),
                    ("da_huy", "Đã hủy"),
                ],
            ),
        ),
        migrations.RunPython(align_existing_trials, restore_previous_stop_state),
        migrations.AddConstraint(
            model_name="lanthuphuongan",
            constraint=models.CheckConstraint(
                name="ck_trial_lifecycle",
                condition=(
                    (
                        models.Q(trang_thai__in=["cho_ket_qua", "dang_thuc_hien"], ket_thuc_luc__isnull=True)
                        | models.Q(trang_thai="da_co_ket_qua", nguoi_thuc_hien__isnull=False, ket_thuc_luc__isnull=False)
                    )
                    | models.Q(trang_thai="da_huy", ket_thuc_luc__isnull=False) & ~models.Q(ly_do_huy="")
                    | models.Q(
                        trang_thai="dung_thu", ket_thuc_luc__isnull=False,
                        nguoi_xac_nhan_dung__isnull=False, ket_luan_dung__isnull=False,
                    ) & ~models.Q(ly_do_huy="")
                ),
            ),
        ),
    ]
