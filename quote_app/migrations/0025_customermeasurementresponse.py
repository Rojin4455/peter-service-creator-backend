# Generated migration for CustomerMeasurementResponse model
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('service_app', '0023_question_measurement_fields'),
        ('quote_app', '0024_update_submission_status_values'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerMeasurementResponse',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('length', models.DecimalField(decimal_places=2, help_text='Length measurement', max_digits=10)),
                ('width', models.DecimalField(decimal_places=2, help_text='Width measurement', max_digits=10)),
                ('quantity', models.PositiveIntegerField(default=1, help_text='Quantity for this measurement row')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('option', models.ForeignKey(help_text='The rug type or measurement label', on_delete=django.db.models.deletion.CASCADE, to='service_app.questionoption')),
                ('question_response', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='measurement_responses', to='quote_app.customerquestionresponse')),
            ],
            options={
                'db_table': 'customer_measurement_responses',
            },
        ),
    ]

