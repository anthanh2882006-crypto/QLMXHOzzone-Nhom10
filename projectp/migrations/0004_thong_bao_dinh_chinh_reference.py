# Generated for UC-SOC-06: retain a structured reference when a published
# official notice is corrected. Published notices themselves remain immutable.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("projectp", "0003_align_report_40uc"),
    ]

    operations = [
        migrations.AddField(
            model_name="thongbaochinhthuc",
            name="thong_bao_tham_chieu",
            field=models.ForeignKey(
                blank=True,
                null=True,
                db_column="ma_thong_bao_tham_chieu",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="thong_bao_dinh_chinh",
                to="projectp.thongbaochinhthuc",
            ),
        ),
    ]
