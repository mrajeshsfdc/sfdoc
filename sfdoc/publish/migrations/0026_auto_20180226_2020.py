# -*- coding: utf-8 -*-
# Generated by Django 1.11.10 on 2018-02-26 20:20
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('publish', '0025_auto_20180226_1857'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='EasyditaBundle',
            new_name='Bundle',
        ),
        migrations.RenameField(
            model_name='article',
            old_name='easydita_bundle',
            new_name='bundle',
        ),
        migrations.RenameField(
            model_name='image',
            old_name='easydita_bundle',
            new_name='bundle',
        ),
        migrations.RenameField(
            model_name='webhook',
            old_name='easydita_bundle',
            new_name='bundle',
        ),
    ]
