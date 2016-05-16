#!/usr/bin/python3

import pprint
pp = pprint.PrettyPrinter(indent=2, compact=True)

import os
import sys
import re
from datetime import datetime
from time import time
from os import path
from docker import Client, errors
from argparse import ArgumentParser
from subprocess import run, PIPE, DEVNULL

from attic.repository import Repository

cl = Client(base_url='unix://var/run/docker.sock', version='auto')

DEFAULT_PREFIX = 'bs'

DIR_BACKUPS = '/backup'
DIR_REPOSITORIES = '/repositories'

ATTIC_ENV = dict(
	# Since we can move the backups around without them being in the cache,
	# we want attic to run without complaining.
	ATTIC_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK='yes',
	# We might want to move the repositories around
	ATTIC_RELOCATED_REPO_ACCESS_IS_OK='yes'
)

os.environ.update(**ATTIC_ENV)


################################################################
#
#				Color support
#
################################################################

fg = dict(
	black = '\033[30m',
	red = '\033[31m',
	green = '\033[32m',
	yellow = '\033[33m',
	blue = '\033[33m',
	magenta = '\033[33m',
	cyan = '\033[33m',
	white = '\033[37m',
	reset = '\033[0m',
	bold = '\033[1m'
)
is_a_tty = sys.stdout.isatty()

def write(str):
	str = re.sub(r'%(?P<color>\w+)%', lambda m: fg[m.group('color')] if is_a_tty else '', str)
	sys.stdout.write(str + '\n')

################################################################
#
#				Helpers and decorators
#
################################################################


class BasementException(Exception):
	pass

def attic(*a, **k):
	suppl = []
	# if args.passphrase:
	# 	suppl += ['-e', args.passphrase]
	return run(['attic'] + list(a) + suppl, **k)

def get_linked_containers(cont):
	'''
		Get the list of all the *running* containers using the volumes of `cont`.

		It finds them simply by looking at their mount points and seeing if they're running.
	'''

	mounts = map(lambda m: m['Source'], cl.inspect_container(cont)['Mounts'])

def get_binds(cont, prefix=''):
	'''
		Get all the bound volume the given container has access to
		and return their destination prefixed by `prefix`

		The prefix is used generally with the DIR_BACKUP directory for the
		target container.
	'''
	info = cl.inspect_container(cont)
	if 'Mounts' in info:
		return ['{}:{}{}'.format(m['Source'], prefix, m['Destination']) for m in info['Mounts']]
	else:
		return ['{}:{}{}'.format(src, prefix, dst) for dst, src in info['Volumes'].items()]

def rerun_with_mounts(args):
	'''
		Create a new disposable container which only purpose is to run attic.
		For this, we need to keep our current mounts and add those of the target
		container to /backup
	'''

	own_config = cl.inspect_container(os.environ['HOSTNAME'])

	# things like docker.sock and /repositories
	own_binds = get_binds(os.environ['HOSTNAME'])

	own_binds.append('/root/.cache/attic:/root/.cache/attic')
	# This is so our backup timestamps reflect our current timezone
	own_binds.append('/etc/timezone:/etc/timezone')
	own_binds.append('/etc/localtime:/etc/localtime')

	# the container's mount
	target_binds = get_binds(args.container, prefix='/backup')

	all_binds = own_binds + target_binds

	write('\nRunning command for container %cyan%{}%reset%'.format(args.container))
	for b in target_binds:
		write('   %bold%%green%*%reset% {}'.format(b))
	print()

	volumes = list(map(
		lambda b: b.split(':')[1],
		all_binds
	))

	container_id = cl.create_container(
		image=own_config['Image'],
		name='basement-child-{}'.format(int(time() * 1000)),
		command=sys.argv[1:],
		environment=dict(BASEMENT_IS_CHILD='true', **ATTIC_ENV),
		volumes=volumes,
		host_config=cl.create_host_config(binds=all_binds)
	)

	cl.start(container_id)

	# Stream the logs until the container is done
	logs = cl.logs(container_id, stream=True)
	for l in logs:
		sys.stdout.write(l.decode('utf-8'))

	cl.remove_container(container_id)

def ensure_all_stopped(func):
	'''
		Decorator that ensures that all affected containers are stopped
		before backuping or restoring
	'''
	def wrapper(args):
		containers = None

		if not args.no_stop:
			containers = get_linked_containers(args.container)

		# perform backup/restore
		res = func(args)

		if not args.no_stop:
			for c in containers:
				print('restarting container {}'.format(c))
				cl.start(c)

	return wrapper

def ensure_mounted(func):
	'''
		Simple decorator to ensure that the function being called is being
		run in a child.
	'''

	def wrapper(args, *a, **kw):
		# If the environment has a BASEMENT_IS_CHILD variable set, it means
		# we are going to run attic. Otherwise, we should prepare the container
		# for backup.
		if not os.environ.get('BASEMENT_IS_CHILD', False):
			return rerun_with_mounts(args)
		return func(args, *a, **kw)

	return wrapper

def handle_args(func):
	'''
		Parse the arguments to set up some default values, such as the repository
		and backup_name
	'''
	def wrapper(args):

		target_infos = cl.inspect_container(args.container)
		target_labels = target_infos['Config']['Labels']
		if not target_labels: target_labels = dict()

		if not args.backup_name:

			# give a name to the backup, or just infer one from the container's name and id
			args.backup_name = target_labels.get('basement.backup-name', '{}-{}'.format(args.container, target_infos['Id'][:8]))

		args.repository = path.join(DIR_REPOSITORIES, args.backup_name + '.attic')
		write('Using repository %green%{}%reset%'.format(args.backup_name))

		stamp = '{0:%Y-%m-%d@%H.%M.%S}'.format(datetime.now())
		if not args.prefix:
			args.prefix = target_labels.get('basement.prefix', DEFAULT_PREFIX)
		if hasattr(args, 'archive') and not args.archive:
			args.archive = '{}_{}'.format(getattr(args, 'prefix', 'bs'), stamp)
		if hasattr(args, 'archive'):
			args.full_archive = '{}::{}'.format(args.repository, args.archive)

		return func(args)

	return wrapper

################################################################
#
#				Command implementation
#
################################################################

@ensure_mounted
@handle_args
def cmd_backup(args):
	'''
		Backup an archive
	'''

	# If the backup repository does not exist yet, init it
	if not path.isdir(args.repository):
		# fixme : maybe we should create a passphrase of sorts here ?
		# or at least allow the option
		attic('init', args.repository)

	if not path.isdir(DIR_BACKUPS):
		write('%yellow%/!\\ This container has no volumes to back up%reset%')
		return

	# Run the backup
	attic('create', '--stats', args.full_archive, '.',
		cwd=DIR_BACKUPS
	)

@handle_args
def cmd_prune(args):
	'''
		attic prune, with options coalesced from the command line as well
		as the basement labels.
	'''

	attic('prune', args.repository, *args.prune_params.split())

@handle_args
def cmd_list(args):
	'''
		attic list
	'''

	attic('list', args.repository)

@handle_args
def cmd_delete(args):
	attic('delete',	args.full_archive)

@ensure_mounted
@handle_args
def cmd_restore(args):
	'''
		Restore a given archive into all the container's volumes.
	'''

	print('\nrestoring {} for {}\n'.format(args.archive, args.container))

	# Ensure that the repository exists
	if not path.isdir(args.repository):
		raise BasementException('no backup to restore from')

	# Ensure that the *archive* exists
	if run(
		['attic', 'info', '{}::{}'.format(args.repository, args.archive)],
		stdout=DEVNULL,
		stderr=DEVNULL
	).returncode != 0:
		raise BasementException('archive {} does not exist for this backup'.format(args.archive))

	if not args.no_remove:
		# Delete everything in the target mounts to prepare for a clean restore.
		mounts = map(lambda m: m.split(':')[1], get_binds(args.container))
		for m in mounts:
			# Only empty directories, as file volumes will be overwritten.
			if path.isdir(m):
				# print('rm -rf {pth}/* {pth}/.*'.format(pth=m))
				run('rm -rf {pth}/* {pth}/.* 2>/dev/null'.format(pth=m), shell=True)

	run([
		'attic',
		'extract',
		'{}::{}'.format(args.repository, args.archive)
	], cwd=DIR_BACKUPS)


def cmd_help(args):
	'''
		Show The help
	'''
	parser.parse_args(['--help'])

################################################################
################################################################
################################################################


################################################################
#
#				Argument Parser
#
################################################################

parser = ArgumentParser(prog='basement')
parser.add_argument('-v', help='display more informations', action='store_true')
parser.set_defaults(func=cmd_help)

parent = ArgumentParser(add_help=False)
parent.add_argument('container', help='the name or id of the container to backup')
parent.add_argument('--no-stop', default=False, action='store_true', help='do not stop the container and those that use the same volumes')
parent.add_argument('--backup-name', help='name of the backup to use instead of the computed one')
parent.add_argument('--passphrase', '-p', help='passphrase for the archive')
parent.add_argument('--prefix', help='prefix that applies on archive names and prunes')

subparsers = parser.add_subparsers(help='')

_backup = subparsers.add_parser('backup', help='backup a container', parents=[parent])
_backup.add_argument('archive', nargs='?', help='name of the archive')
_backup.set_defaults(func=cmd_backup)

_delete = subparsers.add_parser('delete', help='remove an archive', parents=[parent])
_delete.add_argument('archive', help='name of the archive')
_delete.set_defaults(func=cmd_delete)

_restore = subparsers.add_parser('restore',
	help='restore a container from a specific archive',
	parents=[parent]
)

_restore.add_argument('archive', help='the archive to restore (use list to see available ones)')
_restore.add_argument('--no-remove', default=False, action='store_true', help='do not delete everything in the target volumes prior to restoring its contents')
_restore.set_defaults(func=cmd_restore)

_prune = subparsers.add_parser('prune',
	help='prune a repository',
	parents=[parent]
)
_prune.add_argument('prune_params', help='attic prune params')
_prune.set_defaults(func=cmd_prune)

_list = subparsers.add_parser('list', help='list the archives available for a container', parents=[parent])
_list.set_defaults(func=cmd_list)

args = parser.parse_args()

try:
	args.func(args)
except errors.NotFound as e:
	print(e)
except BasementException as e:
	print(e)
