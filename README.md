# Cosmo

Cosmo is another fairy that converting Netbox data into input data for our templating solution.
The output is quite specific to our setup and automation stack, so consider it not a solution, more an inspiration.

## Output

We generate a file for each device - configured in cosmo.yaml - with our needed values.
Also, we generate a device manifest with values which may be interesting for all devices.

### Device Values

This contains multiple variables, which are going to be included in our Ansible solution.
Our Ansible playbook merges the generated values with the group variables and host variables to be able to do
overrides and additional, very specific config. We add e.g. ISIS addresses manually, because we haven't found a good representation in
Netbox yet.

### Device Manifest

TBD.

## Getting started

### Setup

If you are using Nix as a package manager you can start right away using the included `flake.nix` file.

For everyone else:

- Install Python3 packages listed in `requirements.txt`
    - `pip3 install -r requirements.txt`

### Usage

#### Configuration File

cosmo needs a `cosmo.yml` to make sure that it only fetches the correct devices.
`cosmo.example.yaml` provides an example configuration.

#### Environment Variables

You need to specify the Netbox instance, which should be used. Also, you need to provide an API token.
Make sure, that this API token is only eligible to read from Netbox, we do not need write access.
An API token can be obtained in your Netbox instance: `https://$URL/user/api-tokens/`

```shell
export NETBOX_URL=https://your-netbox.example.com
export NETBOX_API_TOKEN=abc123
```

#### Generating Variables

Cosmo can be used by simply calling the following command to regenerate all files in `machines`.
Note: **It will only consider devices listed in `cosmo.yaml`**

Note: We use some additional plugins in Netbox. We discover the Netbox version and installed plugins
automagically and adapt accordingly, e.g. do not generate ip-pools and static routes, if there are no plugins for those.

```shell
$ cosmo

Fetching information from Netbox, make sure VPN is enabled on your system.
Info: Generating router1
Info: Generating router2
```

##### Limit Mode

We are also able to regenerate sessions/filters for one router only. This can be used, if no full rollout is neccessary.
You can add a list of hosts that should be generated, calling --limit multiple times or adding multiple hostnames split
by comma. If this list is omitted, the full config is generated.

```
cosmo --limit=router2
```

## Authors

+ Ember Keske
+ Johann Wagner
+ Fiona Weber
+ Lou Lecrivain

## License

See `LICENSE.md`
