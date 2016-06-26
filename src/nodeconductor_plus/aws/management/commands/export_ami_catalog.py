from __future__ import unicode_literals


from django.core.management.base import BaseCommand, CommandError

from nodeconductor.core.csv import UnicodeDictWriter
from nodeconductor_plus.aws.models import Image


class Command(BaseCommand):
    help_text = "Export catalog of Amazon images."
    args = "[ami_catalog.csv]"

    def handle(self, *args, **options):
        if len(args) == 0:
            raise CommandError('AMI catalog filename is not specified.')

        writer = UnicodeDictWriter(open(args[0], 'w'), fieldnames=('name', 'region', 'backend_id'))
        writer.writeheader()
        rows = [dict(name=image.name, region=image.region.name, backend_id=image.backend_id)
                for image in Image.objects.all()]
        writer.writerows(rows)