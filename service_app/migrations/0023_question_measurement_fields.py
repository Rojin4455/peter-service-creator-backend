# Generated migration for measurement question type
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('service_app', '0022_coupon_is_global'),
    ]

    operations = [
        migrations.AlterField(
            model_name='question',
            name='question_type',
            field=models.CharField(
                choices=[
                    ('yes_no', 'Yes/No'),
                    ('describe', 'Describe (Multiple Options)'),
                    ('multiple_yes_no', 'Multiple Yes/No Sub-Questions'),
                    ('conditional', 'Conditional Questions'),
                    ('quantity', 'How Many (Quantity Selection)'),
                    ('measurement', 'Area Measurement (Length × Width × Quantity)'),
                ],
                max_length=20
            ),
        ),
        migrations.AddField(
            model_name='question',
            name='measurement_unit',
            field=models.CharField(
                blank=True,
                choices=[
                    ('centimeters', 'Centimeters'),
                    ('centimetres', 'Centimetres'),
                    ('inches', 'Inches'),
                    ('feet', 'Feet'),
                    ('meters', 'Meters'),
                    ('metres', 'Metres'),
                ],
                help_text='Unit of measurement for length and width',
                max_length=20,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='question',
            name='allow_quantity',
            field=models.BooleanField(
                default=False,
                help_text='Allow quantity input for each measurement row'
            ),
        ),
        migrations.AddField(
            model_name='question',
            name='max_measurements',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Maximum number of measurement rows allowed. Null = infinite measurements allowed',
                null=True
            ),
        ),
    ]

