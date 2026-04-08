# Booking window + timezone on GHL appointment map (for quote details API)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobber_app", "0004_ghl_appointment_jobber_job_map"),
    ]

    operations = [
        migrations.AddField(
            model_name="ghlappointmentjobberjobmap",
            name="booking_start_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ghlappointmentjobberjobmap",
            name="booking_end_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ghlappointmentjobberjobmap",
            name="calendar_timezone",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="ghlappointmentjobberjobmap",
            name="raw_start_time_iso",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="ghlappointmentjobberjobmap",
            name="raw_end_time_iso",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AlterField(
            model_name="ghlappointmentjobberjobmap",
            name="submission_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
