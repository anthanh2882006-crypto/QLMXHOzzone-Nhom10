from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projectp", "0004_thong_bao_dinh_chinh_reference")]

    operations = [
        migrations.RemoveConstraint(
            model_name="phancongtrithuc",
            name="uq_curator_active",
        ),
        migrations.AddConstraint(
            model_name="phancongtrithuc",
            constraint=models.UniqueConstraint(
                fields=("du_an",),
                condition=models.Q(ket_thuc_luc__isnull=True),
                name="uq_curator_project_active",
            ),
        ),
    ]
