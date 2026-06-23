import uuid
from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('service_app', '0028_addonservice_services'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceBundle',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
                (
                    'discount_type',
                    models.CharField(
                        choices=[('percent', 'Percentage'), ('fixed', 'Fixed Amount')],
                        default='percent',
                        max_length=10,
                    ),
                ),
                (
                    'discount_percentage',
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text='Percentage discount (0-100). Used when discount_type is percent.',
                        max_digits=5,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal('0.00')),
                            django.core.validators.MaxValueValidator(Decimal('100.00')),
                        ],
                    ),
                ),
                (
                    'discount_fixed',
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text='Fixed amount discount. Used when discount_type is fixed.',
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(Decimal('0.00'))],
                    ),
                ),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'services',
                    models.ManyToManyField(
                        help_text='Exact set of services required for this bundle (minimum 2).',
                        related_name='service_bundles',
                        to='service_app.service',
                    ),
                ),
            ],
            options={
                'db_table': 'service_bundles',
                'ordering': ['name'],
            },
        ),
    ]
