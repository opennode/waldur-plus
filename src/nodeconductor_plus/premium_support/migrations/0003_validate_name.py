# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import nodeconductor.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('premium_support', '0002_plan_terms'),
    ]

    operations = [
        migrations.AlterField(
            model_name='plan',
            name='name',
            field=models.CharField(max_length=150, verbose_name='name', validators=[nodeconductor.core.validators.validate_name]),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='supportcase',
            name='name',
            field=models.CharField(max_length=150, verbose_name='name', validators=[nodeconductor.core.validators.validate_name]),
            preserve_default=True,
        ),
    ]
