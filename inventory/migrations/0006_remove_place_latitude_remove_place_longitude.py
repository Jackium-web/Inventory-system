# Generated migration to remove latitude and longitude fields from Place model

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0005_place_latitude_place_longitude'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='place',
            name='latitude',
        ),
        migrations.RemoveField(
            model_name='place',
            name='longitude',
        ),
    ]
