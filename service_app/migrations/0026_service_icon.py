# Generated manually: add Service.icon
from django.db import migrations, models
import service_app.models


class Migration(migrations.Migration):

    dependencies = [
        ("service_app", "0025_add_user_permission_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="icon",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="services/icons/",
                validators=[service_app.models.validate_image_or_svg],
            ),
        ),
    ]
