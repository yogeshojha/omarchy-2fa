import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Icon or pinned code, per the barDisplay setting.
Item {
  id: root

  property QtObject panel: null

  readonly property var host: panel ? panel.bar : null
  readonly property var pinned: panel ? panel.pinned : null
  readonly property string display: panel ? panel.barDisplay : "Icon"
  readonly property string vaultState: panel ? panel.vaultState : Model.VAULT_STARTING
  readonly property bool grouped: !panel || panel.groupDigits
  readonly property bool unlocked: !!panel && panel.vaultUnlocked
  readonly property double now: panel ? panel.vaultNow : 0
  readonly property color foreground: panel ? panel.barForeground : Color.foreground
  readonly property color urgent: panel ? panel.urgent : Color.urgent
  readonly property string fontFamily: panel ? panel.fontFamily : Style.font.family

  readonly property bool showsCode: display !== "Icon" && !!pinned && !!pinned.code
  readonly property real progress: unlocked ? Model.windowProgress(pinned, now) : 0
  readonly property bool expiring: unlocked && Model.isExpiring(pinned, now)
  readonly property color ringColor: expiring ? urgent : foreground
  readonly property color textColor: expiring ? urgent : foreground
  readonly property color trackColor: Util.alpha(foreground, 0.18)

  readonly property string codeText: {
    if (!showsCode) return ""
    if (display === "Code" || (panel && panel.opened)) return Model.groupCode(pinned.code, grouped)
    return Model.maskCode(pinned.digits, grouped)
  }

  readonly property string glyph: {
    if (vaultState === Model.VAULT_UNAVAILABLE) return "\uf071"
    return unlocked ? "\uf132" : "\uf023"
  }

  readonly property string tooltip: {
    if (vaultState === Model.VAULT_UNAVAILABLE) return "OmaFob: helper not running"
    if (vaultState === Model.VAULT_MISSING) return "OmaFob: set up your vault"
    if (vaultState === Model.VAULT_LOCKED) return "OmaFob: locked"
    return pinned ? "OmaFob: " + Model.accountTitle(pinned) : "OmaFob"
  }

  implicitWidth: slot.implicitWidth
  implicitHeight: slot.implicitHeight

  function toggle() {
    if (panel) panel.toggle()
  }

  Loader {
    id: slot
    anchors.fill: parent
    sourceComponent: root.showsCode ? codeSlot : iconSlot
  }

  Component {
    id: iconSlot

    BarIconButton {
      bar: root.host
      tooltipText: root.tooltip
      iconComponent: ringGlyph
      onPressed: function(button) { root.toggle() }
    }
  }

  Component {
    id: ringGlyph

    Item {
      CodeRing {
        anchors.fill: parent
        visible: root.progress > 0
        progress: root.progress
        ringColor: root.ringColor
        trackColor: root.trackColor
      }

      Text {
        anchors.centerIn: parent
        text: root.glyph
        color: root.textColor
        font.family: root.fontFamily
        font.pixelSize: Math.round(Style.bar.iconFont * 0.7)
      }
    }
  }

  Component {
    id: codeSlot

    WidgetButton {
      id: codeButton

      bar: root.host
      tooltipText: root.tooltip
      labelVisible: false
      hasVisualContent: true
      fixedWidth: vertical ? -1 : Math.round(codeRow.implicitWidth + scaledHorizontalMargin * 2)
      onPressed: function(button) { root.toggle() }

      Row {
        id: codeRow
        anchors.centerIn: parent
        spacing: Style.spacing.xs

        CodeRing {
          width: Math.round(Style.bar.iconCanvas * 0.62)
          height: width
          anchors.verticalCenter: parent.verticalCenter
          progress: root.progress
          ringColor: root.ringColor
          trackColor: root.trackColor
        }

        Text {
          anchors.verticalCenter: parent.verticalCenter
          text: root.codeText
          color: root.textColor
          font.family: root.fontFamily
          font.pixelSize: Style.bar.iconFont
          renderType: Text.NativeRendering
        }
      }
    }
  }
}
