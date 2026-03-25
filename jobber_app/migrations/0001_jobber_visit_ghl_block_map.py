# Generated manually for Jobber ↔ GHL calendar block sync

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="JobberVisitGhlBlockMap",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jobber_visit_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("ghl_event_id", models.CharField(db_index=True, max_length=255)),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField()),
                ("title", models.CharField(blank=True, default="", max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "jobber_visit_ghl_block_map",
                "ordering": ["-updated_at"],
            },
        ),
    ]
