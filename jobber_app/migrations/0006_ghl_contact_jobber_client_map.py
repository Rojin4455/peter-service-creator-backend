# GHL contact → Jobber client mapping (create-if-missing sync)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobber_app", "0005_ghl_appointment_job_map_times"),
    ]

    operations = [
        migrations.CreateModel(
            name="GhlContactJobberClientMap",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ghl_contact_id", models.CharField(db_index=True, max_length=128, unique=True)),
                ("jobber_client_id", models.CharField(db_index=True, max_length=255)),
                (
                    "client_created",
                    models.BooleanField(
                        default=False,
                        help_text="True when this sync created the Jobber client (vs found existing).",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "ghl_contact_jobber_client_map",
                "ordering": ["-updated_at"],
            },
        ),
    ]
