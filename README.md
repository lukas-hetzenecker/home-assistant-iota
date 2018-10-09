# Introduction

Please look at my [blog post](https://medium.com/@lukashetzenecker/integrating-my-smart-home-into-the-tangle-d88ae03eb9bb) for full details of this project.

This repo contains the custom components for Home Assistant.

The following two are available:
* MAM Listener (iota_mam_listener). Listens to MAM streams on the Tangle.
* MAM publisher (notify.iota_mam). this can publish to public, private and restricted MAM streams.

# Installation

Make sure to install the custom components as described in the [Home Assistant documentation](https://developers.home-assistant.io/docs/en/creating_component_loading.html).

You also need to have a `node` binary. Install it, if you haven't any. If you're running Home Assistant in a container, you can download the binaries to the `custom_components` folder, and then set the `node_path` configuration option.


## Example for the MAM listener:

```yaml
iota_mam_listener:
 host: api.tingeltangle.de
 port: 443
 secure: true
 node_path: '/config/custom_components/node-v8.12.0-linux-x64/bin/node'
 listeners:
 - root: 'CTOQDBMSSGPZILEOQJUKQZXPMVTGIJFJKWWBKXYSKOHNUAABTGQLEXPIWHG9DICZQCVMHVKCTPNZONAYV'
   mode: 'restricted'
   sidekey: 'supersecret'
```

* host: Hostname of the **iota-websocket-proxy**
* port: Port of the proxy
* secure (optional): true for `wss`, false for `ws`
* node_path (optional): path to `node`
* root: MAM root
* mode: public, private or restricted
* sidekey: required for restricted mode

This component stores the MAM state in `iota_mam_listener_states.yaml`

## Example for the MAM publisher:

```yaml
notify:
  - platform: iota_mam
    name: iota_mam_public
    host: field.deviota.com
    port: 443
    secure: true
    seed: 'GZGEISSQIGQ9GYMMYKFOOKTMMYFCBULKIJLKJLBWUVHRJJDVFLTFNCIYCSDCZSIQPHXFX9DXQDKRZFFFC'
    mode: 'public'

  - platform: iota_mam
    name: iota_mam_private
    host: field.deviota.com
    port: 443
    secure: true
    seed: 'BZMNERQLOZKQOJNIVXBZWPZBRBTINVA9OOMYVDNS9UJIT9KMCULTIPLEBXCVFEVWTKOFLNSBAEKDNBKLQ'
    mode: 'private'

  - platform: iota_mam
    name: iota_mam_restricted
    host: field.deviota.com
    port: 443
    secure: true
    seed: 'EXFWDXXVEAAPVZYGPLZYRTQLXCYLHBAW9FJZDRJQLAIRFWHPCXCAPNPFNGYGAZOFMUFMINNDUJXSRAFOO'
    mode: 'restricted'
    sidekey: 'notreallysecret'
```

* host: Hostname of the **IOTA IRI API**
* port: Port of the IOTA IRI API
* secure (optional): true for `https`, false for `http`
* node_path (optional): path to `node`
* seed: IOTA Seed for MAM
* mode: public, private or restricted
* sidekey: required for restricted mode

You can enable debugging output via the following configuration:

```yaml
logger:
  default: info
  logs:
    custom_components.notify.iota_mam: debug
```
