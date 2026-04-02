# Idempotency: GHL calendar appointment → Jobber job (booking webhook)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobber_app", "0003_jobber_ghl_note_forward"),
    ]

    operations = [
        migrations.CreateModel(
            name="GhlAppointmentJobberJobMap",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ghl_appointment_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("jobber_job_id", models.CharField(db_index=True, max_length=255)),
                ("submission_id", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "ghl_appointment_jobber_job_map",
                "ordering": ["-created_at"],
            },
        ),
    ]
