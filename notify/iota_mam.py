# Monkey-patch jinja2 template filters, so we can generate JSON values
from homeassistant.helpers import template

# This will result in a race condition - the loader might load
# e.g. an automation component before, which validates its yaml
# files before we enable the json filter
# I didn't find any way to fix the ordering.. but this is a ugly hack
# anyway, maybe try to get `| json` directly integrated in Home Assistant?
template.ENV.filters['json'] = lambda s: json.dumps(s, cls=JSONEncoder)

import logging
import asyncio
import shlex

import json
import os

from homeassistant.helpers.json import JSONEncoder
from homeassistant.util.yaml import dump
from homeassistant.config import load_yaml_config_file

import voluptuous as vol

from homeassistant.components.notify import (
    PLATFORM_SCHEMA, BaseNotificationService, ATTR_MESSAGE)
from homeassistant.const import (CONF_HOST, CONF_PORT)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'notify'

CONF_SECURE = 'secure'
CONF_LISTENERS = 'listeners'
CONF_SEED = 'seed'
CONF_MODE = 'mode'
CONF_SIDEKEY = 'sidekey'
CONF_NODE_PATH = 'node_path'

ATTR_ROOT = 'root'
ATTR_PAYLOAD = 'payload'
ATTR_NEXT_ROOT = 'next_root'
ATTR_MODE = 'mode'
ATTR_SIDEKEY = 'sidekey'
ATTR_BUNDLE = 'bundle'

YAML_MAM_STATES = 'iota_mam_notify_states.yaml'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PORT): cv.port,
    vol.Optional(CONF_SECURE, default=False): cv.boolean,
    vol.Required(CONF_SEED): cv.string,
    vol.Required(CONF_MODE): cv.string,
    vol.Optional(CONF_SIDEKEY, default=''): cv.string,
    vol.Optional(CONF_NODE_PATH, default='node'): cv.string,
})


async def async_get_service(hass, config, discovery_info=None):
    return IotaMamNotificationService(hass,
                                      config[CONF_HOST], config[CONF_PORT], config[CONF_SECURE],
                                      config[CONF_SEED], config[CONF_MODE], config[CONF_SIDEKEY],
                                      config[CONF_NODE_PATH])


class IotaMamNotificationService(BaseNotificationService):
    """Implement a notification service for IOTA MAM."""

    def __init__(self, hass, host, port, secure, seed, mode, sidekey, node_path):
        """Initialize the service."""
        import iota

        self._hass = hass
        self._node_path = node_path

        url = '%s://%s:%s' % (
            'https' if secure else 'http', host, port)
        self._api = iota.Iota(url)

        self._seed = seed
        mode = mode
        sidekey = sidekey

        self.yaml_path = hass.config.path(YAML_MAM_STATES)

        self._state = {}
        if os.path.isfile(self.yaml_path):
            conf = load_yaml_config_file(self.yaml_path)
            self._state = conf.get(seed, {})

        self._state["seed"] = seed
        self._state.setdefault("subscribed", [])

        channel = self._state.get("channel", {})
        channel["side_key"] = str(iota.TryteString.from_unicode(sidekey))
        channel["mode"] = mode
        channel.setdefault("next_root", None)
        channel.setdefault("security", 2)
        channel.setdefault("start", 0)
        channel.setdefault("count", 1)
        channel.setdefault("next_count", 1)
        channel.setdefault("index", 0)
        self._state["channel"] = channel

    async def async_send_message(self, message="", **kwargs):
        import iota

        data = kwargs.get('data', {})

        if message and data:
            data[ATTR_MESSAGE] = message
            data = json.dumps(data)
        elif message:
            data = message
        else:
            data = json.dumps(data)

        # Unfortunately MAM is not available in PyOTA - so we need to delegate this task to a
        # simple Javascript helper :-(

        data = str(iota.TryteString.from_unicode(data))
        cmd = ' '.join(
                [self._node_path, os.sep.join([os.path.dirname(os.path.abspath(__file__)), '..', 'helper', 'create.js']),
                 shlex.quote(json.dumps(self._state)), data])

        _LOGGER.debug('calling to encrypt message: %s' % cmd)

        proc = await asyncio.create_subprocess_shell(cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        stdout, stderr = await proc.communicate()

        if stderr:
            _LOGGER.error('Error when decrypting message!')
            _LOGGER.error('Called command: %s' % cmd)
            _LOGGER.error('Error: %s' % stderr)
            return

        mam_message = stdout.decode('utf8')
        mam_message = json.loads(mam_message)

        payload = mam_message['payload']
        root = mam_message['root']
        address = mam_message['address']

        _LOGGER.info('MAM root is: %s' % root)
        _LOGGER.info('attaching MAM message at address: %s' % address)

        await self._hass.async_add_executor_job(self.attach_message, address, payload)

        # Message was successfully published, we can now update the state
        self._state = mam_message['state']

        await self._hass.async_add_executor_job(self.update_state_file)

    def attach_message(self, address, payload):
        import iota

        trytes = self._api.prepare_transfer(transfers=[iota.ProposedTransaction(
            address=iota.Address(address),
            message=iota.TryteString(payload),
            value=0)])
        self._api.send_trytes(trytes["trytes"], depth=6, min_weight_magnitude=14)

    def update_state_file(self):
        yaml = {}
        if os.path.isfile(self.yaml_path):
            yaml = load_yaml_config_file(self.yaml_path)
        yaml[self._seed] = self._state
        with open(self.yaml_path, 'w') as out:
            out.write(dump(yaml))
