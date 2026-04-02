from decouple import config
from django.db import migrations


def repair_quote_urls_to_public_domain(apps, schema_editor):
    CustomerSubmission = apps.get_model("quote_app", "CustomerSubmission")
    public_quote_base_url = config(
        "QUOTE_PUBLIC_BASE_URL",
        default="https://site.cleanonthego.com",
    ).rstrip("/")

    submissions = CustomerSubmission.objects.all().only("id", "quote_url")
    to_update = []

    for submission in submissions:
        expected_url = f"{public_quote_base_url}/booking?submission_id={submission.id}"
        if submission.quote_url != expected_url:
            submission.quote_url = expected_url
            to_update.append(submission)

    if to_update:
        CustomerSubmission.objects.bulk_update(to_update, ["quote_url"])


class Migration(migrations.Migration):
    dependencies = [
        ("quote_app", "0031_backfill_quote_url"),
    ]

    operations = [
        migrations.RunPython(repair_quote_urls_to_public_domain, migrations.RunPython.noop),
    ]
