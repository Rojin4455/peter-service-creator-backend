from decouple import config
from django.db import migrations


def backfill_quote_urls(apps, schema_editor):
    CustomerSubmission = apps.get_model("quote_app", "CustomerSubmission")
    base_frontend_uri = config("BASE_FRONTEND_URI").rstrip("/")

    submissions = CustomerSubmission.objects.all().only("id", "quote_url")
    to_update = []

    for submission in submissions:
        expected_url = f"{base_frontend_uri}/booking?submission_id={submission.id}"
        if submission.quote_url != expected_url:
            submission.quote_url = expected_url
            to_update.append(submission)

    if to_update:
        CustomerSubmission.objects.bulk_update(to_update, ["quote_url"])


class Migration(migrations.Migration):
    dependencies = [
        ("quote_app", "0030_submission_image"),
    ]

    operations = [
        migrations.RunPython(backfill_quote_urls, migrations.RunPython.noop),
    ]
