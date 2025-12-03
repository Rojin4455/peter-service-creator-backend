# Generated migration for measurement_total field
from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('quote_app', '0027_customersubmission_bid_notes_private_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerpackagequote',
            name='measurement_total',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Total from measurement question (replaces base_price if higher)',
                max_digits=10
            ),
        ),
    ]

