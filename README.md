# envicorn

`envicorn` is a utility for setting up test environments on a remote DUT
(Device Under Test) over SSH.

It executes a declarative YAML or JSON action file to perform tasks such as:

- Installing snap packages
- Installing Debian packages
- Running remote shell commands
- Uploading files with SCP
- Creating and enabling systemd services
- Composing reusable templates

## Project Layout

- `test_env_setup_util/env_setup.py`: CLI entrypoint and orchestration logic
- `test_env_setup_util/libs/model.py`: Pydantic action schema
- `test_env_setup_util/libs/operator/`: action implementations
- `test_env_setup_util/demo/`: sample environment setup files
- `doc/USAGE.md`: additional usage notes

## Installation

### Option 1: Run from source (Poetry)

```bash
git clone git@github.com:canonical/envicorn.git
cd envicorn
poetry install
poetry run envicorn --help
```

### Option 2: Install the snap

```bash
sudo snap install ceqa-env-setup-tools --classic
ceqa-env-setup-tools.test-env-setup --help
```

## CLI Overview

The CLI provides three subcommands:

- `validate`: Validate config content against Pydantic schema
- `dump`: Resolve templates and Jinja variables into a final action file
- `setup`: Execute the resolved actions on a remote host over SSH

### `validate`

```bash
poetry run envicorn validate -f test_env_setup_util/demo/example_env_setup.yaml
```

### `dump`

```bash
poetry run envicorn dump \
  -f test_env_setup_util/demo/example_env_setup.yaml \
  -o dump.yaml
```

### `setup`

```bash
poetry run envicorn setup \
  -f test_env_setup_util/demo/example_env_setup.yaml \
  --remote-ip 192.168.1.10 \
  --username ubuntu \
  --password secret
```

For SSH key based auth, pass `--private-key-file <path>`.

## Configuration File Format

The root object must contain an `actions` list.

```yaml
actions:
  - action: install_snap
    name: test-snapd-tools-core22
    track: latest
    risk: edge
  - action: install_debian
    name: bluez
  - action: ssh_command
    command: |
      whoami
      date
```

### Supported actions

- `install_snap`
- `install_debian`
- `ssh_command`
- `scp_command`
- `create_service`
- `load_template`

Each action can also use:

- `ignore_error: true|false` (default `false`)
- `bypass_condition: <python-literal-string>`

If `bypass_condition` evaluates to `True`, that action is skipped.

## Templates and Variables

### `load_template`

- Loads another action file by name
- Resolves relative names by searching from the current root path
- Also searches parent `global_templates/` directories

Example from the demo config:

```yaml
- action: load_template
  name: get_initial_network_info.yaml
```

### Jinja variables

- `dump` and `setup` render actions with Jinja2
- Pass `-v/--variables-file` to provide variables from YAML or JSON
- Variable values like `$VAR` or `${VAR}` are expanded from the local
  environment before rendering

## Behavior Notes

- Validation happens before execution and again after variable rendering
- Execution stops at first failing action unless `ignore_error: true`
- `ssh_command` supports `continue_on_error: true` for shell-level behavior
- `create_service` uploads and enables services via `systemctl`

## Exit Codes

- `0`: success
- `10`: SSH auth failed
- `11`: SSH password/passphrase required
- `12`: invalid username/password
- `20`: action failed

## Build the Snap (classic confinement)

```bash
snapcraft
```

The snap app command is defined in `snap/snapcraft.yaml` as:

```text
ceqa-env-setup-tools.test-env-setup
```

## Related Documentation

- `doc/USAGE.md`
- `test_env_setup_util/demo/example_env_setup.yaml`
