# GHL CRM note → Jobber client internal notes (idempotency)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobber_app", "0002_jobber_client_ghl_tag_sync_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="JobberGhlNoteForward",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ghl_note_id", models.CharField(db_index=True, max_length=128, unique=True)),
                ("ghl_contact_id", models.CharField(db_index=True, max_length=128)),
                ("jobber_client_id", models.CharField(db_index=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "jobber_ghl_note_forward",
                "ordering": ["-created_at"],
            },
        ),
    ]
