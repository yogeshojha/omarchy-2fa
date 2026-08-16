import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property QtObject panel: null

  spacing: Style.spacing.lg

  Toggle {
    width: parent.width
    label: "Privacy mode"
    description: "Never show a code. Enter still copies."
    checked: panel.privacyMode
    foreground: panel.foreground
    accent: panel.accent
    fontFamily: panel.fontFamily
    onClicked: panel.persist({ privacyMode: !panel.privacyMode })
  }

  Toggle {
    width: parent.width
    label: "Countdown ring"
    description: "Ring around the bar icon"
    checked: panel.showRing
    foreground: panel.foreground
    accent: panel.accent
    fontFamily: panel.fontFamily
    onClicked: panel.persist({ showRing: !panel.showRing })
  }

  PanelSeparator { foreground: panel.foreground }

  Dropdown {
    width: parent.width
    label: "Clear clipboard after"
    value: panel.clipboardWipe
    options: Model.CLIPBOARD_OPTIONS
    foreground: panel.foreground
    accent: panel.accent
    fontFamily: panel.fontFamily
    onChanged: function(value) { panel.persist({ clipboardWipe: value }) }
  }

  Dropdown {
    width: parent.width
    label: "Auto-lock vault"
    value: panel.autoLock
    options: Model.AUTO_LOCK_OPTIONS
    foreground: panel.foreground
    accent: panel.accent
    fontFamily: panel.fontFamily
    onChanged: function(value) { panel.persist({ autoLock: value }) }
  }

  Toggle {
    width: parent.width
    label: "Group digits"
    description: "Show 418 293 instead of 418293"
    checked: panel.groupDigits
    foreground: panel.foreground
    accent: panel.accent
    fontFamily: panel.fontFamily
    onClicked: panel.persist({ groupDigits: !panel.groupDigits })
  }

  PanelSeparator { foreground: panel.foreground }

  Row {
    width: parent.width
    spacing: Style.spacing.sm

    Button {
      text: "Import accounts"
      iconText: "\uf029"
      foreground: panel.foreground
      accent: panel.accent
      fontFamily: panel.fontFamily
      bordered: true
      onClicked: panel.scanRegion()
    }

    Button {
      text: "Change passphrase"
      foreground: panel.foreground
      accent: panel.accent
      fontFamily: panel.fontFamily
      bordered: true
      onClicked: panel.passphraseFormOpen = !panel.passphraseFormOpen
    }
  }

  Column {
    width: parent.width
    visible: panel.passphraseFormOpen
    spacing: Style.spacing.sm

    PassphraseField {
      id: currentPassphrase
      panel: root.panel
      placeholderText: "Current passphrase"
    }

    PassphraseField {
      id: nextPassphrase
      panel: root.panel
      placeholderText: "New passphrase"
    }

    PassphraseField {
      id: confirmPassphrase
      panel: root.panel
      placeholderText: "Repeat new passphrase"
      onAccepted: panel.changePassphrase(currentPassphrase.text, nextPassphrase.text, confirmPassphrase.text)
    }

    Button {
      text: "Save passphrase"
      foreground: panel.foreground
      accent: panel.accent
      fontFamily: panel.fontFamily
      bordered: true
      onClicked: panel.changePassphrase(currentPassphrase.text, nextPassphrase.text, confirmPassphrase.text)
    }
  }
}
