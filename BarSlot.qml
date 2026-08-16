import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// The bar item. The countdown ring is off unless the setting turns it on.
Item {
  id: root

  property QtObject panel: null

  readonly property var host: panel ? panel.bar : null
  readonly property string vaultState: panel ? panel.vaultState : Model.VAULT_STARTING
  readonly property bool unlocked: !!panel && panel.vaultUnlocked
  readonly property double now: panel ? panel.vaultNow : 0
  readonly property color foreground: panel ? panel.barForeground : Color.foreground
  readonly property color urgent: panel ? panel.urgent : Color.urgent
  readonly property string fontFamily: panel ? panel.fontFamily : Style.font.family

  readonly property var next: unlocked && panel && panel.showRing
    ? Model.soonestAccount(panel.accounts)
    : null
  readonly property real progress: next ? Model.windowProgress(next, now) : 0
  readonly property bool expiring: !!next && Model.isExpiring(next, now)

  readonly property string glyph: {
    if (vaultState === Model.VAULT_UNAVAILABLE) return "\uf071"
    return unlocked ? "\uf132" : "\uf023"
  }

  readonly property string tooltip: {
    if (vaultState === Model.VAULT_UNAVAILABLE) return "OmaFob: helper not running"
    if (vaultState === Model.VAULT_MISSING) return "OmaFob: set up your vault"
    if (vaultState === Model.VAULT_LOCKED) return "OmaFob: locked"
    return "OmaFob"
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button

    anchors.fill: parent
    bar: root.host
    tooltipText: root.tooltip
    iconComponent: mark
    onPressed: function(pressedButton) { if (root.panel) root.panel.toggle() }
  }

  Component {
    id: mark

    Item {
      CodeRing {
        anchors.fill: parent
        visible: root.progress > 0
        progress: root.progress
        ringColor: root.expiring ? root.urgent : root.foreground
        trackColor: Util.alpha(root.foreground, 0.18)
      }

      Text {
        anchors.centerIn: parent
        text: root.glyph
        color: root.expiring ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Math.round(Style.bar.iconFont * (root.progress > 0 ? 0.7 : 1.0))
      }
    }
  }
}
