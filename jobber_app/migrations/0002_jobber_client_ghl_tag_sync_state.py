# Jobber ↔ GHL client/contact tag sync state

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobber_app", "0001_jobber_visit_ghl_block_map"),
    ]

    operations = [
        migrations.CreateModel(
            name="JobberClientGhlTagSyncState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jobber_client_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("ghl_contact_id", models.CharField(blank=True, default="", max_length=255)),
                ("last_jobber_tag_signature", models.CharField(blank=True, default="", max_length=64)),
                ("last_ghl_tag_signature", models.CharField(blank=True, default="", max_length=64)),
                (
                    "last_sync_source",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="'jobber' or 'ghl' — which system we last pushed from.",
                        max_length=16,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "jobber_client_ghl_tag_sync_state",
                "ordering": ["-updated_at"],
            },
        ),
    ]
