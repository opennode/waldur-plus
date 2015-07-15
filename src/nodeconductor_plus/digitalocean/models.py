from __future__ import unicode_literals

from django.db import models
from django.utils.encoding import python_2_unicode_compatible

from nodeconductor.structure import models as structure_models


class Service(structure_models.Service):
    projects = models.ManyToManyField(
        structure_models.Project, related_name='+', through='ServiceProjectLink')


class ServiceProjectLink(structure_models.ServiceProjectLink):
    service = models.ForeignKey(Service)


class Region(structure_models.ServiceProperty):
    pass


@python_2_unicode_compatible
class Image(structure_models.ServiceProperty):
    regions = models.ManyToManyField(Region)
    distribution = models.CharField(max_length=100)
    type = models.CharField(max_length=100)

    @property
    def is_ssh_key_mandatory(self):
        OPTIONAL = 'Fedora', 'CentOS', 'Debian'
        MANDATORY = 'Ubuntu', 'FreeBSD', 'CoreOS'
        return self.distribution in MANDATORY

    def __str__(self):
        return '{} {} ({}) | {}'.format(self.name, self.distribution, self.type, self.settings)


class Size(structure_models.ServiceProperty):
    regions = models.ManyToManyField(Region)

    cores = models.PositiveSmallIntegerField(help_text='Number of cores in a VM')
    ram = models.PositiveIntegerField(help_text='Memory size in MiB')
    disk = models.PositiveIntegerField(help_text='Disk size in MiB')
    transfer = models.PositiveIntegerField(help_text='Amount of transfer bandwidth in MiB')


class Droplet(structure_models.VirtualMachineMixin, structure_models.Resource):
    service_project_link = models.ForeignKey(
        ServiceProjectLink, related_name='droplets', on_delete=models.PROTECT)

    ip_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv4')
    cores = models.PositiveSmallIntegerField(default=0, help_text='Number of cores in a VM')
    ram = models.PositiveIntegerField(default=0, help_text='Memory size in MiB')
    disk = models.PositiveIntegerField(default=0, help_text='Disk size in MiB')
    transfer = models.PositiveIntegerField(default=0, help_text='Amount of transfer bandwidth in MiB')
