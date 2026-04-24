# GHL-stored service icon: drop FileField, add URL + GHL file id
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("service_app", "0026_service_icon"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="service",
            name="icon",
        ),
        migrations.AddField(
            model_name="service",
            name="icon_file_id",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="service",
            name="icon_url",
            field=models.TextField(blank=True, null=True),
        ),
    ]
