# Generated by Django 2.2.17 on 2021-01-15 09:51

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import latex.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LatexCollection',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('zip_file_key', models.TextField(db_index=True, verbose_name='Zip File Key')),
                ('compile_error', models.TextField(blank=True, null=True, verbose_name='Compile Error')),
                ('creation_time', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Creation time')),
            ],
        ),
        migrations.CreateModel(
            name='LatexProject',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Project name')),
                ('is_private', models.BooleanField(default=True)),
                ('creator', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='Creator')),
            ],
            options={
                'unique_together': {('name', 'creator')},
            },
        ),
        migrations.CreateModel(
            name='LatexPdf',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='File name')),
                ('pdf', models.FileField(blank=True, null=True, storage=latex.models.OverwriteStorage(), upload_to=latex.models.pdf_upload_to)),
                ('data_url', models.TextField(verbose_name='Data Url')),
                ('collection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='latex.LatexCollection', verbose_name='Collection')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='latex.LatexProject', verbose_name='Project')),
            ],
            options={
                'verbose_name': 'LaTeXPdf',
                'verbose_name_plural': 'LaTeXPdfs',
            },
        ),
        migrations.AddField(
            model_name='latexcollection',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='latex.LatexProject', verbose_name='Project'),
        ),
        migrations.AlterUniqueTogether(
            name='latexcollection',
            unique_together={('project', 'zip_file_key')},
        ),
    ]
