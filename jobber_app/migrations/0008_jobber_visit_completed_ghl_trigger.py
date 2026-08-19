from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobber_app", "0007_jobber_task_idempotency"),
    ]

    operations = [
        migrations.CreateModel(
            name="JobberVisitCompletedGhlTrigger",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "jobber_visit_id",
                    models.CharField(db_index=True, max_length=255, unique=True),
                ),
                (
                    "ghl_contact_id",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "jobber_visit_completed_ghl_trigger",
                "ordering": ["-created_at"],
            },
        ),
    ]
