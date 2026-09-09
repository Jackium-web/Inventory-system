# Generated migration to add ProductPairing model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_remove_place_latitude_remove_place_longitude'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductPairing',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('relationship_type', models.CharField(blank=True, help_text='Example: Charger for, Accessory for, Included with, etc.', max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('paired_product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pairings_as_paired', to='inventory.product')),
                ('primary_product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pairings_as_primary', to='inventory.product')),
            ],
            options={
                'ordering': ('-created_at',),
                'unique_together': {('primary_product', 'paired_product')},
            },
        ),
    ]
