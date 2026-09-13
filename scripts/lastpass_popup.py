#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, TypedDict, cast

CHROME_ID = "hdokiejnpimakedhajhdlcegeplioahd"
EDGE_ID = "bbcinlkgjjkejfdpemiealijmmooekmp"
VAULT_URL = "https://app.lastpass.com/vault/"
CHROME_STORE_URL = f"https://chromewebstore.google.com/detail/lastpass-free-password-ma/{CHROME_ID}"
EDGE_STORE_URL = f"https://microsoftedge.microsoft.com/addons/detail/{EDGE_ID}"
PROJECT_URL = "https://github.com/joecastro/omarchy-lastpass-plugin"
POPUP_TOP, POPUP_RIGHT, FRAME_HEIGHT, POPUP_BOTTOM = 60, 20, 34, 20
DEFAULT_WIDTH, DEFAULT_HEIGHT = 420, 650
SCRIPT_PATH = Path(__file__).resolve()
PLUGIN_DIR = SCRIPT_PATH.parent.parent


@dataclass(frozen=True)
class BrowserAdapter:
    key: str
    label: str
    executables: tuple[str, ...]
    config_parts: tuple[str, ...]
    extension_ids: tuple[str, ...]
    process_names: tuple[str, ...]
    process_prefixes: tuple[str, ...]
    window_scheme: str
    store_url: str
    desktop_names: tuple[str, ...]

    def installed_executable(self) -> str | None:
        return next((name for name in self.executables if shutil.which(name)), None)

    def config_root(self, config_home: Path) -> Path:
        return config_home.joinpath(*self.config_parts)

    def matches_process(self, process_name: str) -> bool:
        return process_name in self.process_names or any(
            process_name.startswith(prefix) for prefix in self.process_prefixes
        )

    def popup_class_prefix(self, extension_id: str) -> str:
        return f"{self.window_scheme}-{extension_id}"

    def vault_class_prefix(self) -> str:
        return f"{self.window_scheme}-app.lastpass.com__vault_"

    def matches_desktop(self, desktop: str) -> bool:
        return any(name in desktop for name in self.desktop_names)


CHROMIUM = BrowserAdapter(
    key="chromium",
    label="Chromium",
    executables=("chromium",),
    config_parts=("chromium",),
    extension_ids=(CHROME_ID,),
    process_names=("chromium",),
    process_prefixes=(),
    window_scheme="chrome",
    store_url=CHROME_STORE_URL,
    desktop_names=("chromium",),
)
CHROME = BrowserAdapter(
    key="chrome",
    label="Chrome",
    executables=("google-chrome-stable", "google-chrome"),
    config_parts=("google-chrome",),
    extension_ids=(CHROME_ID,),
    process_names=("chrome",),
    process_prefixes=("google-chrome",),
    window_scheme="chrome",
    store_url=CHROME_STORE_URL,
    desktop_names=("google-chrome",),
)
BRAVE = BrowserAdapter(
    key="brave",
    label="Brave",
    executables=("brave", "brave-browser"),
    config_parts=("BraveSoftware", "Brave-Browser"),
    extension_ids=(CHROME_ID,),
    process_names=("brave", "brave-browser"),
    process_prefixes=(),
    window_scheme="chrome",
    store_url=CHROME_STORE_URL,
    desktop_names=("brave",),
)
EDGE = BrowserAdapter(
    key="edge",
    label="Edge",
    executables=("microsoft-edge-stable",),
    config_parts=("microsoft-edge",),
    extension_ids=(EDGE_ID, CHROME_ID),
    process_names=("msedge",),
    process_prefixes=("microsoft-edge",),
    window_scheme="msedge",
    store_url=EDGE_STORE_URL,
    desktop_names=("microsoft-edge",),
)
BROWSERS = (CHROMIUM, CHROME, BRAVE, EDGE)
BROWSER_BY_KEY = {browser.key: browser for browser in BROWSERS}


@dataclass(frozen=True)
class Installation:
    adapter: BrowserAdapter
    executable: str
    profile: str
    popup: str
    extension_id: str
    version: str


class WorkspaceInfo(TypedDict, total=False):
    id: int


class ClientInfo(TypedDict, total=False):
    address: str
    class_: str
    pid: int
    monitor: int
    floating: bool
    workspace: WorkspaceInfo


class MonitorInfo(TypedDict, total=False):
    id: int
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: int | float


def run(
    args: Iterable[str], *, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )


def run_json(args: Iterable[str]) -> object:
    return cast(object, json.loads(run(args, capture=True).stdout))


def run_json_object(args: Iterable[str]) -> dict[str, Any]:
    command = tuple(args)
    value = run_json(command)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"expected a JSON object from {command[0] if command else 'command'}")
    return cast(dict[str, Any], value)


def run_json_objects(args: Iterable[str]) -> list[dict[str, Any]]:
    command = tuple(args)
    value = run_json(command)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"expected a JSON object list from {command[0] if command else 'command'}")
    return cast(list[dict[str, Any]], value)


def parse_client(value: dict[str, Any]) -> ClientInfo:
    client = ClientInfo()
    address = value.get("address")
    if isinstance(address, str):
        client["address"] = address
    window_class = value.get("class")
    if isinstance(window_class, str):
        client["class_"] = window_class
    pid = value.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool):
        client["pid"] = pid
    monitor = value.get("monitor")
    if isinstance(monitor, int) and not isinstance(monitor, bool):
        client["monitor"] = monitor
    if isinstance(value.get("floating"), bool):
        client["floating"] = value["floating"]
    workspace = value.get("workspace")
    if isinstance(workspace, dict):
        workspace_id = workspace.get("id")
        if isinstance(workspace_id, int) and not isinstance(workspace_id, bool):
            client["workspace"] = {"id": workspace_id}
    return client


def parse_monitor(value: dict[str, Any]) -> MonitorInfo:
    monitor = MonitorInfo()
    monitor_id = value.get("id")
    if isinstance(monitor_id, int) and not isinstance(monitor_id, bool):
        monitor["id"] = monitor_id
    x = value.get("x")
    if isinstance(x, int) and not isinstance(x, bool):
        monitor["x"] = x
    y = value.get("y")
    if isinstance(y, int) and not isinstance(y, bool):
        monitor["y"] = y
    width = value.get("width")
    if isinstance(width, int) and not isinstance(width, bool):
        monitor["width"] = width
    height = value.get("height")
    if isinstance(height, int) and not isinstance(height, bool):
        monitor["height"] = height
    if isinstance(value.get("name"), str):
        monitor["name"] = value["name"]
    scale = value.get("scale")
    if isinstance(scale, (int, float)) and not isinstance(scale, bool):
        monitor["scale"] = scale
    return monitor


def launch(args: Iterable[str]) -> None:
    subprocess.Popen(
        list(args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def runtime_directory() -> Path:
    configured = os.environ.get("XDG_RUNTIME_DIR")
    parent = Path(configured) if configured else Path(tempfile.gettempdir()) / f"user-{os.getuid()}"
    directory = parent / "omarchy-lastpass"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_uid != os.getuid():
        raise PermissionError(f"runtime directory is not owned by the current user: {directory}")
    directory.chmod(0o700)
    return directory


def runtime_file(name: str) -> Path:
    return runtime_directory() / name


class OmarchySession:
    """Typed boundary around Omarchy, Hyprland, and desktop commands."""

    def clients(self) -> list[ClientInfo]:
        return [parse_client(value) for value in run_json_objects(["hyprctl", "clients", "-j"])]

    def monitors(self) -> list[MonitorInfo]:
        return [parse_monitor(value) for value in run_json_objects(["hyprctl", "monitors", "-j"])]

    def active_address(self) -> str:
        return str(run_json_object(["hyprctl", "activewindow", "-j"]).get("address", ""))

    def active_workspace(self) -> int | None:
        workspace = run_json_object(["hyprctl", "activeworkspace", "-j"]).get("id")
        return workspace if isinstance(workspace, int) else None

    def option(self, name: str, fallback: int) -> int:
        try:
            return int(run_json_object(["hyprctl", "getoption", name, "-j"]).get("int", fallback))
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return fallback

    def focus_window(self, address: str) -> None:
        cursor = run_json_object(["hyprctl", "cursorpos", "-j"])
        result = self._dispatch(f'hl.dsp.focus({{ window = "address:{address}" }})')
        if result.returncode:
            self._dispatch("focuswindow", f"address:{address}")
        if isinstance(cursor.get("x"), int) and isinstance(cursor.get("y"), int):
            self._dispatch(f"hl.dsp.cursor.move({{ x = {cursor['x']}, y = {cursor['y']} }})")

    def float_window(self, address: str) -> None:
        self._dispatch(f'hl.dsp.window.float({{ window = "address:{address}" }})')

    def resize_window(self, address: str, width: int, height: int) -> None:
        self._dispatch(
            f'hl.dsp.window.resize({{ x = {width}, y = {height}, window = "address:{address}" }})'
        )

    def move_window(self, address: str, x: int, y: int) -> None:
        self._dispatch(f'hl.dsp.window.move({{ x = {x}, y = {y}, window = "address:{address}" }})')

    def move_window_to_workspace(self, address: str, workspace: int) -> None:
        self._dispatch(
            f"hl.dsp.window.move({{ workspace = {workspace}, "
            f'window = "address:{address}", follow = false }})',
            check=True,
        )

    def close_window(self, address: str) -> None:
        result = self._dispatch(f'hl.dsp.window.close({{ window = "address:{address}" }})')
        if result.returncode:
            self._dispatch("closewindow", f"address:{address}")

    def set_focus_policy(self, follow_mouse: int, float_focus: int, *, check: bool = False) -> None:
        run(
            [
                "hyprctl",
                "eval",
                "hl.config({ input = { "
                f"follow_mouse = {follow_mouse}, float_switch_override_focus = {float_focus} "
                "} })",
            ],
            check=check,
        )

    def shell_call(self, method: str, payload: str | None = None) -> None:
        args = ["omarchy-shell", "-q", "joecastro.lastpass", method]
        if payload is not None:
            args.append(payload)
        run(args, check=False)

    def notify(self, message: str, critical: bool = False) -> None:
        sender = shutil.which("omarchy-notification-send")
        if sender:
            run(
                [
                    sender,
                    "-u",
                    "critical" if critical else "normal",
                    "LastPass Quick Access",
                    message,
                ],
                check=False,
            )
        else:
            print(f"LastPass Quick Access: {message}", file=sys.stderr)

    def launch_app(self, *args: str) -> None:
        launch(["uwsm-app", "--", *args])

    def open_default_browser(self, url: str) -> None:
        self.launch_app("xdg-open", url)

    def default_browser(self) -> str:
        try:
            return run(["xdg-settings", "get", "default-web-browser"], capture=True).stdout
        except subprocess.SubprocessError:
            return ""

    def has_close_shortcut(self) -> bool:
        return shutil.which("wtype") is not None

    def send_close_shortcut(self) -> None:
        run(["wtype", "-M", "ctrl", "-k", "w", "-m", "ctrl"], check=False)

    @staticmethod
    def _dispatch(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return run(["hyprctl", "dispatch", *arguments], check=check)


class FileLock:
    def __init__(self, path: Path, timeout: float | None) -> None:
        self.path = path
        self.timeout = timeout
        self.file: IO[str] | None = None

    def __enter__(self) -> FileLock:
        lock_file = self.path.open("a+", encoding="utf-8")
        self.file = lock_file
        deadline = None if self.timeout is None else time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if deadline is not None and time.monotonic() >= deadline:
                    lock_file.close()
                    raise TimeoutError(f"timed out waiting for {self.path}") from None
                time.sleep(0.02)

    def __exit__(self, *_: object) -> None:
        if self.file:
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()


def valid_size(value: str | None, default: int, minimum: int, maximum: int) -> int:
    if value and value.isdecimal() and minimum <= int(value) <= maximum:
        return int(value)
    return default


def natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(p)) if p.isdecimal() else (1, p.lower()) for p in re.split(r"([0-9]+)", value) if p
    )


def valid_popup(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and ".." not in Path(value).parts
        and re.fullmatch(r"[A-Za-z0-9._/-]+", value) is not None
    )


class LastPassPopup:
    def __init__(
        self,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        session: OmarchySession | None = None,
    ) -> None:
        self.requested_width, self.requested_height = width, height
        self.popup_width, self.popup_height = width, height
        self.session = session or OmarchySession()
        self.saved_follow_mouse: int | None = None
        self.saved_float_focus: int | None = None
        self.stop_requested = False

    @property
    def config_home(self) -> Path:
        return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))

    @property
    def proc_root(self) -> Path:
        return Path(os.environ.get("LASTPASS_PROC_ROOT", "/proc"))

    def discover(self, preferred: str = "auto") -> Installation | None:
        if preferred != "auto" and preferred not in BROWSER_BY_KEY:
            return None
        adapters = BROWSERS if preferred == "auto" else (BROWSER_BY_KEY[preferred],)
        for adapter in adapters:
            executable = adapter.installed_executable()
            if not executable:
                continue
            for extension_id in adapter.extension_ids:
                found = self._find_installation(
                    adapter,
                    executable,
                    adapter.config_root(self.config_home),
                    extension_id,
                )
                if found:
                    return found
        return None

    def _find_installation(
        self,
        adapter: BrowserAdapter,
        executable: str,
        root: Path,
        extension_id: str,
    ) -> Installation | None:
        if not root.is_dir():
            return None
        last_used = ""
        with suppress(OSError, ValueError, TypeError, KeyError):
            last_used = str(
                json.loads((root / "Local State").read_text(encoding="utf-8"))["profile"][
                    "last_used"
                ]
            )
        profiles = [p for p in root.iterdir() if p.is_dir()]
        profiles.sort(key=lambda p: (p.name != last_used, p.name != "Default", p.name))
        for profile in profiles:
            manifests = sorted(
                (profile / "Extensions" / extension_id).glob("*/manifest.json"),
                key=lambda p: natural_key(p.parent.name),
                reverse=True,
            )
            for path in manifests:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    continue
                popup = data.get("action", {}).get("default_popup") or data.get(
                    "browser_action", {}
                ).get("default_popup")
                if valid_popup(popup):
                    return Installation(
                        adapter,
                        executable,
                        profile.name,
                        popup,
                        extension_id,
                        str(data.get("version", "")),
                    )
        return None

    def clients(self) -> list[ClientInfo]:
        return self.session.clients()

    def monitors(self) -> list[MonitorInfo]:
        return self.session.monitors()

    def process_matches(self, adapter: BrowserAdapter, pid: int) -> bool:
        try:
            name = os.readlink(self.proc_root / str(pid) / "exe").rsplit("/", 1)[-1]
        except OSError:
            return False
        return adapter.matches_process(name)

    def matching_address(self, installation: Installation, vault: bool = False) -> str:
        prefix = (
            installation.adapter.vault_class_prefix()
            if vault
            else installation.adapter.popup_class_prefix(installation.extension_id)
        )
        for client in self.clients():
            pid = client.get("pid")
            if (
                client.get("class_", "").startswith(prefix)
                and pid is not None
                and self.process_matches(installation.adapter, pid)
            ):
                return str(client.get("address", ""))
        return ""

    def window_exists(self, address: str) -> bool:
        return any(c.get("address") == address for c in self.clients())

    def active_address(self) -> str:
        return self.session.active_address()

    def focus_window(self, address: str) -> None:
        self.session.focus_window(address)

    def hide_frame(self) -> None:
        self.session.shell_call("frameHide")

    def show_frame(self, address: str, installation: Installation) -> None:
        client = next((c for c in self.clients() if c.get("address") == address), None)
        monitor = next(
            (m for m in self.monitors() if client and m.get("id") == client.get("monitor")), None
        )
        if not monitor:
            return
        try:
            manifest = (PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8")
            plugin_version = str(json.loads(manifest).get("version", "unknown"))
        except (OSError, ValueError, TypeError):
            plugin_version = "unknown"
        payload = json.dumps(
            {
                "monitor": monitor.get("name", ""),
                "browser": installation.adapter.label,
                "pluginVersion": plugin_version,
                "extensionVersion": installation.version,
                "width": self.popup_width,
                "height": self.popup_height,
                "top": POPUP_TOP,
                "right": POPUP_RIGHT,
            },
            separators=(",", ":"),
        )
        self.session.shell_call("frameShow", payload)

    def place_popup(self, address: str) -> None:
        client = next((c for c in self.clients() if c.get("address") == address), None)
        monitor = next(
            (m for m in self.monitors() if client and m.get("id") == client.get("monitor")), None
        )
        if not client or not monitor:
            return
        scale = float(monitor.get("scale", 1)) or 1
        width, height = (
            int(float(monitor.get("width", 0)) / scale),
            int(float(monitor.get("height", 0)) / scale),
        )
        self.popup_width = min(self.requested_width, max(1, width - POPUP_RIGHT * 2))
        self.popup_height = min(
            self.requested_height, max(1, height - POPUP_TOP - FRAME_HEIGHT - POPUP_BOTTOM)
        )
        x = int(monitor.get("x", 0)) + width - self.popup_width - POPUP_RIGHT
        y = int(monitor.get("y", 0)) + POPUP_TOP
        if client.get("floating") is not True:
            self.session.float_window(address)
        self.session.resize_window(address, self.popup_width, self.popup_height)
        self.session.move_window(address, x, y)

    def dismiss(self, address: str, restore: str = "") -> None:
        self.hide_frame()
        if not self.window_exists(address):
            return
        self.session.close_window(address)
        for _ in range(10):
            if not self.window_exists(address):
                return
            time.sleep(0.02)
        if not self.session.has_close_shortcut():
            self.session.notify("wtype is required to dismiss the LastPass popup.", True)
            return
        if self.active_address() != address:
            self.focus_window(address)
            time.sleep(0.05)
        self.session.send_close_shortcut()
        if restore and restore != address:
            for _ in range(10):
                if not self.window_exists(address):
                    break
                time.sleep(0.02)
            if self.window_exists(restore):
                self.focus_window(restore)

    def managed_address(self) -> str:
        try:
            return runtime_file("managed").read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def write_managed(self, address: str) -> None:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(
            runtime_file("managed"),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | no_follow,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as state:
            state.write(address + "\n")

    def clear_managed(self, address: str) -> None:
        path = runtime_file("managed")
        if self.managed_address() == address:
            with suppress(FileNotFoundError):
                path.unlink()

    def wait_watcher(self) -> None:
        try:
            with FileLock(runtime_file("watch.lock"), 1):
                pass
        except TimeoutError:
            pass

    def dismiss_other(self, keep: str = "") -> None:
        address = self.managed_address()
        if address and address != keep:
            self.dismiss(address)
            self.wait_watcher()

    def focus_option(self, name: str, fallback: int) -> int:
        return self.session.option(name, fallback)

    def start_watcher(self, address: str, installation: Installation) -> None:
        launch(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "watch",
                address,
                installation.adapter.key,
                installation.version,
                str(self.requested_width),
                str(self.requested_height),
            ]
        )
        for _ in range(20):
            if (
                self.focus_option("input:follow_mouse", 1) == 0
                and self.focus_option("input:float_switch_override_focus", 1) == 0
            ):
                return
            time.sleep(0.01)

    def restore_focus(self) -> None:
        follow_mouse = self.saved_follow_mouse
        float_focus = self.saved_float_focus
        if follow_mouse not in range(4) or float_focus not in range(3):
            return
        assert follow_mouse is not None and float_focus is not None
        self.session.set_focus_policy(follow_mouse, float_focus)

    def watch(self, address: str, installation: Installation) -> None:
        try:
            lock = FileLock(runtime_file("watch.lock"), 0).__enter__()
        except TimeoutError:
            return
        try:
            self.write_managed(address)
            self.saved_follow_mouse = self.focus_option("input:follow_mouse", 1)
            self.saved_float_focus = self.focus_option("input:float_switch_override_focus", 1)
            for watched_signal in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                signal.signal(watched_signal, self._stop)
            self.session.set_focus_policy(0, 0, check=True)
            active = ""
            for _ in range(30):
                if self.stop_requested or not self.window_exists(address):
                    return
                active = self.active_address()
                if active == address:
                    break
                time.sleep(0.05)
            if active != address:
                return
            self._watch_popup(address, installation)
        finally:
            self.restore_focus()
            self.hide_frame()
            self.clear_managed(address)
            lock.__exit__(None, None, None)

    def _watch_popup(self, address: str, installation: Installation) -> None:
        while not self.stop_requested and self.window_exists(address):
            workspace = self.session.active_workspace()
            if workspace is not None:
                self._follow_workspace(address, installation, workspace)
            active = self.active_address()
            if active and active != address:
                # A workspace switch focuses its previous window before the
                # compositor has finished publishing the workspace change.
                # Give that transition one short cycle before treating it as
                # a click-away dismissal.
                time.sleep(0.05)
                workspace = self.session.active_workspace()
                if workspace is not None and self._follow_workspace(
                    address, installation, workspace
                ):
                    continue
                active = self.active_address()
                if not active or active == address:
                    continue
                self.dismiss(address, active)
                return
            time.sleep(0.25)

    def _follow_workspace(self, address: str, installation: Installation, workspace: int) -> bool:
        client = next((c for c in self.clients() if c.get("address") == address), None)
        popup_workspace = (client or {}).get("workspace", {}).get("id")
        if popup_workspace == workspace:
            return False
        self.session.move_window_to_workspace(address, workspace)
        self.place_popup(address)
        self.show_frame(address, installation)
        self.focus_window(address)
        return True

    def _stop(self, *_: object) -> None:
        self.stop_requested = True

    def open_store(self, preferred: str) -> int:
        adapter = BROWSER_BY_KEY.get(preferred)
        if preferred == "auto":
            desktop = self.session.default_browser()
            adapter = next(
                (browser for browser in BROWSERS if browser.matches_desktop(desktop)), None
            )
            if not adapter or not adapter.installed_executable():
                adapter = next(
                    (browser for browser in BROWSERS if browser.installed_executable()), None
                )
        executable = adapter.installed_executable() if adapter else None
        if not adapter or not executable:
            if preferred == "auto":
                message = "No supported browser is installed."
            elif adapter:
                message = f"{adapter.label} is not installed."
            else:
                message = f'Unknown browser "{preferred}".'
            self.session.notify(message, True)
            return 1
        self.session.notify(
            "LastPass is not installed in this browser. Opening its extension-store page."
        )
        self.session.launch_app(executable, adapter.store_url)
        return 0

    def launch_popup(self, installation: Installation) -> int:
        self.dismiss_other()
        self.session.launch_app(
            installation.executable,
            f"--profile-directory={installation.profile}",
            f"--app=chrome-extension://{installation.extension_id}/{installation.popup}",
        )
        for _ in range(40):
            time.sleep(0.1)
            address = self.matching_address(installation)
            if address:
                self.place_popup(address)
                self.show_frame(address, installation)
                self.start_watcher(address, installation)
                self.focus_window(address)
                return 0
        self.session.notify(
            "The browser started, but the LastPass extension menu did not appear.", True
        )
        return 1

    def open_popup(self, preferred: str) -> int:
        installation = self.discover(preferred)
        if not installation:
            return self.open_store(preferred)
        address = self.matching_address(installation)
        if not address:
            return self.launch_popup(installation)
        self.dismiss_other(address)
        self.place_popup(address)
        self.show_frame(address, installation)
        self.start_watcher(address, installation)
        self.focus_window(address)
        return 0

    def toggle(self, preferred: str) -> int:
        installation = self.discover(preferred)
        if not installation:
            return self.open_store(preferred)
        address = self.matching_address(installation)
        self.dismiss_other(address)
        if not address:
            return self.launch_popup(installation)
        self.dismiss(address)
        self.wait_watcher()
        return 0

    def open_vault(self, preferred: str) -> int:
        installation = self.discover(preferred)
        if not installation:
            return self.open_store(preferred)
        address = self.matching_address(installation, vault=True)
        if address:
            self.focus_window(address)
        else:
            self.session.launch_app(
                installation.executable,
                f"--profile-directory={installation.profile}",
                f"--app={VAULT_URL}",
            )
        return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args else "toggle"
    if action == "watch":
        if len(args) < 4 or not re.fullmatch(r"0x[0-9A-Fa-f]+", args[1]):
            return 2
        adapter = BROWSER_BY_KEY.get(args[2])
        if not adapter:
            return 2
        app = LastPassPopup(
            valid_size(args[4] if len(args) > 4 else None, DEFAULT_WIDTH, 280, 1200),
            valid_size(args[5] if len(args) > 5 else None, DEFAULT_HEIGHT, 320, 1400),
        )
        app.watch(args[1], Installation(adapter, "", "", "", "", args[3]))
        return 0
    browser = args[1] if len(args) > 1 else "auto"
    app = LastPassPopup(
        valid_size(args[2] if len(args) > 2 else None, DEFAULT_WIDTH, 280, 1200),
        valid_size(args[3] if len(args) > 3 else None, DEFAULT_HEIGHT, 320, 1400),
    )
    try:
        with FileLock(runtime_file("control.lock"), 5):
            if action == "toggle":
                return app.toggle(browser)
            if action == "open":
                return app.open_popup(browser)
            if action == "vault":
                return app.open_vault(browser)
            if action == "project":
                app.session.open_default_browser(PROJECT_URL)
                return 0
            if action == "install":
                return app.open_store(browser)
    except TimeoutError as error:
        app.session.notify(str(error), True)
        return 1
    print(f"Usage: {SCRIPT_PATH.name} {{toggle|open|vault|project|install}}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
