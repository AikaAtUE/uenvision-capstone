# Adds CurriculumSurveyResponse — storage for the new public Student / Alumni /
# Professor curriculum-mapping surveys (separate from SurveyResponse, which is
# the logged-in-only SUS/UAT/Functional app-evaluation surveys).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0003_surveyresponse'),
    ]

    operations = [
        migrations.CreateModel(
            name='CurriculumSurveyResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('respondent_type', models.CharField(choices=[('student', 'Student'), ('alumni', 'Fresh Graduate / Alumni'), ('professor', 'Professor')], db_index=True, max_length=20)),
                ('data', models.JSONField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
