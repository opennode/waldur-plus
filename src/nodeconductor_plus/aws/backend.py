import logging
import re

from django.db import IntegrityError
from django.utils import six, dateparse
from libcloud.common.types import LibcloudError
from libcloud.compute.drivers.ec2 import EC2NodeDriver, REGION_DETAILS, NAMESPACE, RESOURCE_EXTRA_ATTRIBUTES_MAP
from libcloud.compute.types import NodeState, StorageVolumeState
from libcloud.utils.xml import fixxpath

from nodeconductor.core.models import SshPublicKey
from nodeconductor.core.tasks import send_task
from nodeconductor.core.utils import hours_in_month
from nodeconductor.structure import ServiceBackend, ServiceBackendError

from . import models

logger = logging.getLogger(__name__)


RESOURCE_EXTRA_ATTRIBUTES_MAP['volume']['volume_type'] = {
    'xpath': 'volumeType',
    'transform_func': str
}


class ExtendedEC2NodeDriver(EC2NodeDriver):
    def get_node(self, node_id):
        """
        Get a node based on an node_id

        :param node_id: Node identifier
        :type node_id: ``str``

        :return: A Node object
        :rtype: :class:`Node`
        """

        return self.list_nodes(ex_node_ids=[node_id])[0]

    def list_volumes(self, node=None, ex_volume_ids=None, ex_filters=None):
        """
        List all volumes

        ex_volume_ids parameter is used to filter the list of
        volumes that should be returned. Only the volumes
        with the corresponding volume ids will be returned.

        :param      ex_volume_ids: List of ``volume.id``
        :type       ex_volume_ids: ``list`` of ``str``

        :param      ex_filters: The filters so that the response includes
                                information for only certain volumes.
        :type       ex_filters: ``dict``

        :rtype: ``list`` of :class:`Node`
        """

        params = {
            'Action': 'DescribeVolumes',
        }
        if node:
            filters = {'attachment.instance-id': node.id}
            params.update(self._build_filters(filters))

        if ex_volume_ids:
            params.update(self._pathlist('VolumeId', ex_volume_ids))

        if ex_filters:
            params.update(self._build_filters(ex_filters))

        response = self.connection.request(self.path, params=params).object
        volumes = [self._to_volume(el) for el in response.findall(
            fixxpath(xpath='volumeSet/item', namespace=NAMESPACE))
        ]
        return volumes

    def get_volume(self, volume_id):
        """
        Get a volume based on an volume_id

        :param volume_id: Volume identifier
        :type volume_id: ``str``

        :return: A Volume object
        :rtype: :class:`Volume`
        """
        return self.list_volumes(ex_volume_ids=[volume_id])[0]

    # Location is required argument
    # http://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html
    def create_volume(self, size, name, location, snapshot=None,
                      ex_volume_type='standard', ex_iops=None):
        """
        Create a new volume.

        :param size: Size of volume in gigabytes (required)
        :type size: ``int``

        :param name: Name of the volume to be created
        :type name: ``str``

        :param snapshot:  Snapshot from which to create the new
                               volume.  (optional)
        :type snapshot:  :class:`.VolumeSnapshot`

        :param location: Datacenter in which to create a volume in (required).
        :type location: :class:`.ExEC2AvailabilityZone`

        :param ex_volume_type: Type of volume to create.
        :type ex_volume_type: ``str``

        :param iops: The number of I/O operations per second (IOPS)
                     that the volume supports. Only used if ex_volume_type
                     is io1.
        :type iops: ``int``

        :return: The newly created volume.
        :rtype: :class:`StorageVolume`
        """
        valid_volume_types = ['standard', 'io1', 'gp2']

        params = {
            'Action': 'CreateVolume',
            'Size': str(size)}

        if ex_volume_type and ex_volume_type not in valid_volume_types:
            raise ValueError('Invalid volume type specified: %s' %
                             (ex_volume_type))

        if snapshot:
            params['SnapshotId'] = snapshot.id

        params['AvailabilityZone'] = location.name

        if ex_volume_type:
            params['VolumeType'] = ex_volume_type

        if ex_volume_type == 'io1' and ex_iops:
            params['Iops'] = ex_iops

        volume = self._to_volume(
            self.connection.request(self.path, params=params).object,
            name=name)

        if self.ex_create_tags(volume, {'Name': name}):
            volume.extra['tags']['Name'] = name

        return volume


class AWSBackendError(ServiceBackendError):
    pass


class AWSBaseBackend(ServiceBackend):
    State = NodeState

    Regions = (('us-east-1', 'US East (N. Virginia)'),
               ('us-west-2', 'US West (Oregon)'),
               ('us-west-1', 'US West (N. California)'),
               ('eu-west-1', 'EU (Ireland)'),
               ('eu-central-1', 'EU (Frankfurt)'),
               ('ap-southeast-1', 'Asia Pacific (Singapore)'),
               ('ap-southeast-2', 'Asia Pacific (Sydney)'),
               ('ap-northeast-1', 'Asia Pacific (Tokyo)'),
               ('sa-east-1', 'South America (Sao Paulo)'))

    def __init__(self, settings):
        super(AWSBaseBackend, self).__init__(settings)
        self.settings = settings

    def _get_api(self, region='us-east-1'):
        return ExtendedEC2NodeDriver(
            self.settings.username, self.settings.token, region=region)

    def sync(self):
        self.pull_service_properties()

    def provision(self, vm, region=None, image=None, size=None, ssh_key=None):
        vm.ram = size.ram
        vm.disk = size.disk
        vm.cores = size.cores
        vm.region = region
        vm.save()

        send_task('aws', 'provision')(
            vm.uuid.hex,
            backend_image_id=image.backend_id,
            backend_size_id=size.backend_id,
            ssh_key_uuid=ssh_key.uuid.hex if ssh_key else None)

    def destroy(self, vm, force=False):
        if force:
            vm.delete()
            return

        vm.schedule_deletion()
        vm.save()
        send_task('aws', 'destroy')(vm.uuid.hex)

    def start(self, vm):
        vm.schedule_starting()
        vm.save()
        send_task('aws', 'start')(vm.uuid.hex)

    def stop(self, vm):
        vm.schedule_stopping()
        vm.save()
        send_task('aws', 'stop')(vm.uuid.hex)

    def restart(self, vm):
        vm.schedule_restarting()
        vm.save()
        send_task('aws', 'restart')(vm.uuid.hex)


class AWSBackend(AWSBaseBackend):
    """ NodeConductor interface to AWS EC2 API.
        https://libcloud.apache.org/
    """

    def ping(self, raise_exception=False):
        try:
            self._get_api().list_key_pairs()
        except Exception as e:
            if raise_exception:
                six.reraise(AWSBackendError, e)
            return False
        else:
            return True

    def ping_resource(self, instance):
        try:
            manager = self.get_manager(instance)
            manager.get_node(instance.backend_id)
        except:
            return False
        else:
            return True

    def pull_service_properties(self):
        self.pull_regions()
        self.pull_sizes()
        self.update_images()

    def pull_regions(self):
        nc_regions = set(models.Region.objects.values_list('backend_id', flat=True))
        for backend_id, name in self.Regions:
            if backend_id in nc_regions:
                continue
            try:
                models.Region.objects.create(backend_id=backend_id, name=name)
            except IntegrityError:
                message = 'Could not create AWS region with name %s due to concurrent update'
                logger.warning(message, name)

    def pull_sizes(self):
        regions = models.Region.objects.values_list('backend_id', flat=True)
        for region in regions:
            manager = self._get_api(region)

            # XXX: Obviously each region has a different price,
            #      find a better form of models relation
            for backend_size in manager.list_sizes():
                size, _ = models.Size.objects.update_or_create(
                    backend_id=backend_size.id,
                    defaults={
                        'name': backend_size.name,
                        'cores': backend_size.extra.get('cpu', 1),
                        'ram': self.gb2mb(backend_size.ram),
                        'disk': self.gb2mb(backend_size.disk),
                        'price': backend_size.price,
                    })

                current_regions = set(size.regions.all())
                backend_regions = set(models.Region.objects.filter(backend_id__in=[
                    r for r, v in REGION_DETAILS.items() if backend_size.id in v['instance_types']]))

                size.regions.add(*(backend_regions - current_regions))
                size.regions.remove(*(current_regions - backend_regions))

    def pull_images(self):
        cur_images = {i.backend_id: i for i in models.Image.objects.all()}

        for region, backend_image in self.get_all_images():
            cur_images.pop(backend_image.id, None)
            try:
                models.Image.objects.update_or_create(
                    backend_id=backend_image.id,
                    defaults={
                        'name': backend_image.name,
                        'region': region
                    })
            except IntegrityError:
                logger.warning(
                    'Could not create AWS image with id %s due to concurrent update',
                    backend_image.id)

        # Remove stale images using one SQL query
        models.Image.objects.filter(backend_id__in=cur_images.keys()).delete()

    def create_volume(self, volume):
        try:
            manager = self._get_api(volume.region.backend_id)
            zones = manager.ex_list_availability_zones()
            # Availability zone is required by AWS
            new_volume = manager.create_volume(
                location=zones[0],
                size=volume.size,
                name=volume.name,
                ex_volume_type=volume.volume_type
            )
            volume.backend_id = new_volume.id
            volume.save(update_fields=['backend_id'])
        except Exception as e:
            logger.exception('Unable to create volume with id %s', volume.id)
            six.reraise(AWSBackendError, e)

    def delete_volume(self, volume):
        try:
            manager = self._get_api(volume.region.backend_id)
            manager.destroy_volume(self.get_volume(volume))
        except Exception as e:
            logger.exception('Unable to delete volume with id %s', volume.id)
            six.reraise(AWSBackendError, e)

    def attach_volume(self, instance, volume, device):
        """
        Attach volume to the instance
        """
        manager = self._get_api(volume.region.backend_id)
        backend_node = manager.get_node(instance.backend_id)
        backend_volume = manager.get_volume(volume.backend_id)
        try:
            manager.attach_volume(backend_node, backend_volume, device)
        except LibcloudError as e:
            logger.exception('Unable to attach volume with id %s to instance with id %s',
                             volume.id, instance.id)
            six.reraise(AWSBackendError, e)

    def detach_volume(self, volume):
        """
        Detach volume from the instance
        """
        manager = self._get_api(volume.region.backend_id)
        backend_volume = manager.get_volume(volume.backend_id)
        try:
            manager.detach_volume(backend_volume)
        except LibcloudError as e:
            logger.exception('Unable to detach volume with id %s', volume.id)
            six.reraise(AWSBackendError, e)

    def get_all_images(self):
        """
        Fetch images from all regions
        """
        # TODO: change into a more flexible filtering
        options = self.settings.options or {}
        regex = None
        if 'images_regex' in options:
            try:
                regex = re.compile(options['images_regex'])
            except re.error:
                logger.warning(
                    'Invalid images regexp supplied for service settings %s: %s',
                    self.settings.uuid, options['images_regex'])

        for region in models.Region.objects.all():
            manager = self._get_api(region.backend_id)
            # opinionated filter for populating image list
            for image in manager.list_images(ex_owner='aws-marketplace',
                                             ex_filters={'virtualization-type': 'hvm', 'image-type': 'machine'}):
                # Skip images without name
                if image.name:
                    if regex and not regex.match(image.name):
                        continue
                    yield region, image

    def update_images(self):
        get_images = lambda manager, owner: {
            i.id: i.extra['description']
            for i in manager.list_images(
                ex_owner=owner,
                ex_filters={'virtualization-type': 'hvm', 'image-type': 'machine'})}

        for region in models.Region.objects.all():
            images = region.image_set.all()
            if images.count():
                manager = self._get_api(region.backend_id)
                backend_images = get_images(manager, 'amazon')
                backend_images.update(get_images(manager, 'aws-marketplace'))
                for image in images:
                    try:
                        image.name = backend_images[image.backend_id]
                    except KeyError:
                        image.delete()
                    else:
                        image.save()

    def get_all_nodes(self):
        """
        Fetch nodes from all regions
        """
        try:
            for region in models.Region.objects.all():
                manager = self._get_api(region.backend_id)
                for node in manager.list_nodes():
                    yield region, node
        except LibcloudError as e:
            six.reraise(AWSBackendError, e)

    def provision_vm(self, vm, backend_image_id=None, backend_size_id=None, ssh_key_uuid=None):
        manager = self.get_manager(vm)

        params = dict(name=vm.name,
                      image=self.get_image(backend_image_id, manager),
                      size=self.get_size(backend_size_id, manager),
                      ex_custom_data=vm.user_data)

        if ssh_key_uuid:
            ssh_key = SshPublicKey.objects.get(uuid=ssh_key_uuid)
            try:
                backend_ssh_key = self.get_or_create_ssh_key(ssh_key, manager)
            except LibcloudError as e:
                logger.exception('Unable to provision SSH key %s', ssh_key_uuid)
                six.reraise(AWSBackendError, e)

            params['ex_keyname'] = backend_ssh_key['keyName']

        try:
            backend_vm = manager.create_node(**params)
        except LibcloudError as e:
            logger.exception('Failed to provision virtual machine %s', vm.name)
            six.reraise(AWSBackendError, e)

        if ssh_key_uuid:
            vm.key_name = ssh_key.name
            vm.key_fingerprint = ssh_key.fingerprint

        vm.backend_id = backend_vm.id
        vm.save()
        return vm

    def reboot_vm(self, vm):
        try:
            manager = self.get_manager(vm)
            manager.reboot_node(manager.get_node(vm.backend_id))
        except Exception as e:
            logger.exception('Unable to reboot Amazon virtual machine %s', vm.uuid.hex)
            six.reraise(AWSBackendError, six.text_type(e))

    def stop_vm(self, vm):
        try:
            manager = self.get_manager(vm)
            manager.ex_stop_node(manager.get_node(vm.backend_id))
        except Exception as e:
            logger.exception('Unable to stop Amazon virtual machine %s', vm.uuid.hex)
            six.reraise(AWSBackendError, six.text_type(e))

    def start_vm(self, vm):
        try:
            manager = self.get_manager(vm)
            manager.ex_start_node(manager.get_node(vm.backend_id))
        except Exception as e:
            logger.exception('Unable to start Amazon virtual machine %s', vm.uuid.hex)
            six.reraise(AWSBackendError, six.text_type(e))

    def destroy_vm(self, vm):
        try:
            manager = self.get_manager(vm)
            manager.destroy_node(manager.get_node(vm.backend_id))
        except Exception as e:
            logger.exception('Unable to destroy Amazon virtual machine %s', vm.uuid.hex)
            six.reraise(AWSBackendError, six.text_type(e))

    def get_monthly_cost_estimate(self, instance):
        manager = self.get_manager(instance)
        try:
            backend_instance = manager.get_node(instance.backend_id)
        except Exception as e:
            six.reraise(AWSBackendError, e)

        size = self.get_size(backend_instance.extra['instance_type'], manager)

        # calculate a price for current month based on hourly rate
        return size.price * hours_in_month()

    def to_instance(self, instance, region):
        from nodeconductor.structure import SupportedServices

        manager = self._get_api(region.backend_id)
        # TODO: Connect volume with instance
        try:
            volumes = {v.id: v.size for v in manager.list_volumes(instance)}
        except Exception as e:
            six.reraise(AWSBackendError, e)

        for device in instance.extra['block_device_mapping']:
            vid = device['ebs']['volume_id']
            if vid in volumes:
                device['ebs']['volume_size'] = volumes[vid]

        # libcloud is a funny buggy thing, put all required info here
        instance_type = self.get_size(instance.extra['instance_type'], manager)
        external_ips = instance.public_ips and instance.public_ips[0] or None

        return {
            'id': instance.id,
            'name': instance.name or instance.uuid,
            'cores': instance_type.extra.get('cpu', 1),
            'ram': instance_type.ram,
            'disk': self.gb2mb(sum(volumes.values())),
            'created': dateparse.parse_datetime(instance.extra['launch_time']),
            'region': region.uuid.hex,
            'state': self._get_instance_state(instance.state),
            'external_ips': external_ips,
            'flavor_name': instance.extra.get('instance_type'),
            'type': SupportedServices.get_name_for_model(models.Instance)
        }

    def _get_instance_state(self, state):
        aws_to_nodeconductor = {
            NodeState.RUNNING: models.Instance.States.ONLINE,
            NodeState.REBOOTING: models.Instance.States.RESTARTING,
            NodeState.TERMINATED: models.Instance.States.OFFLINE,
            NodeState.PENDING: models.Instance.States.PROVISIONING,
            NodeState.STOPPED: models.Instance.States.OFFLINE,
            NodeState.SUSPENDED: models.Instance.States.OFFLINE,
            NodeState.PAUSED: models.Instance.States.OFFLINE,
            NodeState.ERROR: models.Instance.States.ERRED
        }

        return aws_to_nodeconductor.get(state, models.Instance.States.ERRED)

    def get_manager(self, instance):
        return self._get_api(instance.region.backend_id)

    def get_size(self, size_id, manager):
        try:
            return next(s for s in manager.list_sizes() if s.id == size_id)
        except (StopIteration, LibcloudError) as e:
            logger.exception("Size %s doesn't exist", size_id)
            six.reraise(AWSBackendError, e)

    def get_image(self, image_id, manager):
        try:
            return manager.get_image(image_id)
        except (StopIteration, LibcloudError) as e:
            logger.exception("Image %s doesn't exist", image_id)
            six.reraise(AWSBackendError, e)

    def get_or_create_ssh_key(self, ssh_key, manager):
        try:
            return manager.ex_describe_keypair(ssh_key.name)
        except LibcloudError:
            return manager.ex_import_keypair_from_string(ssh_key.name, ssh_key.public_key)

    def get_resources_for_import(self, resource_type=None):
        from nodeconductor.structure import SupportedServices

        resources = []

        if resource_type is None or resource_type == SupportedServices.get_name_for_model(models.Instance):
            resources.extend(self.get_instances_for_import())

        if resource_type is None or resource_type == SupportedServices.get_name_for_model(models.Volume):
            resources.extend(self.get_volumes_for_import())
        return resources

    def get_instances_for_import(self):
        cur_instances = models.Instance.objects.all().values_list('backend_id', flat=True)

        return [
            self.to_instance(instance, region)
            for region, instance in self.get_all_nodes()
            if instance.id not in cur_instances and
            instance.state != NodeState.TERMINATED
        ]

    def get_volumes_for_import(self):
        cur_volumes = models.Volume.objects.all().values_list('backend_id', flat=True)
        return [
            self.to_volume(region, volume)
            for region, volume in self.get_all_volumes()
            if volume.id not in cur_volumes and
            volume.state != StorageVolumeState.DELETED
        ]

    def find_instance(self, instance_id):
        for region in models.Region.objects.all():
            manager = self._get_api(region.backend_id)
            try:
                instance = manager.get_node(instance_id)
            except:
                # Instance not found
                pass
            else:
                return region, self.to_instance(instance, region)
        raise AWSBackendError("Instance with id %s is not found", instance_id)

    def find_volume(self, volume_id):
        for region in models.Region.objects.all():
            manager = self._get_api(region.backend_id)
            try:
                volume = manager.get_volume(volume_id)
            except:
                # Volume not found
                pass
            else:
                return region, self.to_volume(region, volume)
        raise AWSBackendError("Volume with id %s is not found", volume_id)

    def get_managed_resources(self):
        backend_instance = self.get_managed_instances()
        backend_volumes = self.get_managed_volumes()
        return list(backend_instance) + list(backend_volumes)

    def get_managed_instances(self):
        try:
            ids = [instance.id for region, instance in self.get_all_nodes()]
            return models.Instance.objects.filter(backend_id__in=ids)
        except LibcloudError:
            return []

    def get_managed_volumes(self):
        try:
            ids = [volume.id for region, volume in self.get_all_volumes()]
            return models.Volume.objects.filter(backend_id__in=ids)
        except LibcloudError:
            return []

    def get_all_volumes(self):
        try:
            for region in models.Region.objects.all():
                manager = self._get_api(region.backend_id)
                for node in manager.list_volumes():
                    yield region, node
        except Exception as e:
            logger.exception('Unable to list EC2 volumes')
            six.reraise(AWSBackendError, e)

    def to_volume(self, region, volume):
        from nodeconductor.structure import SupportedServices

        return {
            'id': volume.id,
            'name': volume.name,
            'size': volume.size,
            'created': volume.extra['create_time'],
            'state': self._get_volume_state(volume.state),
            'runtime_state': volume.state,
            'type': SupportedServices.get_name_for_model(models.Volume),
            'device': volume.extra['device'],
            'instance_id': volume.extra['instance_id'],
            'volume_type': volume.extra['volume_type']
        }

    def _get_volume_state(self, state):
        aws_to_nodeconductor = {
            StorageVolumeState.AVAILABLE: models.Volume.States.OK,
            StorageVolumeState.INUSE: models.Volume.States.OK,
            StorageVolumeState.CREATING: models.Volume.States.CREATING,
            StorageVolumeState.DELETING: models.Volume.States.DELETING,
            StorageVolumeState.ATTACHING: models.Volume.States.UPDATING
        }

        return aws_to_nodeconductor.get(state, models.Volume.States.ERRED)

    def get_volume(self, volume):
        try:
            manager = self._get_api(volume.region.backend_id)
            return manager.get_volume(volume.backend_id)
        except LibcloudError as e:
            six.reraise(AWSBackendError, e)

    def pull_volume_runtime_state(self, volume):
        backend_volume = self.get_volume(volume)
        if backend_volume.state != volume.runtime_state:
            volume.runtime_state = backend_volume.state
            volume.save(update_fields=['runtime_state'])
