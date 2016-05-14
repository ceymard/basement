#!/usr/bin/python3

import pprint
pp = pprint.PrettyPrinter(indent=2, compact=True)

import os
import sys
from datetime import datetime
from time import time
from os import path
from docker import Client, errors
from argparse import ArgumentParser
from subprocess import run

cl = Client(base_url='unix://var/run/docker.sock')

def get_backup_name(args):
	if args.backup_name: return args.backup_name

	target_infos = cl.inspect_container(args.container)
	target_labels = target_infos['Config']['Labels']

	# give a name to the backup, or just infer one from the container's name and id
	backup_name = target_labels.get('basement.backup-name', '{}-{}'.format(args.container, target_infos['Id'][:8]))
	return backup_name

def get_linked_containers(cont):
	'''
		Get the list of all the *running* containers using the volumes of `cont`.

		It finds them simply by looking at their mount points and seeing if they're running.
	'''

	mounts = map(lambda m: m['Source'], cl.inspect_container(cont)['Mounts'])

def get_mounts(cont, prefix=''):
	info = cl.inspect_container(cont)
	if 'Mounts' in info:
		return list(map(
			lambda m: dict(src=m['Source'], dst=prefix + m['Destination']),
			info['Mounts']
		))
	else:
		return [dict(src=k, dst=prefix + v) for k, v in info['Volumes'].items()]


def rerun_with_mounts(args):
	'''
		Create a new disposable container which only purpose is to run attic.
		For this, we need to keep our current mounts and add those of the target
		container to /backup
	'''

	own_config = cl.inspect_container(os.environ['HOSTNAME'])

	# things like docker.sock and /repositories
	own_mounts = get_mounts(os.environ['HOSTNAME'])

	# attic need a cache to work correctly. if not mounted, then just append
	# /root/.cache/attic to the mount points.
	attic_cache = list(filter(lambda m: '/root/.cache/attic'.startswith(m['dst']), own_mounts))
	if len(attic_cache) == 0:
		own_mounts.append(dict(src='/root/.cache/attic', dst='/root/.cache/attic'))

	# the container's mount
	target_mounts = get_mounts(args.container, prefix='/backup')
	all_mounts = own_mounts + target_mounts

	print('\nRunning for {} with volumes :'.format(args.container))
	for m in target_mounts:
		print('   * {}'.format(m['dst'].replace('/backup', '')))
	print()

	# Create bindings
	mount_points = list(map(lambda v: v['dst'], all_mounts))
	binds = {m['src']: m['dst'] for m in all_mounts}

	container_id = cl.create_container(
		image=own_config['Image'],
		name='basement-child-{}'.format(int(time() * 1000)),
		command=sys.argv[1:],
		environment=dict(
			BASEMENT_IS_CHILD='true',
			# Since we can move the backups around without them being in the cache,
			# we want attic to run without complaining.
			ATTIC_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK='yes'
		),
		host_config=cl.create_host_config(binds=binds)
	)

	cl.start(container_id)

	# Stream the logs until the container is done
	logs = cl.logs(container_id, stream=True)
	for l in logs:
		sys.stdout.write(l.decode('utf-8'))

	cl.remove_container(container_id)

def backup(args):

	# If the environment has a BASEMENT_IS_CHILD variable set, it means
	# we are going to run attic. Otherwise, we should prepare the container
	# for backup.
	if not os.environ.get('BASEMENT_IS_CHILD', False):
		return rerun_with_mounts(args)

	containers = None
	if not args.no_stop:
		containers = get_linked_containers(args.container)
		# stop all of them

	backup_name = get_backup_name(args)
	repository = path.join('/repositories', backup_name + '.attic')

	archive_name = 'bs-{stamp}'.format(
		stamp=datetime.utcnow().isoformat()
	)

	# If the backup repository does not exist yet, init it
	if not path.isdir(repository):
		# fixme : maybe we should create a passphrase of sorts here ?
		# or at least allow the option
		run(['attic', 'init', repository])

	# Run the backup
	run([
		'attic',
		'create',
		'--stats',
		'{}::{}'.format(repository, archive_name),
		'.'
	], cwd='/backup')

	print('pruning repository')
	run([
		'attic',
		'prune',
		'{}'.format(repository),
		'--keep-daily',
		'14',
		'--keep-monthly',
		'3',
		'--keep-weekly',
		'4'
	])
	# Prune old archives

	if not args.no_stop:
		# restart all the linked containers
		pass


def restore(args):

	if not os.environ.get('BASEMENT_IS_CHILD', False):
		return rerun_with_mounts(args)


###################################################

parser = ArgumentParser()
parser.add_argument('-v', help='display more informations', action='store_true')

parent = ArgumentParser(add_help=False)
parent.add_argument('container', help='the name or id of the container to backup')
parent.add_argument('--no-stop', default=False, action='store_true', help='do not stop the container and those that use the same volumes')
parent.add_argument('--backup-name', help='name of the backup to use instead of the computed one')

subparsers = parser.add_subparsers(help='')

parser_backup = subparsers.add_parser('backup', help='backup a container', parents=[parent])
parser_backup.set_defaults(func=backup)

parser_restore = subparsers.add_parser('restore', help='restore a container from a specific archive', parents=[parent])
parser_restore.add_argument('archive', help='the archive to restore like [<backup_name>::]<archive>')
parser_restore.add_argument('--no-remove', default=False, action='store_true', help='do not delete everything in the target volumes prior to restoring its contents')
parser_restore.set_defaults(func=restore)

args = parser.parse_args()

try:
	args.func(args)
except errors.NotFound as e:
	print(e)
