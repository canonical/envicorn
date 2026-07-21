"""
Tests for snap installation functionality.
This file demonstrates the private snap installation feature.
"""
import unittest
from unittest.mock import Mock, patch, call
from test_env_setup_util.libs.operator.snap import (
    install_snap,
    get_store_id_from_device,
    _install_snap_via_download,
    _install_snap_directly,
    get_snap_info,
    parse_snap_info,
)
from test_env_setup_util.libs.exceptions import SnapCommandError


class TestGetStoreIdFromDevice(unittest.TestCase):
    """Test automatic store ID detection from device."""
    
    def test_get_store_id_success(self):
        """Test successful store ID extraction."""
        session = Mock()
        session.launch_ssh_command.return_value = (
            0,
            "brand-id: canonical\nmodel: ubuntu-core-22-amd64\nstore: my-custom-store\n",
            ""
        )
        
        store_id = get_store_id_from_device(session)
        
        self.assertEqual(store_id, "my-custom-store")
        session.launch_ssh_command.assert_called_once_with("snap model --assertion")
    
    def test_get_store_id_not_found(self):
        """Test when no store ID is in the assertion."""
        session = Mock()
        session.launch_ssh_command.return_value = (
            0,
            "brand-id: canonical\nmodel: ubuntu-core-22-amd64\n",
            ""
        )
        
        store_id = get_store_id_from_device(session)
        
        self.assertIsNone(store_id)
    
    def test_get_store_id_command_fails(self):
        """Test when snap model command fails."""
        session = Mock()
        session.launch_ssh_command.return_value = (1, "", "error")
        
        store_id = get_store_id_from_device(session)
        
        self.assertIsNone(store_id)


class TestInstallSnapViaDownload(unittest.TestCase):
    """Test the download-ack-install flow for private snaps."""
    
    @patch('test_env_setup_util.libs.operator.snap.get_store_id_from_device')
    def test_install_with_auth_and_store_id(self, mock_get_store):
        """Test installation with both auth and store_id provided."""
        session = Mock()
        session.launch_ssh_command.return_value = (0, "", "")
        
        snap_data = {
            "name": "my-private-snap",
            "track": "22",
            "risk": "edge",
            "mode": "devmode",
            "store_auth": "base64encodedcreds",
            "store_id": "my-store"
        }
        
        result = _install_snap_via_download(session, snap_data, store_id="my-store")
        
        self.assertEqual(result, 0)
        # Should not auto-detect since store_id is provided
        mock_get_store.assert_not_called()
        
        # Verify download command includes auth
        download_call = session.launch_ssh_command.call_args_list[0]
        self.assertIn("UBUNTU_STORE_ID", download_call[0][0])
        self.assertIn("UBUNTU_STORE_AUTH", download_call[0][0])
        self.assertIn("snap download", download_call[0][0])
        
        # Verify ack command
        ack_call = session.launch_ssh_command.call_args_list[1]
        self.assertIn("sudo snap ack", ack_call[0][0])
        self.assertIn(".assert", ack_call[0][0])
        
        # Verify install command
        install_call = session.launch_ssh_command.call_args_list[2]
        self.assertIn("sudo snap install", install_call[0][0])
        self.assertIn(".snap", install_call[0][0])
        self.assertIn("--devmode", install_call[0][0])
        
        # Verify cleanup
        cleanup_call = session.launch_ssh_command.call_args_list[3]
        self.assertIn("rm -f", cleanup_call[0][0])
    
    @patch('test_env_setup_util.libs.operator.snap.get_store_id_from_device')
    def test_install_with_auth_auto_detect_store(self, mock_get_store):
        """Test installation with auth but auto-detected store_id."""
        session = Mock()
        session.launch_ssh_command.return_value = (0, "", "")
        mock_get_store.return_value = "detected-store"
        
        snap_data = {
            "name": "my-private-snap",
            "track": "latest",
            "risk": "stable",
            "store_auth": "base64encodedcreds"
        }
        
        result = _install_snap_via_download(session, snap_data)
        
        self.assertEqual(result, 0)
        # Should auto-detect store_id
        mock_get_store.assert_called_once_with(session)
        
        # Verify download command includes detected store (without quotes around value)
        download_call = session.launch_ssh_command.call_args_list[0]
        self.assertIn("UBUNTU_STORE_ID=detected-store", download_call[0][0])
    
    @patch('test_env_setup_util.libs.operator.snap.get_store_id_from_device')
    def test_install_with_revision(self, mock_get_store):
        """Test installation with specific revision."""
        session = Mock()
        session.launch_ssh_command.return_value = (0, "", "")
        mock_get_store.return_value = None
        
        snap_data = {
            "name": "test-snap",
            "revision": "123",
            "store_auth": "creds"
        }
        
        result = _install_snap_via_download(session, snap_data, store_id=None)
        
        self.assertEqual(result, 0)
        download_call = session.launch_ssh_command.call_args_list[0]
        self.assertIn("--revision=", download_call[0][0])
        self.assertIn("123", download_call[0][0])
    
    @patch('test_env_setup_util.libs.operator.snap.get_store_id_from_device')
    def test_install_with_branch(self, mock_get_store):
        """Test installation with channel branch."""
        session = Mock()
        session.launch_ssh_command.return_value = (0, "", "")
        mock_get_store.return_value = None
        
        snap_data = {
            "name": "test-snap",
            "track": "22",
            "risk": "edge",
            "branch": "hotfix",
            "store_auth": "creds"
        }
        
        result = _install_snap_via_download(session, snap_data, store_id=None)
        
        self.assertEqual(result, 0)
        download_call = session.launch_ssh_command.call_args_list[0]
        self.assertIn("--channel=", download_call[0][0])
        self.assertIn("22/edge/hotfix", download_call[0][0])
    
    def test_download_fails(self):
        """Test handling of download failure."""
        session = Mock()
        session.launch_ssh_command.side_effect = [
            (1, "", "download error"),  # Download fails
            (0, "", ""),  # Cleanup succeeds  
        ]
        
        snap_data = {
            "name": "test-snap",
            "track": "latest",
            "risk": "stable",
            "store_auth": "creds",
            "store_id": "test-store"  # Provide store_id to avoid auto-detect call
        }
        
        with self.assertRaises(SnapCommandError) as context:
            _install_snap_via_download(session, snap_data, store_id="test-store")
        
        self.assertIn("Failed to download", str(context.exception))
        # Cleanup should still be called
        self.assertEqual(session.launch_ssh_command.call_count, 2)


class TestInstallSnapDirectly(unittest.TestCase):
    """Test direct snap installation (public snaps)."""
    
    @patch('test_env_setup_util.libs.operator.snap.get_snap_info')
    def test_install_new_snap(self, mock_get_info):
        """Test installing a snap that's not yet installed."""
        session = Mock()
        session.launch_ssh_command.return_value = (0, "", "")
        mock_get_info.return_value = ("", [])  # Not installed
        
        snap_data = {
            "name": "test-snap",
            "track": "latest",
            "risk": "stable",
            "mode": "classic"
        }
        
        result = _install_snap_directly(session, snap_data)
        
        self.assertEqual(result, 0)
        install_call = session.launch_ssh_command.call_args_list[0]
        self.assertIn("sudo snap install", install_call[0][0])
        self.assertIn("--channel=latest/stable", install_call[0][0])
        self.assertIn("--classic", install_call[0][0])
    
    @patch('test_env_setup_util.libs.operator.snap.get_snap_info')
    def test_refresh_existing_snap(self, mock_get_info):
        """Test refreshing an already installed snap."""
        session = Mock()
        session.launch_ssh_command.return_value = (0, "", "")
        mock_get_info.return_value = ("123", ["latest/edge"])  # Already installed
        
        snap_data = {
            "name": "test-snap",
            "track": "latest",
            "risk": "stable"
        }
        
        result = _install_snap_directly(session, snap_data)
        
        self.assertEqual(result, 0)
        refresh_call = session.launch_ssh_command.call_args_list[0]
        self.assertIn("sudo snap refresh", refresh_call[0][0])
    
    @patch('test_env_setup_util.libs.operator.snap.get_snap_info')
    def test_skip_if_already_correct_channel(self, mock_get_info):
        """Test skipping installation if already on correct channel."""
        session = Mock()
        mock_get_info.return_value = ("123", ["latest/stable"])
        
        snap_data = {
            "name": "test-snap",
            "track": "latest",
            "risk": "stable"
        }
        
        result = _install_snap_directly(session, snap_data)
        
        self.assertEqual(result, 0)
        # Should not call install/refresh
        session.launch_ssh_command.assert_not_called()


class TestInstallSnap(unittest.TestCase):
    """Test the main install_snap function."""
    
    @patch('test_env_setup_util.libs.operator.snap.check_snap_utility')
    @patch('test_env_setup_util.libs.operator.snap._install_snap_via_download')
    def test_routes_to_download_with_auth(self, mock_download, mock_check):
        """Test that presence of store_auth routes to download method."""
        session = Mock()
        mock_download.return_value = 0
        
        snap_data = {
            "name": "private-snap",
            "track": "22",
            "risk": "edge",
            "store_auth": "credentials"
        }
        
        install_snap(session, snap_data)
        
        mock_check.assert_called_once_with(session)
        mock_download.assert_called_once_with(session, snap_data, None)
    
    @patch('test_env_setup_util.libs.operator.snap.check_snap_utility')
    @patch('test_env_setup_util.libs.operator.snap._install_snap_via_download')
    def test_routes_to_download_with_store_id(self, mock_download, mock_check):
        """Test that presence of store_id routes to download method."""
        session = Mock()
        mock_download.return_value = 0
        
        snap_data = {
            "name": "private-snap",
            "track": "22",
            "risk": "edge",
            "store_id": "custom-store"
        }
        
        install_snap(session, snap_data)
        
        mock_download.assert_called_once_with(session, snap_data, "custom-store")
    
    @patch('test_env_setup_util.libs.operator.snap.check_snap_utility')
    @patch('test_env_setup_util.libs.operator.snap._install_snap_directly')
    def test_routes_to_direct_without_auth(self, mock_direct, mock_check):
        """Test that absence of auth routes to direct method."""
        session = Mock()
        mock_direct.return_value = 0
        
        snap_data = {
            "name": "public-snap",
            "track": "latest",
            "risk": "stable"
        }
        
        install_snap(session, snap_data)
        
        mock_direct.assert_called_once_with(session, snap_data)
    
    @patch('test_env_setup_util.libs.operator.snap.check_snap_utility')
    @patch('test_env_setup_util.libs.operator.snap._install_snap_directly')
    def test_post_commands_executed(self, mock_direct, mock_check):
        """Test that post_commands are executed after successful install."""
        session = Mock()
        session.launch_ssh_command.return_value = (0, "", "")
        mock_direct.return_value = 0
        
        snap_data = {
            "name": "test-snap",
            "track": "latest",
            "risk": "stable",
            "post_commands": "snap list"
        }
        
        install_snap(session, snap_data)
        
        # Should call post_commands
        session.launch_ssh_command.assert_called_with("snap list")
    
    @patch('test_env_setup_util.libs.operator.snap.check_snap_utility')
    @patch('test_env_setup_util.libs.operator.snap._install_snap_directly')
    def test_post_commands_error_raises(self, mock_direct, mock_check):
        """Test that post_commands error raises SnapCommandError."""
        session = Mock()
        session.launch_ssh_command.return_value = (1, "", "error")
        mock_direct.return_value = 0
        
        snap_data = {
            "name": "test-snap",
            "track": "latest",
            "risk": "stable",
            "post_commands": "failing command"
        }
        
        with self.assertRaises(SnapCommandError):
            install_snap(session, snap_data)


class TestParseSnapInfo(unittest.TestCase):
    """Test snap info parsing."""
    
    def test_parse_installed_snap(self):
        """Test parsing info for an installed snap."""
        snap_info = """
name:      test-snap
summary:   Test snap
publisher: Canonical
store-url: https://snapcraft.io/test-snap
license:   GPL-3.0
description: |
  A test snap
snap-id:      abc123
tracking:     latest/stable
refresh-date: today
installed:    1.0  (42) 100MB -
channels:
  latest/stable:    1.0  (42) 100MB -
  latest/candidate: 1.0  (42) 100MB -
  latest/beta:      1.1  (43) 100MB -
  latest/edge:      1.2  (44) 100MB -
"""
        
        rev, tracks = parse_snap_info(snap_info)
        
        self.assertEqual(rev, "42")
        self.assertIn("latest/stable", tracks)
        self.assertIn("latest/candidate", tracks)
    
    def test_parse_not_installed(self):
        """Test parsing info for a snap that's not installed."""
        snap_info = """
name:      test-snap
summary:   Test snap
channels:
  latest/stable:    1.0  (42) 100MB -
"""
        
        rev, tracks = parse_snap_info(snap_info)
        
        self.assertEqual(rev, "")
        self.assertEqual(tracks, [])


if __name__ == '__main__':
    unittest.main()
