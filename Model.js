var BAR_DISPLAYS = ["Icon", "Masked code", "Code"]
var AUTO_LOCK_OPTIONS = ["Never", "5 minutes", "15 minutes", "1 hour"]

var AUTO_LOCK_SECONDS = {
  "Never": 0,
  "5 minutes": 300,
  "15 minutes": 900,
  "1 hour": 3600
}

var CLIPBOARD_OPTIONS = ["Never", "15 seconds", "30 seconds", "1 minute", "2 minutes"]

var CLIPBOARD_SECONDS = {
  "Never": 0,
  "15 seconds": 15,
  "30 seconds": 30,
  "1 minute": 60,
  "2 minutes": 120
}

var EXPIRING_SECONDS = 5

// Vault states as reported by the helper.
var VAULT_STARTING = "starting"
var VAULT_MISSING = "missing"
var VAULT_LOCKED = "locked"
var VAULT_UNLOCKED = "unlocked"
var VAULT_UNAVAILABLE = "unavailable"

function number(value, fallback) {
  var parsed = Number(value)
  return isFinite(parsed) ? parsed : (fallback === undefined ? 0 : fallback)
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, number(value)))
}

function boolean(value, fallback) {
  if (typeof value === "boolean") return value
  if (typeof value === "string") {
    var normalized = value.trim().toLowerCase()
    if (normalized === "true" || normalized === "on" || normalized === "yes") return true
    if (normalized === "false" || normalized === "off" || normalized === "no") return false
  }
  return value === undefined || value === null ? fallback : !!value
}

function oneOf(value, options) {
  var candidate = String(value === undefined || value === null ? "" : value)
  return options.indexOf(candidate) >= 0 ? candidate : options[0]
}

function barDisplay(value) {
  return oneOf(value, BAR_DISPLAYS)
}

function autoLockSeconds(value) {
  return AUTO_LOCK_SECONDS[oneOf(value, AUTO_LOCK_OPTIONS)]
}

function clipboardSeconds(value) {
  return CLIPBOARD_SECONDS[oneOf(value, CLIPBOARD_OPTIONS)]
}

// -------------------------------------------------------------- searching

function searchText(account) {
  if (!account) return ""
  return ((account.issuer || "") + " " + (account.label || "")).toLowerCase()
}

function matches(account, query) {
  var terms = String(query || "").toLowerCase().split(/\s+/)
  var haystack = searchText(account)
  for (var i = 0; i < terms.length; i++) {
    if (terms[i] && haystack.indexOf(terms[i]) < 0) return false
  }
  return true
}

function filterAccounts(accounts, query) {
  var list = Array.isArray(accounts) ? accounts : []
  var trimmed = String(query || "").trim()
  if (!trimmed) return list
  return list.filter(function(account) { return matches(account, trimmed) })
}

// An empty pin falls back to the first account.
function findPinned(accounts, query) {
  var list = Array.isArray(accounts) ? accounts : []
  if (list.length === 0) return null
  var found = filterAccounts(list, query)
  return found.length > 0 ? found[0] : null
}

// -------------------------------------------------------------- formatting

function groupCode(code, grouped) {
  var text = String(code === undefined || code === null ? "" : code)
  if (!grouped || text.length < 6) return text
  var half = Math.ceil(text.length / 2)
  return text.slice(0, half) + " " + text.slice(half)
}

function maskCode(digits, grouped) {
  var count = Math.max(1, Math.round(number(digits, 6)))
  var dots = new Array(count + 1).join("•")
  return groupCode(dots, grouped)
}

function accountBadge(account) {
  var source = String((account && (account.issuer || account.label)) || "?").trim()
  return source ? source.charAt(0).toUpperCase() : "?"
}

function accountSubtitle(account) {
  if (!account) return ""
  return account.issuer ? (account.label || "") : ""
}

function accountTitle(account) {
  if (!account) return ""
  return account.issuer || account.label || "Unnamed account"
}

// -------------------------------------------------------------- countdown

function secondsLeft(account, now) {
  if (!account) return 0
  return Math.max(0, number(account.expiresAt) - number(now))
}

function windowProgress(account, now) {
  if (!account) return 0
  return clamp(secondsLeft(account, now) / Math.max(1, number(account.period, 30)), 0, 1)
}

function isExpiring(account, now) {
  return !!account && secondsLeft(account, now) <= EXPIRING_SECONDS
}

function soonestExpiry(accounts) {
  var list = Array.isArray(accounts) ? accounts : []
  var soonest = 0
  for (var i = 0; i < list.length; i++) {
    var at = number(list[i].expiresAt)
    if (at > 0 && (soonest === 0 || at < soonest)) soonest = at
  }
  return soonest
}

// -------------------------------------------------------------- messages

function pluralAccounts(count) {
  return count === 1 ? "1 account" : count + " accounts"
}

function importSummary(result) {
  var added = number(result && result.added)
  var skipped = number(result && result.skipped)
  var unsupported = number(result && result.unsupported)

  if (added === 0) return skipped > 0 ? "Those accounts are already in your vault" : "Nothing to import"

  var text = "Imported " + pluralAccounts(added)
  if (skipped > 0) text += " · " + skipped + " already saved"
  if (unsupported > 0) text += " · " + unsupported + " counter-based"
  return text
}

var ERROR_TEXT = {
  "bad-passphrase": "That passphrase does not open the vault",
  "wrong-current": "That is not your current passphrase",
  "cancelled": "Import cancelled",
  "clipboard": "Could not reach the clipboard",
  "locked": "The vault is locked",
  "no-qr": "No QR code found there",
  "unsupported": "Counter-based accounts cannot be copied yet",
  "vault-exists": "A vault already exists"
}

function sentence(text) {
  var value = String(text || "").replace(/^\s+|\s+$/g, "")
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : ""
}

function errorText(response) {
  if (!response) return "Something went wrong"
  return ERROR_TEXT[response.error] || sentence(response.message) || "Something went wrong"
}
