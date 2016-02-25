import os
import getpass
import json
import subprocess
import shutil
import socket
from distutils.spawn import find_executable
from jinja2 import Environment, PackageLoader
from .utils import get_sites, get_config, update_config, get_redis_version

env = Environment(loader=PackageLoader('bench', 'templates'), trim_blocks=True)

def write_config_file(bench, file_name, config):
	config_path = os.path.join(bench, 'config')
	file_path = os.path.join(config_path, file_name)
	number = (len([path for path in os.listdir(config_path) if path.startswith(file_name)]) -1 ) or ''
	if number:
		number = '.' + str(number)
	if os.path.exists(file_path):
		shutil.move(file_path, file_path + '.save' + number)

	with open(file_path, 'wb') as f:
		f.write(config)

def generate_supervisor_config(bench='.', user=None):
	from .app import get_current_frappe_version
	template = env.get_template('supervisor.conf')
	bench_dir = os.path.abspath(bench)
	sites_dir = os.path.join(bench_dir, "sites")
	sites = get_sites(bench=bench)
	if not user:
		user = getpass.getuser()
	config = get_config(bench=bench)

	config = template.render(**{
		"bench_dir": bench_dir,
		"sites_dir": sites_dir,
		"user": user,
		"http_timeout": config.get("http_timeout", 120),
		"redis_server": find_executable('redis-server'),
		"node": find_executable('node') or find_executable('nodejs'),
		"redis_cache_config": os.path.join(bench_dir, 'config', 'redis_cache.conf'),
		"redis_async_broker_config": os.path.join(bench_dir, 'config', 'redis_async_broker.conf'),
		"frappe_version": get_current_frappe_version(),
		"webserver_port": config.get('webserver_port'),
		"n_workers": config.get('max_workers')
	})
	write_config_file(bench, 'supervisor.conf', config)
	update_config({'restart_supervisor_on_update': True})

def get_site_config(site, bench='.'):
	with open(os.path.join(bench, 'sites', site, 'site_config.json')) as f:
		return json.load(f)

def generate_common_site_config(bench='.'):
	'''Generates the default common_site_config.json while a new bench is created'''
	config = get_config(bench=bench)
	
	celery_broker_port = config.get('redis_celery_broker_port', '11311')
	celery_broker = 'redis://localhost:{0}'.format(celery_broker_port)

	async_redis_server_port = config.get('redis_async_broker_port', '12311')
	async_redis_server = 'redis://localhost:{0}'.format(async_redis_server_port)

	cache_redis_server_port = config.get('redis_cache_port', '13311')
	cache_redis_server = 'redis://localhost:{0}'.format(cache_redis_server_port)

	default_common_site_config = {
		"celery_broker" : celery_broker,
		"async_redis_server": async_redis_server,
		"cache_redis_server": cache_redis_server
	}

	#TODO Optionally we need to add the host or domain name in case dns_multitenant is false

	with open(os.path.join(bench, 'sites', 'common_site_config.json'), 'wb') as f:
		json.dump(default_common_site_config, f, indent=1, sort_keys=True)

def get_sites_with_config(bench='.'):
	sites = get_sites(bench=bench)
	ret = []
	for site in sites:
		site_config = get_site_config(site, bench=bench)
		ret.append({
			"name": site,
			"port": site_config.get('nginx_port'),
			"ssl_certificate": site_config.get('ssl_certificate'),
			"ssl_certificate_key": site_config.get('ssl_certificate_key')
		})
	return ret

def generate_nginx_config(bench='.'):
	template = env.get_template('nginx.conf')
	bench_dir = os.path.abspath(bench)
	sites_dir = os.path.join(bench_dir, "sites")
	sites = get_sites_with_config(bench=bench)
	user = getpass.getuser()
	config = get_config(bench)

	if config.get('serve_default_site'):
		try:
			with open("sites/currentsite.txt") as f:
				default_site = {'name': f.read().strip()}
		except IOError:
			default_site = None
	else:
		default_site = None

	config = template.render(**{
		"sites_dir": sites_dir,
		"http_timeout": config.get("http_timeout", 120),
		"default_site": default_site,
		"dns_multitenant": config.get('dns_multitenant'),
		"sites": sites
	})
	write_config_file(bench, 'nginx.conf', config)

def generate_redis_celery_broker_config(bench='.'):
	"""Redis that is used for queueing celery tasks"""
	_generate_redis_config(
		template_name='redis_celery_broker.conf',
		context={
			"port": get_config(bench).get('redis_celery_broker_port', '11311'),
			"bench_path": os.path.abspath(bench),
		},
		bench=bench
	)

def generate_redis_async_broker_config(bench='.'):
	"""Redis that is used to do pub/sub"""
	_generate_redis_config(
		template_name='redis_async_broker.conf',
		context={
			"port": get_config(bench).get('redis_async_broker_port', '12311'),
		},
		bench=bench
	)

def generate_redis_cache_config(bench='.'):
	"""Redis that is used and optimized for caching"""
	config = get_config(bench=bench)

	_generate_redis_config(
		template_name='redis_cache.conf',
		context={
			"maxmemory": config.get('cache_maxmemory', '50'),
			"port": config.get('redis_cache_port', '13311'),
			"redis_version": get_redis_version(),
		},
		bench=bench
	)

def _generate_redis_config(template_name, context, bench):
	template = env.get_template(template_name)

	if "process_files_path" not in context:
		context["process_files_path"] = os.path.abspath(os.path.join(bench, "config", "files"))

	redis_config = template.render(**context)
	write_config_file(bench, template_name, redis_config)
