import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

BorderSurface {
  id: root

  property var account: null
  property bool selected: false
  property QtObject panel: null

  signal activated()
  signal hovered()
  signal pinRequested()
  signal removeRequested()

  readonly property color foreground: panel ? panel.foreground : Color.popups.text
  readonly property color accent: panel ? panel.accent : Color.accent
  readonly property color urgent: panel ? panel.urgent : Color.urgent
  readonly property color dim: panel ? panel.dim : Color.muted
  readonly property string fontFamily: panel ? panel.fontFamily : Style.font.family
  readonly property bool grouped: panel ? panel.groupDigits : true
  readonly property double now: panel ? panel.vaultNow : 0

  readonly property bool active: selected || pointer.containsMouse

  // `muted` is unreadable against the active row's fill.
  readonly property color subtle: active ? Util.alpha(foreground, 0.7) : dim
  readonly property bool expiring: Model.isExpiring(account, now)
  readonly property bool readable: !!account && account.supported && !!account.code
  readonly property color codeColor: expiring ? urgent : accent
  readonly property real ringSize: Style.space(24)

  radius: Style.cornerRadius
  color: selected ? Style.selectedFillFor(foreground, accent)
    : pointer.containsMouse ? Style.hoverFillFor(foreground, accent)
    : "transparent"
  borderSpec: selected ? Border.controlSpec("selected", foreground, accent) : Border.none()

  MouseArea {
    id: pointer
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: root.hovered()
    onClicked: root.activated()
  }

  // Children centre against the full row height.
  Row {
    anchors.left: parent.left
    anchors.right: actions.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.leftMargin: Style.spacing.sm
    anchors.rightMargin: Style.spacing.sm
    spacing: Style.spacing.md

    Item {
      width: root.ringSize
      height: root.ringSize
      anchors.verticalCenter: parent.verticalCenter

      CodeRing {
        anchors.fill: parent
        visible: root.readable
        progress: Model.windowProgress(root.account, root.now)
        ringColor: root.expiring ? root.urgent : root.accent
        trackColor: Util.alpha(root.foreground, 0.16)
      }

      Text {
        anchors.centerIn: parent
        text: Model.accountBadge(root.account)
        color: root.readable ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }
    }

    Column {
      width: parent.width - root.ringSize - parent.spacing
      anchors.verticalCenter: parent.verticalCenter
      spacing: 0

      Text {
        width: parent.width
        text: Model.accountTitle(root.account)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        visible: text !== ""
        text: Model.accountSubtitle(root.account)
        color: root.subtle
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideMiddle
      }
    }
  }

  Row {
    id: actions

    anchors.right: parent.right
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.rightMargin: Style.spacing.sm
    spacing: Style.spacing.xs

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.readable
      text: Model.groupCode(root.account ? root.account.code : "", root.grouped)
      color: root.codeColor
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      renderType: Text.NativeRendering
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: !root.readable
      text: root.account && root.account.error === "counter-based" ? "COUNTER" : "UNREADABLE"
      color: root.subtle
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    // Keeps the code column fixed as the cursor moves.
    PanelActionButton {
      anchors.verticalCenter: parent.verticalCenter
      opacity: root.active ? 1 : 0
      enabled: root.active
      iconText: "\uf08d"
      tooltipText: "Pin to the bar"
      foreground: root.subtle
      hoverColor: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      onClicked: root.pinRequested()
    }

    PanelActionButton {
      anchors.verticalCenter: parent.verticalCenter
      opacity: root.active ? 1 : 0
      enabled: root.active
      iconText: "\uf1f8"
      tooltipText: "Remove this account"
      foreground: root.subtle
      hoverColor: root.urgent
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      onClicked: root.removeRequested()
    }
  }
}
