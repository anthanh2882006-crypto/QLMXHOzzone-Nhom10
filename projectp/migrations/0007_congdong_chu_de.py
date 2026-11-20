from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projectp", "0006_trial_author_and_stop_history")]

    operations = [
        migrations.AddField(
            model_name="congdong",
            name="chu_de",
            field=models.CharField("Chủ đề", max_length=150, blank=True),
        ),
    ]
