<!-- markdownlint-disable line-length -->

# Purpose

This snap helps user to set up test environments on both the DUT and client sides.

## Installation

Install ceqa-env-setup-tools from Snap store on client.

```bash
# install this snap with classic confinement
$ sudo snap install ce-qa-env-setup-tools --classic
```

## Test Environment Setup Tool

Setup up your test environment on DUT remotely, including install snaps and debian packages on DUT and creates system services.

### Usage

This utility perform actions defined in a configuration file to setup the test environment:

- Validate your configuration file

```bash
$ ceqa-env-setup-tools.test-env-setup validate -f $ENV_SETUP_YAML_FILE
# e.g.
$ ceqa-env-setup-tools.test-env-setup validate -f demo.yaml
```

- Setup test environment with SSH key in ssh-agent

```bash
# Enable SSH agent and add your private key on the client
# start ssh agent
$ ssh-agent
# add private key into agent
$ ssh-add $id_rsa_key
$ ceqa-env-setup-tools.test-env-setup setup -f $ENV_SETUP_YAML_FILE --remote-ip $DUT_IP --username $DUT_USERNAME --password $PASSPHRASE_ID_RSA
# e.g.
$ ceqa-env-setup-tools.test-env-setup setup -f demo.yaml --remote_ip 192.168.1.1 --username ubuntu --password password
```

- Setup test environment with SSH key file directly

```bash
$ ceqa-env-setup-tools.test-env-setup setup -f $ENV_SETUP_YAML_FILE --remote-ip $DUT_IP --username $DUT_USERNAME --password $PASSPHRASE_ID_RSA --private-key-file $PRIVATE_SSH_KEY_FILE
# e.g.
$ ceqa-env-setup-tools.test-env-setup setup -f demo.yaml --remote_ip 192.168.1.1 --username ubuntu --password password --private-key-file my_ssh_key_rsa
```

- Setup test environment with username and password

```bash
$ ceqa-env-setup-tools.test-env-setup setup -f $ENV_SETUP_YAML_FILE --remote-ip $DUT_IP --username $DUT_USERNAME --password $PASSWORD
# e.g.
$ ceqa-env-setup-tools.test-env-setup setup -f demo.yaml --remote_ip 192.168.1.1 --username ubuntu --password password
```

#### Notes

1. Configuration files in the current directory have a higher priority than others in outside directories.

### How to create a Platform-Specific config

#### Set Up VScode for Config File Modifications

- For YAML
Add the following to your user settings to properly format YAML files:

```json
"[yaml]": {
    "editor.insertSpaces": true,
    "editor.tabSize": 2,
    "editor.autoIndent": "advanced",
    "editor.formatOnType": true,
    "editor.codeLens": true,
    "editor.defaultFormatter": "redhat.vscode-yaml",
    "diffEditor.ignoreTrimWhitespace": false,
},
"yaml.validate": true,
"yaml.schemas": {
    "./test_env_setup/schema/env_setup_schema.json": "*/*_env_setup.yaml",
},
```

And then you can start creating your configuration using some helper tools, such as schema validation or templates in your editor, to ensure the configuration is correct and formatted properly.

#### Create and upload new configuration

Once you create your own configuration for a specific platform, follow the instructions to validate the files.
`ceqa-test-env-setup-tool.test-env-setup validate $your-setup-conf`

<!-- markdownlint-restore -->
