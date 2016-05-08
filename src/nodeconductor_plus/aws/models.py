from __future__ import unicode_literals

from django.db import models
from libcloud.compute.drivers.ec2 import REGION_DETAILS

from nodeconductor.structure import models as structure_models
from nodeconductor.structure.utils import get_coordinates_by_ip


class AWSService(structure_models.Service):
    projects = models.ManyToManyField(
        structure_models.Project, related_name='aws_services', through='AWSServiceProjectLink')

    class Meta(structure_models.Service.Meta):
        verbose_name = 'AWS service'
        verbose_name_plural = 'AWS service'


class AWSServiceProjectLink(structure_models.ServiceProjectLink):
    service = models.ForeignKey(AWSService)

    class Meta(structure_models.ServiceProjectLink.Meta):
        verbose_name = 'AWS service project link'
        verbose_name_plural = 'AWS service project link'


class Region(structure_models.GeneralServiceProperty):
    class Meta:
        ordering = ['name']


class Image(structure_models.GeneralServiceProperty):
    class Meta:
        ordering = ['name']

    region = models.ForeignKey(Region)


class Size(structure_models.GeneralServiceProperty):
    class Meta:
        ordering = ['cores', 'ram']

    regions = models.ManyToManyField(Region)
    cores = models.PositiveSmallIntegerField(help_text='Number of cores in a VM')
    ram = models.PositiveIntegerField(help_text='Memory size in MiB')
    disk = models.PositiveIntegerField(help_text='Disk size in MiB')
    price = models.DecimalField('Hourly price rate', default=0, max_digits=11, decimal_places=5)


class Instance(structure_models.VirtualMachineMixin, structure_models.Resource):
    service_project_link = models.ForeignKey(
        AWSServiceProjectLink, related_name='instances', on_delete=models.PROTECT)

    region = models.ForeignKey(Region)

    def detect_coordinates(self):
        if self.external_ips:
            return get_coordinates_by_ip(self.external_ips)
        region = self.region.backend_id
        endpoint = REGION_DETAILS[region]['endpoint']
        return get_coordinates_by_ip(endpoint)
