# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings
import taggit.managers


class Migration(migrations.Migration):

    dependencies = [
        ('agency', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tags', '0001_initial'),
        ('foia', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='foiarequest',
            name='tags',
            field=taggit.managers.TaggableManager(to='tags.Tag', through='tags.TaggedItemBase', blank=True, help_text='A comma-separated list of tags.', verbose_name='Tags'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiarequest',
            name='user',
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foianote',
            name='foia',
            field=models.ForeignKey(related_name='notes', to='foia.FOIARequest'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiamultirequest',
            name='agencies',
            field=models.ManyToManyField(related_name='agencies', null=True, to='agency.Agency', blank=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiamultirequest',
            name='tags',
            field=taggit.managers.TaggableManager(to='tags.Tag', through='tags.TaggedItemBase', blank=True, help_text='A comma-separated list of tags.', verbose_name='Tags'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiamultirequest',
            name='user',
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiafile',
            name='comm',
            field=models.ForeignKey(related_name='files', blank=True, to='foia.FOIACommunication', null=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiafile',
            name='foia',
            field=models.ForeignKey(related_name='files', blank=True, to='foia.FOIARequest', null=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiacommunication',
            name='foia',
            field=models.ForeignKey(related_name='communications', blank=True, to='foia.FOIARequest', null=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='foiacommunication',
            name='likely_foia',
            field=models.ForeignKey(related_name='likely_communications', blank=True, to='foia.FOIARequest', null=True),
            preserve_default=True,
        ),
    ]
