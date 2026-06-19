from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("quote_app", "0032_repair_quote_url_public_domain"),
    ]

    operations = [
        migrations.AddField(
            model_name="customersubmission",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customersubmission",
            name="deleted_by",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="customersubmission",
            name="is_deleted",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
