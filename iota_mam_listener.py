import logging
import asyncio
import aiohttp
import json
import os

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import dump
from homeassistant.config import load_yaml_config_file

import voluptuous as vol

from homeassistant.core import callback
from homeassistant.helpers.typing import HomeAssistantType, ConfigType
from homeassistant.const import (CONF_HOST, CONF_PORT,
                                 EVENT_STATE_CHANGED, EVENT_SERVICE_REGISTERED)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = ['PyOTA==2.0.6', 'pyota[ccurl]', 'pyOpenSSL>=0.14']

_LOGGER = logging.getLogger(__name__)

EVENT_ACTION_TRIGGERED = 'iota_mam.action_triggered'

CONF_SECURE = 'secure'
CONF_LISTENERS = 'listeners'
CONF_ROOT = 'root'
CONF_MODE = 'mode'
CONF_SIDEKEY = 'sidekey'
CONF_NODE_PATH = 'node_path'

ATTR_ROOT = 'root'
ATTR_PAYLOAD = 'payload'
ATTR_NEXT_ROOT = 'next_root'
ATTR_MODE = 'mode'
ATTR_SIDEKEY = 'sidekey'
ATTR_BUNDLE = 'bundle'

DOMAIN = 'iota_mam_listener'

YAML_LISTENER_STATES = 'iota_mam_listener_states.yaml'

DEFAULT_SUBSCRIBED_EVENTS = [EVENT_STATE_CHANGED,
                             EVENT_SERVICE_REGISTERED]
DEFAULT_ENTITY_PREFIX = ''

LISTENERS_SCHEMA = vol.Schema({
    vol.Required(CONF_ROOT): cv.string,
    vol.Required(CONF_MODE): cv.string,
    vol.Optional(CONF_SIDEKEY): cv.string,
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.port,
        vol.Optional(CONF_SECURE, default=False): cv.boolean,
        vol.Required(CONF_LISTENERS): vol.All(cv.ensure_list,
                                              [LISTENERS_SCHEMA]),
        vol.Optional(CONF_NODE_PATH, default='node'): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)


def curl_hash(*keys):
    import iota

    key = []
    curl = iota.crypto.Curl()
    for k in keys:
        curl.absorb(iota.TryteString(k).as_trits())
    curl.squeeze(key)
    return iota.TryteString.from_trits(key)


async def async_setup(hass: HomeAssistantType, config: ConfigType):
    """Set up the iota_mam_listener component."""
    conf = config.get(DOMAIN)

    connection = IOTAWebsocketConnection(hass, conf)
    asyncio.ensure_future(connection.async_create())

    return True


class IOTAWebsocketConnection(object):
    """A Websocket connection to a iota-websocket-proxy."""

    def __init__(self, hass, conf):
        """Initialize the connection."""
        self._hass = hass
        self._host = conf.get(CONF_HOST)
        self._port = conf.get(CONF_PORT)
        self._secure = conf.get(CONF_SECURE)
        self._listener_conf = conf.get(CONF_LISTENERS)
        self._node_path = conf.get(CONF_NODE_PATH)

        self._listener_states = {}
        self._listener_ids = {}

        self.__next_id = 1

    @callback
    def _get_url(self):
        """Get url to connect to."""
        return '%s://%s:%s/ws' % (
            'wss' if self._secure else 'ws', self._host, self._port)

    async def async_create(self):
        path = self._hass.config.path(YAML_LISTENER_STATES)

        if os.path.isfile(path):
            try:
                self._listener_states = await self._hass.async_add_job(
                    load_yaml_config_file, path)
            except HomeAssistantError as err:
                _LOGGER.error("Unable to load %s: %s", path, str(err))
                return []

        for listener_conf in self._listener_conf:
            root = listener_conf.get(CONF_ROOT)
            mode = listener_conf.get(CONF_MODE)
            sidekey = listener_conf.get(CONF_SIDEKEY)
            if root not in self._listener_states or self._listener_states[root][ATTR_MODE] != mode or \
                    self._listener_states[root][ATTR_SIDEKEY] != sidekey:

                self._listener_states[root] = {
                    ATTR_ROOT: root,
                    ATTR_NEXT_ROOT: root,
                    ATTR_MODE: mode,
                    ATTR_SIDEKEY: sidekey
                }

        url = self._get_url()
        session = async_get_clientsession(self._hass)

        while True:
            try:
                _LOGGER.info('Connecting to %s', url)
                await self.async_connect(session, url)
            except aiohttp.client_exceptions.ClientError as err:
                _LOGGER.error(
                    'Could not connect to %s, retry in 10 seconds...', url)
                await asyncio.sleep(10)
            else:
                _LOGGER.info(
                    'Connected to home-assistant websocket at %s', url)
                break

    async def async_connect(self, session, url):
        import iota

        async with session.ws_connect(url) as ws:
            for listener in self._listener_states.values():
                await self.subscribe(ws, listener)

            while True:
                listener_id, listener, bundle_hash, data = await self.get_next_message(ws)

                payload_json = data['payload']
                payload_json = iota.TryteString(payload_json).encode()

                payload = json.loads(payload_json)

                self._hass.bus.fire(EVENT_ACTION_TRIGGERED, {
                    ATTR_ROOT: listener[ATTR_ROOT],
                    ATTR_BUNDLE: bundle_hash,
                    ATTR_PAYLOAD: payload
                })

                await self.unsubscribe(ws, listener_id)
                listener[ATTR_NEXT_ROOT] = data['next_root']
                await self.subscribe(ws, listener)

                # update iota_mam_listeners.yaml
                with open(self._hass.config.path(YAML_LISTENER_STATES), 'w') as out:
                    out.write(dump(self._listener_states))

    async def subscribe(self, ws, listener):
        address = listener[ATTR_NEXT_ROOT]
        if listener[ATTR_MODE] == 'private' or listener[ATTR_MODE] == 'restricted':
            address = str(curl_hash(address))

        _LOGGER.debug('Subscribing to address %s (looking for root %s)' % (address, listener[ATTR_NEXT_ROOT]))
        self._listener_ids[self.__next_id] = listener
        await ws.send_json({'id': self.__next_id, 'type': 'subscribe', 'addresses': [address]})
        self.__next_id += 1

    async def unsubscribe(self, ws, listener_id):
        _LOGGER.debug('Unsubscribing from root %s' % self._listener_ids[listener_id][ATTR_NEXT_ROOT])
        del self._listener_ids[listener_id]
        await ws.send_json({'id': listener_id, 'type': 'unsubscribe'})

    async def get_next_message(self, ws):
        import iota

        bundles = dict()
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                listener_id = data['id']
                if listener_id not in self._listener_ids:
                    continue
                listener = self._listener_ids[listener_id]

                tx = iota.Transaction.from_tryte_string(data['data'], data['hash'])

                _LOGGER.info('Received tx %s from bundle %s' % (tx.current_index, tx.bundle_hash))

                bundle_hash = str(tx.bundle_hash)
                if bundle_hash not in bundles:
                    bundles[bundle_hash] = [None] * (tx.last_index + 1)
                bundles[bundle_hash][tx.current_index] = str(tx.signature_message_fragment)

                if not None in bundles[bundle_hash]:
                    payload = ''.join(bundles[bundle_hash])
                    side_key_trytes = str(iota.TryteString.from_unicode(listener[ATTR_SIDEKEY]))

                    # Unfortunately MAM is not available in PyOTA - so we need to delegate this task to a
                    # simple Javascript helper :-(

                    cmd = ' '.join([self._node_path, os.sep.join([os.path.dirname(os.path.abspath(__file__)), 'helper',
                                                                  'decrypt.js']),
                                    payload, listener[ATTR_NEXT_ROOT], side_key_trytes])

                    _LOGGER.debug('calling to decrypt message: %s' % cmd)

                    proc = await asyncio.create_subprocess_shell(cmd,
                                                                 stdout=asyncio.subprocess.PIPE,
                                                                 stderr=asyncio.subprocess.PIPE)

                    stdout, stderr = await proc.communicate()

                    if stderr:
                        _LOGGER.error('Error when decrypting message!')
                        _LOGGER.error('Called command: %s' % cmd)
                        _LOGGER.error('Error: %s' % stderr)
                        continue

                    data = stdout.decode('utf8')
                    data = json.loads(data)

                    return listener_id, listener, bundle_hash, data

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise Exception()

