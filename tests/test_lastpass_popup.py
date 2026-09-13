import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import lastpass_popup  # noqa: E402


def hold_lock(path: str, delay: float, order: str) -> None:
    with (
        lastpass_popup.FileLock(Path(path), 1),
        Path(order).open("a", encoding="utf-8") as output,
    ):
        time.sleep(delay)
        output.write("first\n")


def take_lock(path: str, order: str) -> None:
    with (
        lastpass_popup.FileLock(Path(path), 1),
        Path(order).open("a", encoding="utf-8") as output,
    ):
        output.write("second\n")


class FakeSession(lastpass_popup.OmarchySession):
    def __init__(self, clients: list[dict[str, Any]], monitors: list[dict[str, Any]]) -> None:
        self._clients = [lastpass_popup.parse_client(client) for client in clients]
        self._monitors = [lastpass_popup.parse_monitor(monitor) for monitor in monitors]
        self.actions: list[tuple[object, ...]] = []

    def clients(self) -> list[lastpass_popup.ClientInfo]:
        return self._clients

    def monitors(self) -> list[lastpass_popup.MonitorInfo]:
        return self._monitors

    def float_window(self, address: str) -> None:
        self.actions.append(("float", address))

    def resize_window(self, address: str, width: int, height: int) -> None:
        self.actions.append(("resize", address, width, height))

    def move_window(self, address: str, x: int, y: int) -> None:
        self.actions.append(("move", address, x, y))

    def move_window_to_workspace(self, address: str, workspace: int) -> None:
        self.actions.append(("workspace", address, workspace))

    def shell_call(self, method: str, payload: str | None = None) -> None:
        self.actions.append(("shell", method, payload))

    def focus_window(self, address: str) -> None:
        self.actions.append(("focus", address))


class StoreSession(lastpass_popup.OmarchySession):
    def __init__(self, default_browser: str) -> None:
        self.default = default_browser
        self.launched: tuple[str, ...] | None = None
        self.notifications: list[tuple[str, bool]] = []

    def default_browser(self) -> str:
        return self.default

    def notify(self, message: str, critical: bool = False) -> None:
        self.notifications.append((message, critical))

    def launch_app(self, *args: str) -> None:
        self.launched = args


class FakePopup(lastpass_popup.LastPassPopup):
    def __init__(
        self,
        clients: list[dict[str, Any]],
        monitors: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        self.fake_session = FakeSession(clients, monitors or [])
        super().__init__(session=self.fake_session, **kwargs)


class HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.config = self.root / "config"
        self.bin = self.root / "bin"
        self.proc = self.root / "proc"
        self.bin.mkdir()
        self.proc.mkdir()

        for browser in (
            "chromium",
            "google-chrome-stable",
            "brave",
            "microsoft-edge-stable",
        ):
            path = self.bin / browser
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)

        for pid, executable in (
            (100, "/usr/bin/chromium"),
            (200, "/opt/brave.com/brave/brave"),
            (300, "/opt/microsoft/msedge/msedge"),
        ):
            process = self.proc / str(pid)
            process.mkdir()
            (process / "exe").symlink_to(executable)

        self.environment: Any = mock.patch.dict(
            os.environ,
            {
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "XDG_CONFIG_HOME": str(self.config),
                "LASTPASS_PROC_ROOT": str(self.proc),
                "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            },
        )
        self.environment.start()
        (self.root / "runtime").mkdir()

    def tearDown(self) -> None:
        self.environment.stop()
        self.tempdir.cleanup()

    def write_manifest(
        self,
        root: Path,
        extension_id: str,
        version: str,
        popup: str = "popup.html",
        profile: str = "Default",
    ) -> None:
        directory = root / profile / "Extensions" / extension_id / version
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "manifest.json").write_text(
            json.dumps({"version": version, "action": {"default_popup": popup}}),
            encoding="utf-8",
        )

    def test_validation_helpers(self) -> None:
        self.assertTrue(lastpass_popup.valid_popup("popup.html"))
        self.assertTrue(lastpass_popup.valid_popup("pages/popup.html"))
        self.assertFalse(lastpass_popup.valid_popup("../popup.html"))
        self.assertFalse(lastpass_popup.valid_popup("/popup.html"))
        self.assertEqual(lastpass_popup.valid_size("500", 420, 280, 1200), 500)
        self.assertEqual(lastpass_popup.valid_size("100", 420, 280, 1200), 420)

    def test_runtime_state_uses_private_plugin_directory(self) -> None:
        directory = lastpass_popup.runtime_directory()

        self.assertEqual(directory.parent, self.root / "runtime")
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(lastpass_popup.runtime_file("managed"), directory / "managed")

    def test_compositor_payloads_are_type_checked(self) -> None:
        client = lastpass_popup.parse_client(
            {
                "address": "0x1",
                "class": "popup",
                "pid": "not-a-pid",
                "monitor": 0,
                "floating": 1,
                "workspace": {"id": 2},
            }
        )
        monitor = lastpass_popup.parse_monitor(
            {"id": 0, "name": "TEST", "width": "wide", "height": 600, "scale": True}
        )

        self.assertEqual(
            client,
            {
                "address": "0x1",
                "class_": "popup",
                "monitor": 0,
                "workspace": {"id": 2},
            },
        )
        self.assertEqual(monitor, {"id": 0, "name": "TEST", "height": 600})

    def test_discovery_prefers_last_profile_and_newest_version(self) -> None:
        browser_root = self.config / "chromium"
        self.write_manifest(browser_root, lastpass_popup.CHROME_ID, "4.9.0")
        self.write_manifest(browser_root, lastpass_popup.CHROME_ID, "4.10.0")
        self.write_manifest(browser_root, lastpass_popup.CHROME_ID, "5.0.0", profile="Profile 2")
        (browser_root / "Local State").write_text(
            json.dumps({"profile": {"last_used": "Profile 2"}}), encoding="utf-8"
        )

        installation = lastpass_popup.LastPassPopup().discover("chromium")

        assert installation is not None
        self.assertIs(installation.adapter, lastpass_popup.CHROMIUM)
        self.assertEqual(installation.executable, "chromium")
        self.assertEqual(installation.profile, "Profile 2")
        self.assertEqual(installation.version, "5.0.0")

        (browser_root / "Local State").unlink()
        installation = lastpass_popup.LastPassPopup().discover("chromium")
        assert installation is not None
        self.assertEqual(installation.profile, "Default")
        self.assertEqual(installation.version, "4.10.0")

    def test_each_browser_adapter_discovers_its_extension(self) -> None:
        cases = (
            (lastpass_popup.CHROMIUM, self.config / "chromium", lastpass_popup.CHROME_ID),
            (lastpass_popup.CHROME, self.config / "google-chrome", lastpass_popup.CHROME_ID),
            (
                lastpass_popup.BRAVE,
                self.config / "BraveSoftware" / "Brave-Browser",
                lastpass_popup.CHROME_ID,
            ),
            (lastpass_popup.EDGE, self.config / "microsoft-edge", lastpass_popup.EDGE_ID),
        )
        for adapter, root, extension_id in cases:
            with self.subTest(browser=adapter.key):
                self.write_manifest(root, extension_id, "1.2.3")
                installation = lastpass_popup.LastPassPopup().discover(adapter.key)
                assert installation is not None
                self.assertIs(installation.adapter, adapter)
                self.assertEqual(installation.extension_id, extension_id)

    def test_edge_accepts_chrome_store_extension_id(self) -> None:
        root = self.config / "microsoft-edge"
        self.write_manifest(root, lastpass_popup.CHROME_ID, "2.0.0")

        installation = lastpass_popup.LastPassPopup().discover("edge")

        assert installation is not None
        self.assertIs(installation.adapter, lastpass_popup.EDGE)
        self.assertEqual(installation.extension_id, lastpass_popup.CHROME_ID)

    def test_default_browser_selects_matching_extension_store(self) -> None:
        session = StoreSession("microsoft-edge.desktop")
        popup = lastpass_popup.LastPassPopup(session=session)

        self.assertEqual(popup.open_store("auto"), 0)
        self.assertEqual(
            session.launched,
            ("microsoft-edge-stable", lastpass_popup.EDGE_STORE_URL),
        )

    def test_missing_browser_notification_names_requested_browser(self) -> None:
        session = StoreSession("")
        popup = lastpass_popup.LastPassPopup(session=session)

        with mock.patch.object(shutil, "which", return_value=None):
            self.assertEqual(popup.open_store("edge"), 1)

        self.assertEqual(session.notifications, [("Edge is not installed.", True)])

    def test_browser_specific_window_matching(self) -> None:
        clients = [
            {"address": "0x1", "pid": 100, "class": f"chrome-{lastpass_popup.CHROME_ID}-popup"},
            {"address": "0x2", "pid": 200, "class": f"chrome-{lastpass_popup.CHROME_ID}-popup"},
            {"address": "0x3", "pid": 300, "class": f"msedge-{lastpass_popup.EDGE_ID}-popup"},
            {"address": "0x4", "pid": 100, "class": "chrome-app.lastpass.com__vault_-Default"},
            {"address": "0x5", "pid": 300, "class": "msedge-app.lastpass.com__vault_-Default"},
        ]
        popup = FakePopup(clients)

        self.assertEqual(popup.matching_address(self.installation("chromium")), "0x1")
        self.assertEqual(popup.matching_address(self.installation("brave")), "0x2")
        self.assertEqual(popup.matching_address(self.installation("microsoft-edge-stable")), "0x3")
        self.assertEqual(popup.matching_address(self.installation("chromium"), vault=True), "0x4")
        self.assertEqual(
            popup.matching_address(self.installation("microsoft-edge-stable"), vault=True), "0x5"
        )

    def test_popup_size_is_clamped_to_monitor(self) -> None:
        clients = [{"address": "0x1", "monitor": 0, "floating": True}]
        monitors = [{"id": 0, "x": 0, "y": 0, "width": 800, "height": 600, "scale": 1}]
        popup = FakePopup(clients, monitors, width=1200, height=1400)

        popup.place_popup("0x1")

        self.assertEqual(popup.popup_width, 760)
        self.assertEqual(popup.popup_height, 486)
        self.assertEqual(
            popup.fake_session.actions,
            [("resize", "0x1", 760, 486), ("move", "0x1", 20, 60)],
        )

    def test_workspace_change_moves_and_refocuses_popup(self) -> None:
        clients = [
            {
                "address": "0x1",
                "monitor": 0,
                "floating": True,
                "workspace": {"id": 1},
            }
        ]
        monitors = [
            {"id": 0, "name": "TEST", "x": 0, "y": 0, "width": 800, "height": 900, "scale": 1}
        ]
        popup = FakePopup(clients, monitors)

        moved = popup._follow_workspace("0x1", self.installation("chromium"), 2)

        self.assertTrue(moved)
        self.assertEqual(popup.fake_session.actions[0], ("workspace", "0x1", 2))
        self.assertEqual(popup.fake_session.actions[-1], ("focus", "0x1"))

        popup.fake_session.actions.clear()
        popup.fake_session._clients[0]["workspace"] = {"id": 2}
        self.assertFalse(popup._follow_workspace("0x1", self.installation("chromium"), 2))
        self.assertEqual(popup.fake_session.actions, [])

    def test_omarchy_session_maps_typed_calls_to_commands(self) -> None:
        session = lastpass_popup.OmarchySession()
        completed = mock.Mock(returncode=0)

        with mock.patch.object(lastpass_popup, "run", return_value=completed) as command:
            session.resize_window("0xabc", 420, 650)
            session.shell_call("frameHide")
            session.set_focus_policy(0, 0)

        self.assertEqual(
            command.call_args_list[0],
            mock.call(
                [
                    "hyprctl",
                    "dispatch",
                    'hl.dsp.window.resize({ x = 420, y = 650, window = "address:0xabc" })',
                ],
                check=False,
            ),
        )
        self.assertEqual(
            command.call_args_list[1],
            mock.call(
                ["omarchy-shell", "-q", "joecastro.lastpass", "frameHide"],
                check=False,
            ),
        )
        self.assertIn("follow_mouse = 0", command.call_args_list[2].args[0][2])

    def test_control_lock_serializes_processes(self) -> None:
        path = self.root / "runtime" / "test.lock"
        order = self.root / "lock-order"
        first = multiprocessing.Process(target=hold_lock, args=(str(path), 0.2, str(order)))
        second = multiprocessing.Process(target=take_lock, args=(str(path), str(order)))
        first.start()
        time.sleep(0.05)
        second.start()
        first.join(2)
        second.join(2)

        self.assertEqual(first.exitcode, 0)
        self.assertEqual(second.exitcode, 0)
        self.assertEqual(order.read_text(encoding="utf-8"), "first\nsecond\n")

    @staticmethod
    def installation(browser: str) -> lastpass_popup.Installation:
        adapters = {
            "chromium": lastpass_popup.CHROMIUM,
            "brave": lastpass_popup.BRAVE,
            "microsoft-edge-stable": lastpass_popup.EDGE,
        }
        adapter = adapters[browser]
        extension_id = (
            lastpass_popup.EDGE_ID if adapter is lastpass_popup.EDGE else lastpass_popup.CHROME_ID
        )
        return lastpass_popup.Installation(
            adapter,
            browser,
            "Default",
            "popup.html",
            extension_id,
            "1.0",
        )


if __name__ == "__main__":
    unittest.main()
