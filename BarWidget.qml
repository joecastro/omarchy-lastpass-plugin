pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "joecastro.lastpass"

  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace("file://", "")
  readonly property string browserPreference: String(setting("browser", "auto"))
  readonly property string popupWidth: String(setting("popupWidth", 420))
  readonly property string popupHeight: String(setting("popupHeight", 650))
  property bool frameOpen: false
  property string frameMonitor: ""
  property string frameBrowser: ""
  property string framePluginVersion: ""
  property string frameExtensionVersion: ""
  property int frameWidth: 420
  property int framePopupHeight: 650
  property int frameTop: 60
  property int frameRight: 20

  function applyFrame(payload: string): void {
    var data
    try {
      data = JSON.parse(payload)
    } catch (error) {
      return
    }
    root.frameMonitor = String(data.monitor || "")
    root.frameBrowser = String(data.browser || "")
    root.framePluginVersion = String(data.pluginVersion || "")
    root.frameExtensionVersion = String(data.extensionVersion || "")
    root.frameWidth = Math.max(280, Number(data.width) || 420)
    root.framePopupHeight = Math.max(320, Number(data.height) || 650)
    root.frameTop = Math.max(0, Number(data.top) || 60)
    root.frameRight = Math.max(0, Number(data.right) || 20)
    root.frameOpen = root.frameMonitor !== ""
  }

  function clearFrame(): void {
    root.frameOpen = false
  }

  function relayFrame(method: string, payload: var): void {
    var items = root.bar && typeof root.bar.moduleWidgets === "function"
      ? root.bar.moduleWidgets(root.moduleName) : [root]
    for (var i = 0; i < items.length; i++) {
      if (items[i] && typeof items[i][method] === "function") {
        if (payload === undefined) items[i][method]()
        else items[i][method](payload)
      }
    }
  }

  function toggleMenu(): void {
    Quickshell.execDetached([root.pluginDir + "/scripts/lastpass-popup", "toggle", root.browserPreference, root.popupWidth, root.popupHeight])
  }

  function openMenu(): void {
    Quickshell.execDetached([root.pluginDir + "/scripts/lastpass-popup", "open", root.browserPreference, root.popupWidth, root.popupHeight])
  }

  function openVault(): void {
    Quickshell.execDetached([root.pluginDir + "/scripts/lastpass-popup", "vault", root.browserPreference])
  }

  function openProject(): void {
    Quickshell.execDetached([root.pluginDir + "/scripts/lastpass-popup", "project"])
  }

  IpcHandler {
    target: "joecastro.lastpass"

    function toggle(): void { root.toggleMenu() }
    function open(): void { root.openMenu() }
    function vault(): void { root.openVault() }
    function frameShow(payload: string): void { root.relayFrame("applyFrame", payload) }
    function frameHide(): void { root.relayFrame("clearFrame") }
  }

  readonly property var anchorWindow: button.QsWindow.window
  readonly property string barMonitor: root.anchorWindow && root.anchorWindow.screen
    ? root.anchorWindow.screen.name : ""

  PanelWindow {
    id: popupFrame
    screen: root.anchorWindow ? root.anchorWindow.screen : null
    visible: root.frameOpen && root.barMonitor === root.frameMonitor
    implicitWidth: root.frameWidth
    implicitHeight: Math.max(32, Style.space(34))
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    anchors {
      top: true
      right: true
    }
    margins {
      top: root.frameTop + root.framePopupHeight
      right: root.frameRight
    }

    WlrLayershell.namespace: "omarchy-lastpass-frame"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    BorderSurface {
      id: frameSurface
      anchors.fill: parent
      color: Color.popups.background
      radius: Style.cornerRadius
      borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(1)))

      RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.spacing.md
        anchors.rightMargin: Style.spacing.md

        Text {
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          text: "LastPass · v" + root.framePluginVersion + " · " + root.frameBrowser
            + (root.frameExtensionVersion ? " · ext " + root.frameExtensionVersion : "")
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          color: Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          fontSizeMode: Text.Fit
          minimumPixelSize: Math.max(8, Style.font.bodySmall - 2)
        }
      }

      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.openProject()
      }
    }
  }

  Component {
    id: lastPassLogo

    Item {
      Item {
        id: artwork
        anchors.centerIn: parent
        width: parent.width * 0.8
        height: parent.height * 0.8

        Rectangle {
          anchors.fill: parent
          radius: width * 0.16
          color: "#d32d27"
        }

        Repeater {
          model: [0.13, 0.36, 0.59]
          delegate: Rectangle {
            required property real modelData
            x: artwork.width * modelData
            y: artwork.height * 0.41
            width: artwork.width * 0.17
            height: width
            radius: width / 2
            color: "white"
          }
        }

        Rectangle {
          x: artwork.width * 0.82
          y: artwork.height * 0.24
          width: Math.max(1, artwork.width * 0.055)
          height: artwork.height * 0.52
          radius: width / 2
          color: "white"
        }
      }
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    iconComponent: lastPassLogo
    opticalSize: Style.bar.iconCanvas
    tooltipText: "LastPass Quick Access · click to toggle menu · right-click for vault"

    onPressed: function(b) {
      if (b === Qt.RightButton) root.openVault()
      else root.toggleMenu()
    }
  }
}
