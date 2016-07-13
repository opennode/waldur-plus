from __future__ import unicode_literals

import functools
import logging
import sys

import digitalocean
from django.db import IntegrityError, transaction
from django.utils import six

from nodeconductor.core.models import SshPublicKey
from nodeconductor.structure import ServiceBackend, ServiceBackendError

from . import models


logger = logging.getLogger(__name__)


class DigitalOceanBackendError(ServiceBackendError):
    pass


class TokenScopeError(DigitalOceanBackendError):
    pass


class NotFoundError(DigitalOceanBackendError):
    pass


def digitalocean_error_handler(func):
    """
    Convert DigitalOcean exception to specific classes based on text message.
    It shoud be applied to functions which directly call `manager`.
    """
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        logger.debug('About to execute DO backend method `%s`' % func.__name__)
        try:
            return func(*args, **kwargs)
        except digitalocean.DataReadError as e:
            exc = list(sys.exc_info())
            message = six.text_type(e)
            if message == 'You do not have access for the attempted action.':
                exc[0] = TokenScopeError
                six.reraise(*exc)
            elif message == 'The resource you were accessing could not be found.':
                exc[0] = NotFoundError
                six.reraise(*exc)
            else:
                exc[0] = DigitalOceanBackendError
                six.reraise(*exc)
    return wrapped


class DigitalOceanBaseBackend(ServiceBackend):

    def __init__(self, settings):
        self.settings = settings
        self.manager = digitalocean.Manager(token=settings.token)

    def sync(self):
        self.pull_service_properties()
        self.pull_droplets()

    @digitalocean_error_handler
    def create_droplet(self, droplet, backend_region_id=None, backend_image_id=None,
                       backend_size_id=None, ssh_key_uuid=None):

        if ssh_key_uuid:
            ssh_key = SshPublicKey.objects.get(uuid=ssh_key_uuid)
            backend_ssh_key = self.get_or_create_ssh_key(ssh_key)

            droplet.key_name = ssh_key.name
            droplet.key_fingerprint = ssh_key.fingerprint

        backend_droplet = digitalocean.Droplet(
            token=self.manager.token,
            name=droplet.name,
            user_data=droplet.user_data,
            region=backend_region_id,
            image=backend_image_id,
            size_slug=backend_size_id,
            ssh_keys=[backend_ssh_key.id] if ssh_key_uuid else [])
        backend_droplet.create()

        action_id = backend_droplet.action_ids[-1]
        droplet.backend_id = backend_droplet.id
        droplet.save()
        return action_id

    @digitalocean_error_handler
    def destroy(self, droplet):
        backend_droplet = self.get_droplet(droplet.backend_id)
        backend_droplet.destroy()

    @digitalocean_error_handler
    def start(self, droplet):
        backend_droplet = self.get_droplet(droplet.backend_id)
        action = backend_droplet.power_on()
        return action['action']['id']

    @digitalocean_error_handler
    def stop(self, droplet):
        backend_droplet = self.get_droplet(droplet.backend_id)
        action = backend_droplet.shutdown()
        return action['action']['id']

    @digitalocean_error_handler
    def restart(self, droplet):
        backend_droplet = self.get_droplet(droplet.backend_id)
        action = backend_droplet.reboot()
        return action['action']['id']

    @digitalocean_error_handler
    def resize(self, droplet, backend_size_id=None, disk=None):
        backend_droplet = self.get_droplet(droplet.backend_id)
        action = backend_droplet.resize(new_size_slug=backend_size_id, disk=disk)
        return action['action']['id']

    @digitalocean_error_handler
    def remove_ssh_key(self, name, fingerprint):
        try:
            backend_ssh_key = self.pull_ssh_key(name, fingerprint)
        except NotFoundError:
            pass  # no need to perform any action if key doesn't exist at backend
        else:
            backend_ssh_key.destroy()


class DigitalOceanBackend(DigitalOceanBaseBackend):
    """ NodeConductor interface to Digital Ocean API.
        https://developers.digitalocean.com/documentation/v2/
        https://github.com/koalalorenzo/python-digitalocean
    """

    def ping(self, raise_exception=False):
        tries_count = 3
        for _ in range(tries_count):
            try:
                self.manager.get_account()
            except digitalocean.DataReadError as e:
                if raise_exception:
                    six.reraise(DigitalOceanBackendError, e)
            else:
                return True
        return False

    def ping_resource(self, droplet):
        tries_count = 3
        for _ in range(tries_count):
            try:
                self.get_droplet(droplet.backend_id)
            except DigitalOceanBackendError:
                logger.warning('Droplet %s (UUID: %s) is unreachable' % (droplet.name, droplet.uuid.hex))
            else:
                return True
        return False

    def pull_service_properties(self):
        self.pull_regions()
        self.pull_images()
        self.pull_sizes()

    def has_global_properties(self):
        properties = (models.Region, models.Image, models.Size)
        return all(model.objects.count() > 0 for model in properties)

    @transaction.atomic
    def pull_regions(self):
        cur_regions = self._get_current_properties(models.Region)
        for backend_region in self.manager.get_all_regions():
            if backend_region.available:
                cur_regions.pop(backend_region.slug, None)
                try:
                    models.Region.objects.update_or_create(
                        backend_id=backend_region.slug,
                        defaults={'name': backend_region.name})
                except IntegrityError:
                    logger.warning(
                        'Could not create DigitalOcean region with id %s due to concurrent update',
                        backend_region.slug)

        models.Region.objects.filter(backend_id__in=cur_regions.keys()).delete()

    @transaction.atomic
    def pull_images(self):
        cur_images = self._get_current_properties(models.Image)
        for backend_image in self.manager.get_all_images():
            cur_images.pop(str(backend_image.id), None)
            try:
                image, _ = models.Image.objects.update_or_create(
                    backend_id=backend_image.id,
                    defaults={
                        'name': '{} {}'.format(backend_image.distribution, backend_image.name),
                        'type': backend_image.type,
                        'distribution': backend_image.distribution,
                    })
                self._update_entity_regions(image, backend_image)
            except IntegrityError:
                logger.warning(
                    'Could not create DigitalOcean image with id %s due to concurrent update',
                    backend_image.id)

        models.Image.objects.filter(backend_id__in=cur_images.keys()).delete()

    @transaction.atomic
    def pull_sizes(self):
        cur_sizes = self._get_current_properties(models.Size)
        for backend_size in self.manager.get_all_sizes():
            cur_sizes.pop(backend_size.slug, None)
            try:
                size, _ = models.Size.objects.update_or_create(
                    backend_id=backend_size.slug,
                    defaults={
                        'name': backend_size.slug,
                        'cores': backend_size.vcpus,
                        'ram': backend_size.memory,
                        'disk': self.gb2mb(backend_size.disk),
                        'transfer': int(self.tb2mb(backend_size.transfer)),
                        'price': backend_size.price_hourly})
                self._update_entity_regions(size, backend_size)
            except IntegrityError:
                logger.warning(
                    'Could not create DigitalOcean size with id %s due to concurrent update',
                    backend_size.slug)

        models.Size.objects.filter(backend_id__in=cur_sizes.keys()).delete()

    @transaction.atomic
    def pull_droplets(self):
        backend_droplets = {six.text_type(droplet.id): droplet for droplet in self.get_all_droplets()}
        backend_ids = set(backend_droplets.keys())

        nc_droplets = models.Droplet.objects.filter(service_project_link__service__settings=self.settings)
        nc_droplets = {droplet.backend_id: droplet for droplet in nc_droplets}
        nc_ids = set(nc_droplets.keys())

        # Mark stale droplets as erred if they are removed from the backend
        for droplet_id in nc_ids - backend_ids:
            nc_droplet = nc_droplets[droplet_id]
            nc_droplet.set_erred()
            nc_droplet.save()

        # Update state of matching droplets
        for droplet_id in nc_ids & backend_ids:
            backend_droplet = backend_droplets[droplet_id]
            nc_droplet = nc_droplets[droplet_id]
            nc_droplet.state, nc_droplet.runtime_state = self._get_droplet_states(backend_droplet)
            nc_droplet.save()

    def _get_droplet_states(self, droplet):
        States = models.Droplet.States
        RuntimeStates = models.Droplet.RuntimeStates

        digitalocean_to_nodeconductor = {
            'new': (States.CREATING, 'provisioning'),
            'active': (States.OK, RuntimeStates.ONLINE),
            'off': (States.OK, RuntimeStates.OFFLINE),
            'archive': (States.OK, 'archive'),
        }

        return digitalocean_to_nodeconductor.get(droplet.status, (States.ERRED, 'error'))

    @digitalocean_error_handler
    def get_droplet(self, backend_droplet_id):
        return self.manager.get_droplet(backend_droplet_id)

    def get_monthly_cost_estimate(self, droplet):
        backend_droplet = self.get_droplet(droplet.backend_id)
        return backend_droplet.size['price_monthly']

    def get_resources_for_import(self):
        cur_droplets = models.Droplet.objects.all().values_list('backend_id', flat=True)
        statuses = ('active', 'off')
        droplets = self.get_all_droplets()
        return [{
            'id': droplet.id,
            'name': droplet.name,
            'created_at': droplet.created_at,
            'kernel': droplet.kernel['name'],
            'cores': droplet.vcpus,
            'ram': droplet.memory,
            'disk': self.gb2mb(droplet.disk),
            'flavor_name': droplet.size_slug
        } for droplet in droplets
            if str(droplet.id) not in cur_droplets and droplet.status in statuses]

    def get_managed_resources(self):
        try:
            ids = [droplet.id for droplet in self.get_all_droplets()]
            return models.Droplet.objects.filter(backend_id__in=ids)
        except DigitalOceanBackendError:
            return []

    @digitalocean_error_handler
    def get_all_droplets(self):
        return self.manager.get_all_droplets()

    def get_or_create_ssh_key(self, ssh_key):
        try:
            backend_ssh_key = self.pull_ssh_key(ssh_key)
        except NotFoundError:
            backend_ssh_key = self.push_ssh_key(ssh_key)
        return backend_ssh_key

    @digitalocean_error_handler
    def push_ssh_key(self, ssh_key):
        backend_ssh_key = digitalocean.SSHKey(
            token=self.manager.token,
            name=ssh_key.name,
            public_key=ssh_key.public_key)

        backend_ssh_key.create()
        return backend_ssh_key

    @digitalocean_error_handler
    def pull_ssh_key(self, name, fingerprint):
        backend_ssh_key = digitalocean.SSHKey(
            token=self.manager.token,
            fingerprint=fingerprint,
            name=name,
            id=None)

        backend_ssh_key.load()
        return backend_ssh_key

    def _get_current_properties(self, model):
        return {p.backend_id: p for p in model.objects.all()}

    def _update_entity_regions(self, entity, backend_entity):
        all_regions = set(entity.regions.all())
        actual_regions = set(models.Region.objects.filter(backend_id__in=backend_entity.regions))

        entity.regions.add(*(actual_regions - all_regions))
        entity.regions.remove(*(all_regions - actual_regions))
