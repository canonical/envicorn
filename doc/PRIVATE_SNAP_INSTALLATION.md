# Private Snap Installation Feature

## Overview

Envicorn now supports installing private snaps that require authentication. This feature uses the download-ack-install flow to securely install snaps from private or custom Snap stores.

## How It Works

When `store_auth` or `store_id` is specified in the snap installation action, envicorn automatically uses the secure download-ack-install flow:

1. **Download**: Downloads the snap with authentication credentials
2. **Acknowledge**: Validates the snap assertion (ensures authenticity)
3. **Install**: Installs from the local file (without `--dangerous` flag)
4. **Cleanup**: Automatically removes downloaded files

This approach maintains snap security while supporting private snap installation.

## Configuration

### New Fields for InstallSnapAction

Two new optional fields have been added to the `install_snap` action:

- **`store_auth`** (string, optional): Base64-encoded authentication credentials from `snapcraft export-login`
- **`store_id`** (string, optional): Custom Snap store ID

If `store_id` is not provided, envicorn will attempt to auto-detect it from the device using `snap model --assertion`.

### Examples

#### Example 1: Private Snap with Explicit Store ID

```yaml
actions:
  - action: install_snap
    name: my-private-snap
    track: 22
    risk: edge
    mode: devmode
    store_auth: "{{ SNAP_STORE_AUTH }}"
    store_id: my-custom-store-id
```

#### Example 2: Private Snap with Auto-Detected Store ID

```yaml
actions:
  - action: install_snap
    name: checkbox-frontend-private
    track: 22
    risk: stable
    store_auth: "{{ SNAP_STORE_AUTH }}"
    # store_id omitted - will be auto-detected from device
```

#### Example 3: Private Snap with Specific Revision

```yaml
actions:
  - action: install_snap
    name: private-snap-by-revision
    revision: "456"
    mode: classic
    store_auth: "{{ SNAP_STORE_AUTH }}"
```

#### Example 4: Public Snap (Existing Behavior)

```yaml
actions:
  - action: install_snap
    name: test-snapd-tools-core22
    track: latest
    risk: edge
    mode: devmode
    # No store_auth or store_id - uses direct install
```

## Usage Instructions

### Step 1: Export Snap Store Credentials

First, export your Snap Store login credentials using `snapcraft export-login`:

```bash
$ snapcraft export-login ~/snap-credentials.txt
```

This creates a file containing your Snap Store authentication token.

### Step 2: Set Environment Variable

Encode the credentials as base64 and set the `SNAP_STORE_AUTH` environment variable:

```bash
$ export SNAP_STORE_AUTH=$(cat ~/snap-credentials.txt | base64 -w 0)
```

### Step 3: (Optional) Set Custom Store ID

If you're using a custom store and don't want auto-detection:

```bash
$ export STORE_ID="my-custom-store"
```

### Step 4: Run Envicorn

Run envicorn with your configuration file that references the environment variables:

```bash
$ envicorn setup -f private_snap_config.yaml --remote-ip 192.168.1.1 --username ubuntu
```

## Security Considerations

1. **Never commit credentials**: Always use environment variables for `store_auth`
2. **Credentials are temporary**: The credentials file from `snapcraft export-login` has an expiration
3. **Automatic cleanup**: Downloaded snap files are automatically removed after installation
4. **Assertion validation**: Snaps are validated through their assertions, maintaining security

## Behavior

### Public Snaps

When neither `store_auth` nor `store_id` is provided, envicorn uses the traditional direct installation method:

- Checks if snap is already installed
- Uses `snap install` or `snap refresh` directly
- Faster for public snaps

### Private Snaps

When `store_auth` or `store_id` is provided, envicorn uses the download-ack-install flow:

- Downloads snap with authentication
- Validates with snap assertions
- Installs from local file
- Works for both private and public snaps

### Store ID Auto-Detection

If `store_auth` is provided but `store_id` is not, envicorn will attempt to auto-detect the store ID from the device using:

```bash
snap model --assertion
```

This extracts the `store:` field from the device's model assertion. If no custom store is configured on the device, the installation will proceed without a store ID (using the main Snap Store).

## Troubleshooting

### Authentication Errors

```
Failed to download snap: authentication failed
```

**Solution**: Verify your `SNAP_STORE_AUTH` is correctly set and not expired. Re-export credentials if needed.

### Missing Snap Assertions

```
Failed to acknowledge snap assertion
```

**Solution**: Ensure the snap exists in the specified channel/revision and you have access to it.

### Store ID Issues

```
Unable to determine store ID
```

**Solution**: Either:
- Explicitly provide `store_id` in your configuration
- Ensure the device has a valid snap model assertion with a store field

## Implementation Details

### Code Flow

The implementation follows this decision tree:

```
install_snap()
    ├─ Has store_auth or store_id?
    │   ├─ YES: Use _install_snap_via_download()
    │   │        ├─ Auto-detect store_id if not provided
    │   │        ├─ Download snap with auth
    │   │        ├─ Acknowledge assertion
    │   │        ├─ Install from local file
    │   │        └─ Cleanup
    │   │
    │   └─ NO: Use _install_snap_directly()
    │            ├─ Check if already installed
    │            └─ Direct snap install/refresh
    │
    └─ Execute post_commands if specified
```

### Files Modified

- **`test_env_setup_util/libs/model.py`**: Added `store_auth` and `store_id` fields to `InstallSnapAction`
- **`test_env_setup_util/libs/operator/snap.py`**: Implemented download-ack-install flow and store ID auto-detection

### Test Coverage

Comprehensive unit tests cover:
- Store ID auto-detection (success, failure, not found cases)
- Download-ack-install flow with various configurations
- Direct installation for public snaps
- Error handling and cleanup
- Post-command execution

Run tests with:
```bash
$ python3 -m unittest test_snap -v
```

## References

- Reference implementation: [canonical/certification-lab-ci-tools](https://github.com/canonical/certification-lab-ci-tools/blob/main/scriptlets/install_checkbox_snaps#L101-L113)
- Snap documentation: https://snapcraft.io/docs
- Snapcraft export-login: https://snapcraft.io/docs/snapcraft-export-login
