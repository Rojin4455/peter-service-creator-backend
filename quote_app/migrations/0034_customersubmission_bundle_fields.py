from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('service_app', '0029_servicebundle'),
        ('quote_app', '0033_customersubmission_soft_delete'),
    ]

    operations = [
        migrations.AddField(
            model_name='customersubmission',
            name='applied_bundle',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='submissions',
                to='service_app.servicebundle',
            ),
        ),
        migrations.AddField(
            model_name='customersubmission',
            name='bundle_discount_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='customersubmission',
            name='is_bundle_applied',
            field=models.BooleanField(default=False),
        ),
    ]
